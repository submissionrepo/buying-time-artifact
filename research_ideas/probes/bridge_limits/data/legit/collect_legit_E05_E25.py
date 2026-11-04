"""Legitimate release history before the failure, for E05 (lock proxy custody) and E25 (Ethereum vault).

Inputs  results/incidents.csv                   (failure times; read only)
        data/incidents/onchain_targets.json     (release-point contracts; read only)
Outputs data/legit/<ID>.csv                      (no addresses or hashes)
        data/legit/raw/<ID>/                     (raw RPC and price caches; addresses live only here)
        data/legit/raw/<ID>/summary.json         (numbers quoted in the README)

Method
- Window: [t_fail - 150 d, t_fail - 1 s], t_fail = first unauthorized release (block timestamp).
- Release record: the bridge's own release event, from the public source code.
    E05 lock proxy (polynetwork/eth-contracts, LockProxy.sol): UnlockEvent(address toAssetHash,
        address toAddress, uint256 amount), all fields non-indexed; toAssetHash == 0 means native coin.
    E25 vault (orbit-chain/bridge-contract, EthVault.impl.sol): Withdraw(string fromChain, bytes fromAddr,
        bytes toAddr, bytes token, bytes32[] bytes32s, uint[] uints, bytes data); uints[0] = amount;
        token == 0 means native coin.
- ERC-20 releases: Transfer logs with the contract as sender (topic1), kept when the same transaction holds a
  release event of the same contract (E05 also requires the token to equal the event's asset). Outflows in
  transactions without a release event are excluded and counted (fee forwarding, farm transfers, admin moves).
- Native releases: from the release event with a zero asset (E05 UnlockEvent; E25 Withdraw). For E25 the cached
  call traces of the first 194,000 blocks serve as a cross-check (identical transaction and amount sets).
- E25 ERC-20 transfers whose token differs from the event's token are matched on transaction and equal amount.
- BSC (E05): ERC-20 releases from UnlockEvent alone (kind "event"); Transfer logs not fetched.
- Release events with an ERC-20 asset but no matching Transfer log enter as kind "event" (amount from the event).
- Exclusions: transfers to the contract itself or to another leg's contract; for E05, releases at or after the
  leg's keeper-key replacement (signed by the replacement key, part of the failure).
- Prices: DefiLlama /chart hourly series (nearest point within 2 h) for the most frequent assets; otherwise the
  daily series (nearest point within 36 h); otherwise unpriced. One coin per request (pricing.chart).
- BSC log responses carry no block timestamps; timestamps are interpolated linearly between block headers
  sampled every ANCHOR_STEP blocks, and the error of that interpolation is measured on a sample of exact headers.
Run: python -I data/legit/collect_legit_E05_E25.py E05|E25
"""
import bisect
import collections
import csv
import datetime
import json
import pathlib
import sys
import time
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT / "incidents"))
from rpc import Rpc, TRANSFER, topic_addr, addr_from_topic, erc20_meta  # noqa: E402
sys.path.insert(0, str(HERE))
import pricing  # noqa: E402

UNLOCK = "0xd90288730b87c2b8e0c45bd82260fd22478aba30ae1c4d578b8daba9261604df"   # UnlockEvent(address,address,uint256)
WITHDRAW = "0xa866edf1861d39a9973d7892f3869e1bb4b76bc00d216872c1dd2bc547f2da2e"  # Withdraw(string,bytes,bytes,bytes,bytes32[],uint256[],bytes)
def _sel(sig):
    from Crypto.Hash import keccak
    h = keccak.new(digest_bits=256)
    h.update(sig.encode())
    return "0x" + h.hexdigest()[:8]


SEL_MANAGER_PROXY = _sel("managerProxyContract()")  # present on lock proxies of the same bridge

WINDOW_S = 150 * 86400
# Issuer-pegged tokens (Binance-Peg on BSC, Poly-peg ONT on Ethereum; 1:1 redeemable) whose own DefiLlama series is empty for 2021: priced from
# the series of the underlying coin. Used only when the token's own series has no point within tolerance.
PEG = {"bsc:0xe9e7cea3dedca5984780bafc599bd69add087d56": "coingecko:binance-usd",       # BUSD
       "bsc:0x8ac76a51cc950d9822d68b83fe1ad97b32cd580d": "coingecko:usd-coin",          # USDC (Binance-Peg)
       "bsc:0x55d398326f99059ff775485246999027b3197955": "coingecko:tether",            # USDT (Binance-Peg)
       "bsc:0x2170ed0880ac9a755fd29b2688956bd959f933f8": "coingecko:ethereum",          # ETH (Binance-Peg)
       "bsc:0x7130d2a12b9bcbfae4f2634d864a1ee1ce3ead9c": "coingecko:bitcoin",          # BTCB (Binance-Peg)
       # pONT (name "Poly Ontology Token"): this bridge's own 1:1 peg of ONT, no own series in 2021
       "ethereum:0xcb46c550539ac3db72dc7af7c89b11c306c727c2": "coingecko:ontology"}
ANCHOR_STEP = 1000
NATIVE_CID = {"ethereum": "coingecko:ethereum", "bsc": "coingecko:binancecoin"}
NATIVE_SYM = {"ethereum": "ETH", "bsc": "BNB"}


def iso(ts):
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def to_ts(s):
    return int(datetime.datetime.fromisoformat(s.replace("Z", "")).replace(tzinfo=datetime.timezone.utc).timestamp())


# t_fail: E05 = first release on any leg (incidents.csv first_release_utc). E25 = first unauthorized release per the
# corrected selection in incidents.csv notes (30.095 ETH at 20:52:47 UTC, reported there as preliminary; the
# first_release_utc column holds the first large release at 21:07:59).
CFG = {
    "E05": {
        "t_fail": "2021-08-10T09:51:02Z",
        "legs": [
            {"leg": "Ethereum lock proxy", "chain": "ethereum", "mode": "poly", "target": "E05_eth",
             "cut_utc": "2021-08-10T09:48:40Z", "step": 5000},
            # BSC release contract: the emitter of UnlockEvent in the documented BSC failure blocks
            # (incidents.csv: bscscan blocks 9906162 to 9906550).
            {"leg": "BSC lock proxy", "chain": "bsc", "mode": "poly", "derive_blocks": [9906162, 9906550],
             "cut_utc": "2021-08-10T09:33:07Z", "step": 5000, "unlock_step": 50000,
             # BSC: ERC-20 releases are taken from UnlockEvent (amount = value passed to the token transfer in
             # LockProxy.unlock), so Transfer logs are not fetched; anchors every 5000 blocks (about 4 h).
             "erc20_from_event": True, "anchor_step": 5000},
        ],
        "skipped_legs": {"Polygon lock proxy": "only public endpoint answering historical eth_getLogs (polygon.drpc.org) "
                         "caps ranges at 50 blocks (about 118,000 calls for 150 days); 1rpc.io/matic over plan limit; "
                         "polygon-rpc.com 401; rpc.ankr.com/polygon requires a key; publicnode reset the connection; "
                         "polygon.llamarpc.com did not resolve (tested 2026-10-16)"},
    },
    "E25": {
        "t_fail": "2023-12-31T20:52:47Z",
        "legs": [
            # Native releases from Withdraw (token == 0). Traces were fetched for the first 194,000 blocks
            # only; they serve as a cross-check there (no further trace requests).
            {"leg": "Ethereum vault", "chain": "ethereum", "mode": "orbit", "target": "E25_eth", "step": 5000,
             "native_from_event": True, "trace_cache_only": True},
        ],
        "skipped_legs": {},
    },
}


def http_json(url, tries=5):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "bridge-limits-probe/1.0"})
            with urllib.request.urlopen(req, timeout=90) as r:
                return json.loads(r.read().decode())
        except Exception as e:
            last = e
            time.sleep(2 * (i + 1))
    raise RuntimeError(f"{url[:120]}: {last}")


class ChunkCache:
    """Append-only JSONL cache of range queries, so that interrupted runs resume."""

    def __init__(self, path):
        self.path = path
        self.done = {}
        if path.exists():
            for line in path.read_text().splitlines():
                if line.strip():
                    j = json.loads(line)
                    self.done[(j["b0"], j["b1"])] = j["res"]

    def get(self, b0, b1, fn):
        if (b0, b1) not in self.done:
            res = fn()
            with self.path.open("a") as f:
                f.write(json.dumps({"b0": b0, "b1": b1, "res": res}) + "\n")
            self.done[(b0, b1)] = res
        return self.done[(b0, b1)]


def ranged(rpc, method_fn, b0, b1, step, cache, label):
    """Fixed chunk grid (so the cache keys are stable); a chunk that fails on range is split in four."""
    out = []
    b = b0
    n = 0
    while b <= b1:
        e = min(b + step - 1, b1)
        try:
            out += cache.get(b, e, lambda: method_fn(b, e))
        except Exception as ex:
            if step <= 50:
                raise
            print(f"   {label}: split {b}-{e} ({str(ex)[:80]})", flush=True)
            out += ranged(rpc, method_fn, b, e, max(50, step // 4), cache, label)
        b = e + 1
        n += 1
        if n % 50 == 0:
            print(f"   {label}: block {e} / {b1}, rows {len(out)}", flush=True)
    return out


def abi_words(data):
    h = data[2:]
    return [h[i:i + 64] for i in range(0, len(h), 64)]


def abi_bytes(words, off_word):
    off = int(words[off_word], 16) // 32
    n = int(words[off], 16)
    raw = "".join(words[off + 1:off + 1 + (n + 31) // 32])[:2 * n]
    return raw


def abi_uint_array(words, off_word):
    off = int(words[off_word], 16) // 32
    n = int(words[off], 16)
    return [int(words[off + 1 + i], 16) for i in range(n)]


def parse_release(lg, mode):
    w = abi_words(lg["data"])
    if mode == "poly":
        return {"asset": "0x" + w[0][-40:], "to": "0x" + w[1][-40:], "amount": int(w[2], 16)}
    # orbit Withdraw(string, bytes fromAddr, bytes toAddr, bytes token, bytes32[], uint[], bytes)
    to = abi_bytes(w, 2)
    tok = abi_bytes(w, 3)
    uints = abi_uint_array(w, 5)
    return {"asset": "0x" + tok.rjust(40, "0")[-40:], "to": "0x" + to[-40:], "amount": uints[0] if uints else 0,
            "uints": uints}


class Prices:
    def __init__(self, cdir, t0, t1):
        self.cdir = cdir / "prices"
        self.cdir.mkdir(parents=True, exist_ok=True)
        self.t0, self.t1 = t0, t1
        self.daily, self.hourly, self.conf = {}, {}, {}

    def load_daily(self, cids):
        # one coin per request (a multi-coin request returned HTTP 400 on 2026-10-16); shared helper pricing.chart
        for c in cids:
            if c in self.daily:
                continue
            pts = pricing.chart(c, self.t0, self.t1, "1d", self.cdir, search_width=43200)
            self.daily[c] = sorted((q[0], q[1]) for q in pts)
            self.conf[c] = pts[0][2] if pts else None

    def load_hourly(self, cid):
        if cid in self.hourly:
            return
        pts = pricing.chart(cid, self.t0, self.t1, "1h", self.cdir, search_width=1800)
        self.hourly[cid] = sorted((q[0], q[1]) for q in pts)

    @staticmethod
    def _near(series, ts, tol):
        if not series:
            return None
        i = bisect.bisect_left(series, (ts, -1e300))
        best = None
        for j in (i - 1, i):
            if 0 <= j < len(series):
                d = abs(series[j][0] - ts)
                if d <= tol and (best is None or d < best[0]):
                    best = (d, series[j][1])
        return None if best is None else best[1]

    def price(self, cid, ts):
        for c, tag in ((cid, ""), (PEG.get(cid), " (issuer peg, underlying series)")):
            if c is None:
                continue
            p = self._near(self.hourly.get(c, []), ts, 2 * 3600)
            if p is not None:
                return p, "defillama chart 1h" + tag
            p = self._near(self.daily.get(c, []), ts, 36 * 3600)
            if p is not None:
                return p, "defillama chart 1d" + tag
        return None, ""


class BlockTimes:
    """Exact timestamps from log fields or headers; on chains whose logs lack them, interpolation between anchors."""

    def __init__(self, rpc, cdir, b0, b1, chain, step=ANCHOR_STEP):
        self.rpc = rpc
        self.step = step
        self.p = cdir / f"block_ts_{chain}.json"
        self.c = {int(k): v for k, v in json.loads(self.p.read_text()).items()} if self.p.exists() else {}
        self.b0, self.b1 = b0, b1
        self.anchors = None

    def save(self):
        self.p.write_text(json.dumps(self.c))

    def exact(self, b):
        if b not in self.c:
            self.c[b] = self.rpc.block_ts(b)
            if len(self.c) % 200 == 0:
                self.save()
        return self.c[b]

    def build_anchors(self):
        bs = list(range(self.b0, self.b1 + 1, self.step)) + [self.b1]
        for i, b in enumerate(bs):
            self.exact(b)
            if i % 200 == 0:
                print(f"   anchors {i}/{len(bs)}", flush=True)
        self.save()
        self.anchors = sorted((b, self.c[b]) for b in set(bs))

    def interp(self, b):
        if b in self.c:
            return self.c[b]
        i = bisect.bisect_right(self.anchors, (b, 1e18))
        (ba, ta), (bb, tb) = self.anchors[i - 1], self.anchors[min(i, len(self.anchors) - 1)]
        if bb == ba:
            return ta
        return int(round(ta + (tb - ta) * (b - ba) / (bb - ba)))


def collect_leg(eid, L, t_fail, cdir, targets, all_custody):
    chain = L["chain"]
    rpc = Rpc(chain)
    if chain == "ethereum":
        rpc.urls = ["https://rpc.mevblocker.io", "https://mainnet.gateway.tenderly.co"]
    else:
        rpc.urls = rpc.urls[:1]
    if "target" in L:
        custody = [a.lower() for a in targets[L["target"]]["custody"]]
    else:
        lg = rpc.call("eth_getLogs", [{"topics": [UNLOCK], "fromBlock": hex(L["derive_blocks"][0]),
                                       "toBlock": hex(L["derive_blocks"][1])}])
        emit = collections.Counter(x["address"].lower() for x in lg)
        custody = [emit.most_common(1)[0][0]]
        L["derived"] = {"n_events_in_failure_blocks": emit.most_common(1)[0][1], "n_emitters": len(emit)}
    ldir = cdir / chain
    ldir.mkdir(parents=True, exist_ok=True)
    (ldir / "contracts.json").write_text(json.dumps({"custody": custody, "leg": L["leg"]}, indent=1))
    t0, t1 = t_fail - WINDOW_S, t_fail - 1
    bfile = ldir / "blocks.json"
    if bfile.exists():
        b0, b1 = json.loads(bfile.read_text())
    else:
        b0 = rpc.block_at(t0)
        b1 = rpc.block_at(t_fail) - 1
        bfile.write_text(json.dumps([b0, b1]))
    print(f"== {eid} {L['leg']}: blocks {b0}-{b1}", flush=True)
    topic0 = UNLOCK if L["mode"] == "poly" else WITHDRAW
    rel, xfer, trc = [], [], []
    for c in custody:
        rel += ranged(rpc, lambda a, b: rpc.call("eth_getLogs", [{"address": c, "topics": [topic0],
                                                                    "fromBlock": hex(a), "toBlock": hex(b)}]),
                      b0, b1, L.get("unlock_step", L["step"]), ChunkCache(ldir / f"release_{c[2:10]}.jsonl"), "release")
        if not L.get("erc20_from_event"):
            xfer += ranged(rpc, lambda a, b: rpc.call("eth_getLogs", [{"topics": [TRANSFER, topic_addr(c)],
                                                                         "fromBlock": hex(a), "toBlock": hex(b)}]),
                           b0, b1, L["step"], ChunkCache(ldir / f"transfer_{c[2:10]}.jsonl"), "transfer")
        if L.get("trace_cache_only"):
            tc = ChunkCache(ldir / f"trace_{c[2:10]}.jsonl")
            for v in tc.done.values():
                trc += v
            L["trace_range"] = [min(k[0] for k in tc.done), max(k[1] for k in tc.done),
                                sum(k[1] - k[0] + 1 for k in tc.done)] if tc.done else None
        if L.get("trace"):
            rt = Rpc(chain + "_trace")
            trc += ranged(rt, lambda a, b: rt.call("trace_filter", [{"fromBlock": hex(a), "toBlock": hex(b),
                                                                       "fromAddress": [c]}]) or [],
                          b0, b1, L["trace_step"], ChunkCache(ldir / f"trace_{c[2:10]}.jsonl"), "trace")
    return rpc, custody, b0, b1, rel, xfer, trc


def main(eid):
    cfg = CFG[eid]
    t_fail = to_ts(cfg["t_fail"])
    t0, t1 = t_fail - WINDOW_S, t_fail - 1
    cdir = HERE / "raw" / eid
    cdir.mkdir(parents=True, exist_ok=True)
    targets = json.loads((ROOT / "data" / "incidents" / "onchain_targets.json").read_text())
    rows, excluded, legs_info = [], collections.Counter(), []
    match_notes = collections.Counter()
    collected = []
    for L in cfg["legs"]:
        collected.append((L, collect_leg(eid, L, t_fail, cdir, targets, None)))
    all_custody = {c for _, (_, cust, *_r) in collected for c in cust}
    prices = Prices(cdir, t0, t1)
    pending = []  # rows before pricing
    for L, (rpc, custody, b0, b1, rel, xfer, trc) in collected:
        chain = L["chain"]
        ldir = cdir / chain
        bt = BlockTimes(rpc, ldir, b0, b1, chain, L.get("anchor_step", ANCHOR_STEP))
        need_interp = any("blockTimestamp" not in x for x in rel + xfer)
        if need_interp:
            bt.build_anchors()

        def ts_of(x):
            if x.get("blockTimestamp"):
                return int(x["blockTimestamp"], 16)
            b = int(x["blockNumber"], 16) if isinstance(x["blockNumber"], str) else x["blockNumber"]
            return bt.interp(b) if need_interp else bt.exact(b)

        cut = to_ts(L["cut_utc"]) if L.get("cut_utc") else None
        meta = {}
        meta_p = ldir / "token_meta.json"
        if meta_p.exists():
            meta = {k: tuple(v) for k, v in json.loads(meta_p.read_text()).items()}
        ev_by_tx = collections.defaultdict(list)
        for lg in rel:
            if lg.get("removed"):
                continue
            ev = parse_release(lg, L["mode"])
            ev.update({"ts": ts_of(lg), "block": int(lg["blockNumber"], 16), "tx": lg["transactionHash"],
                       "li": int(lg["logIndex"], 16), "matched": False})
            ev_by_tx[lg["transactionHash"]].append(ev)
        n_events = sum(len(v) for v in ev_by_tx.values())

        def add(ts, kind, tok, raw, to, ev=None):
            if tok == "native":
                sym, dec, cid = NATIVE_SYM[chain], 18, NATIVE_CID[chain]
            else:
                sym, dec = erc20_meta(rpc, tok, meta)
                cid = f"{chain}:{tok}"
            pending.append({"ts": ts, "leg": L["leg"], "chain": chain, "asset": sym or "?", "token": tok, "cid": cid,
                            "amount": raw / 10 ** dec, "raw": str(raw), "kind": kind, "to": to})

        # ERC-20 transfers out
        unmatched_out = []
        seen_logs = set()
        for lg in xfer:
            if lg.get("removed") or len(lg["topics"]) != 3:
                if len(lg["topics"]) != 3:
                    excluded["nft_or_nonstandard_transfer_log"] += 1
                continue
            k = (lg["transactionHash"], lg["logIndex"])
            if k in seen_logs:
                continue
            seen_logs.add(k)
            ts = ts_of(lg)
            if ts > t1 or ts < t0:
                excluded["outside_window"] += 1
                continue
            to = addr_from_topic(lg["topics"][2]).lower()
            tok = lg["address"].lower()
            raw = int(lg["data"], 16) if lg["data"] not in ("0x", "") else 0
            evs = ev_by_tx.get(lg["transactionHash"], [])
            if to in all_custody:
                excluded["to_bridge_contract"] += 1
                continue
            if not evs:
                excluded["erc20_out_without_release_event"] += 1
                unmatched_out.append({"kind": "erc20", "ts": ts, "token": tok, "raw": str(raw), "to": to,
                                      "tx": lg["transactionHash"]})
                continue
            if L["mode"] == "poly":
                m = [e for e in evs if e["asset"] == tok and not e["matched"]]
                if not m:
                    excluded["erc20_out_token_not_in_release_event"] += 1
                    continue
                m[0]["matched"] = True
            else:
                m = [e for e in evs if e["asset"] == tok and not e["matched"]]
                if not m:
                    # the event names another token address than the one transferred (token mapping in the
                    # vault); match on the same transaction and equal amount, keep the transferred token
                    m = [e for e in evs if e["amount"] == raw and not e["matched"]]
                    if m:
                        match_notes["erc20_matched_by_amount_event_token_differs"] += 1
                if not m:
                    excluded["erc20_out_token_not_in_release_event"] += 1
                    continue
                m[0]["matched"] = True
            if cut is not None and ts >= cut:
                excluded["after_keeper_replacement"] += 1
                continue
            add(ts, "erc20", tok, raw, to)
        # native outflows
        if L["mode"] == "poly" or L.get("native_from_event"):
            for evs in ev_by_tx.values():
                for e in evs:
                    if e["asset"] != "0x" + "0" * 40:
                        continue
                    e["matched"] = True
                    if e["to"] in all_custody:
                        excluded["to_bridge_contract"] += 1
                        continue
                    if cut is not None and e["ts"] >= cut:
                        excluded["after_keeper_replacement"] += 1
                        continue
                    add(e["ts"], "native", "native", e["amount"], e["to"])
        if L.get("trace_cache_only") and L.get("trace_range"):
            tb0, tb1, tcov = L["trace_range"]
            ev_nat = {(tx, e["amount"]) for tx, v in ev_by_tx.items() for e in v
                      if e["asset"] == "0x" + "0" * 40 and tb0 <= e["block"] <= tb1}
            tr_nat, no_ev = set(), []
            for x in trc:
                a = x.get("action", {})
                v = int(a.get("value", "0x0"), 16)
                if x.get("type") != "call" or x.get("error") or v == 0:
                    continue
                if x["transactionHash"] in ev_by_tx:
                    tr_nat.add((x["transactionHash"], v))
                else:
                    no_ev.append(v)
                    excluded["native_out_without_release_event_trace_range"] += 1
                    unmatched_out.append({"kind": "native", "block": x["blockNumber"], "token": "native",
                                          "raw": str(v), "to": (a.get("to") or "").lower(),
                                          "tx": x["transactionHash"]})
            L["trace_check"] = {"blocks": [tb0, tb1], "blocks_covered": tcov,
                                "native_release_events": len(ev_nat), "native_traces_in_release_txs": len(tr_nat),
                                "identical_sets": ev_nat == tr_nat,
                                "native_outflows_without_release_event": len(no_ev),
                                "native_without_event_eth": sum(no_ev) / 1e18}
        elif L["mode"] != "poly":
            for x in trc:
                a = x.get("action", {})
                if x.get("type") != "call" or a.get("callType") not in ("call", None) or x.get("error"):
                    if x.get("error") and int(a.get("value", "0x0"), 16) > 0:
                        excluded["native_trace_reverted"] += 1
                    continue
                v = int(a.get("value", "0x0"), 16)
                if v == 0:
                    continue
                blk = x["blockNumber"]
                ts = bt.exact(blk)
                to = (a.get("to") or "").lower()
                if ts > t1 or ts < t0:
                    excluded["outside_window"] += 1
                    continue
                if to in all_custody:
                    excluded["to_bridge_contract"] += 1
                    continue
                evs = ev_by_tx.get(x["transactionHash"], [])
                if not evs:
                    excluded["native_out_without_release_event"] += 1
                    unmatched_out.append({"kind": "native", "ts": ts, "token": "native", "raw": str(v), "to": to,
                                          "tx": x["transactionHash"]})
                    continue
                for e in evs:
                    if e["asset"] == "0x" + "0" * 40:
                        e["matched"] = True
                add(ts, "native", "native", v, to)
        bt.save()
        # release events without a matching transfer
        unmatched_ev = []
        for evs in ev_by_tx.values():
            for e in evs:
                if not e["matched"]:
                    unmatched_ev.append(e)
                    if e["ts"] > t1 or e["ts"] < t0:
                        excluded["outside_window"] += 1
                        continue
                    if cut is not None and e["ts"] >= cut:
                        excluded["after_keeper_replacement"] += 1
                        continue
                    if e["asset"] == "0x" + "0" * 40:
                        add(e["ts"], "event", "native", e["amount"], e["to"])
                    else:
                        add(e["ts"], "event", e["asset"], e["amount"], e["to"])
        meta_p.write_text(json.dumps(meta))
        (ldir / "unmatched_release_events.json").write_text(json.dumps(unmatched_ev, indent=0))
        (ldir / "outflows_without_release_event.json").write_text(json.dumps(unmatched_out, indent=0))
        info = {"leg": L["leg"], "chain": chain, "block_from": b0, "block_to": b1, "n_release_events": n_events,
                "n_transfer_logs": len(xfer), "n_traces": len(trc), "n_unmatched_release_events": len(unmatched_ev),
                "timestamps": "interpolated between headers every %d blocks" % bt.step if need_interp
                else "block timestamps in log responses / headers"}
        if L.get("derived"):
            info["contract_derivation"] = L["derived"]
        if L.get("trace_check"):
            info["trace_check"] = L["trace_check"]
        if need_interp:
            # measure the interpolation error on exact headers of sampled release blocks
            sample = sorted({e["block"] for v in ev_by_tx.values() for e in v})[::max(1, n_events // 150)][:150]
            errs = []
            for b in sample:
                ex = bt.exact(b)
                i = bisect.bisect_right(bt.anchors, (b, 1e18))
                (ba, ta), (bb, tb) = bt.anchors[i - 1], bt.anchors[min(i, len(bt.anchors) - 1)]
                est = ta if bb == ba else round(ta + (tb - ta) * (b - ba) / (bb - ba))
                errs.append(abs(est - ex))
            bt.save()
            info["interp_error_s"] = {"n": len(errs), "max": max(errs) if errs else None,
                                      "mean": sum(errs) / len(errs) if errs else None}
        legs_info.append(info)
    # own-contract check on the largest recipients (lock proxies answer managerProxyContract())
    own = set()
    by_to = collections.Counter()
    for r in pending:
        by_to[(r["chain"], r["to"])] += 1
    rpcs = {L["chain"]: rp for L, (rp, *_r) in collected}
    checked = 0
    for (chain, to), n in by_to.most_common(60):
        try:
            code = rpcs[chain].call("eth_getCode", [to, "latest"])
        except Exception:
            continue
        if code and len(code) > 2:
            try:
                r_ = rpcs[chain].eth_call(to, SEL_MANAGER_PROXY)
                if r_ and len(r_) >= 66 and int(r_, 16) != 0:
                    own.add((chain, to))
            except Exception:
                pass
        checked += 1
    (cdir / "own_contract_recipients.json").write_text(json.dumps(sorted(own)))
    kept = []
    for r in pending:
        if (r["chain"], r["to"]) in own:
            excluded["to_same_bridge_proxy_contract"] += 1
            continue
        kept.append(r)
    # prices
    cnt = collections.Counter(r["cid"] for r in kept)
    peg_used = sorted({PEG[c] for c in cnt if c in PEG})
    prices.load_daily(sorted(cnt) + peg_used)
    for cid, _n in cnt.most_common(12):
        prices.load_hourly(cid)
        if cid in PEG:
            prices.load_hourly(PEG[cid])
    for r in kept:
        p, src = prices.price(r["cid"], r["ts"])
        r["price"], r["src"] = p, src
        r["usd"] = r["amount"] * p if p is not None else None
    kept.sort(key=lambda r: (r["ts"], r["leg"]))
    with (HERE / f"{eid}.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ts_utc", "leg", "asset", "amount", "usd", "kind", "priced"])
        for r in kept:
            w.writerow([iso(r["ts"]), r["leg"], r["asset"], repr(r["amount"]) if r["amount"] < 1e-6 else f"{r['amount']:.10g}",
                        "" if r["usd"] is None else f"{r['usd']:.2f}", r["kind"], "yes" if r["usd"] is not None else "no"])
    (cdir / "rows_with_detail.json").write_text(json.dumps(kept))
    # summary
    pr = [r for r in kept if r["usd"] is not None]
    usd = sum(r["usd"] for r in pr)
    by_asset = collections.defaultdict(lambda: [0, 0.0, 0.0, 0, ""])
    for r in kept:
        a = by_asset[(r["leg"], r["asset"], r["cid"].split(":")[0])]
        a[0] += 1
        a[1] += r["amount"]
        a[2] += r["usd"] or 0.0
        a[3] += r["usd"] is not None
        a[4] = a[4] or r["src"]
    hour = collections.defaultdict(lambda: [0, 0.0])
    day = collections.defaultdict(lambda: [0, 0.0])
    for r in kept:
        h = hour[iso(r["ts"] - r["ts"] % 3600)]
        h[0] += 1
        h[1] += r["usd"] or 0.0
        d = day[iso(r["ts"] - r["ts"] % 86400)[:10]]
        d[0] += 1
        d[1] += r["usd"] or 0.0
    big = max(pr, key=lambda r: r["usd"]) if pr else None
    leg_tot = collections.defaultdict(lambda: [0, 0.0, 0])
    for r in kept:
        leg_tot[r["leg"]][0] += 1
        leg_tot[r["leg"]][1] += r["usd"] or 0.0
        leg_tot[r["leg"]][2] += r["usd"] is not None
    days_active = len(day)
    gaps = []
    ts_sorted = sorted(r["ts"] for r in kept)
    for leg in leg_tot:
        tl = sorted(r["ts"] for r in kept if r["leg"] == leg)
        gl = sorted(((b - a, iso(a), iso(b)) for a, b in zip([t0] + tl, tl + [t1])), reverse=True)[:5]
        gaps.append({"leg": leg, "longest_gaps": [{"s": g[0], "from": g[1], "to": g[2]} for g in gl]})
    src = collections.Counter(r["src"] or "unpriced" for r in kept)
    s = {"id": eid, "window_utc": [iso(t0), iso(t1)], "legs": legs_info, "skipped_legs": cfg["skipped_legs"],
         "n_rows": len(kept), "n_priced": len(pr), "share_priced_count": len(pr) / len(kept) if kept else None,
         "usd_total_priced": usd, "price_sources": dict(src), "excluded": dict(excluded),
         "match_notes": dict(match_notes),
         "own_contract_recipients_checked": checked, "own_contract_recipients_found": len(own),
         "by_leg": {k: {"n": v[0], "usd": v[1], "n_priced": v[2]} for k, v in leg_tot.items()},
         "by_kind": dict(collections.Counter(r["kind"] for r in kept)),
         "by_asset": sorted([{"leg": k[0], "asset": k[1], "chain": k[2], "n": v[0], "amount": v[1], "usd": v[2],
                              "n_priced": v[3], "price_source_first": v[4],
                              "llama_confidence": None} for k, v in by_asset.items()], key=lambda x: -x["usd"]),
         "largest_release": None if big is None else {"ts": iso(big["ts"]), "leg": big["leg"], "asset": big["asset"],
                                                      "amount": big["amount"], "usd": big["usd"]},
         "busiest_hour_usd": max(hour.items(), key=lambda kv: kv[1][1]) if hour else None,
         "busiest_hour_count": max(hour.items(), key=lambda kv: kv[1][0]) if hour else None,
         "busiest_day_usd": max(day.items(), key=lambda kv: kv[1][1]) if day else None,
         "busiest_day_count": max(day.items(), key=lambda kv: kv[1][0]) if day else None,
         "days_with_release": days_active, "gaps": gaps,
         "daily_usd": {k: v for k, v in sorted(day.items())},
         "first_row": iso(ts_sorted[0]) if ts_sorted else None, "last_row": iso(ts_sorted[-1]) if ts_sorted else None}
    (cdir / "summary.json").write_text(json.dumps(s, indent=1))
    print(json.dumps({k: s[k] for k in ("n_rows", "n_priced", "share_priced_count", "usd_total_priced", "excluded",
                                        "by_leg", "by_kind", "largest_release", "busiest_hour_usd",
                                        "busiest_day_usd", "price_sources")}, indent=1))
    print(json.dumps(legs_info, indent=1))


if __name__ == "__main__":
    main(sys.argv[1])
