"""Legitimate release history before the failure, for E45, E49 and E60 (2026-10-16).

Release points (addresses are read from the research notes, data/incidents/research/batch_*.json, by the role
recorded there; they are written only to raw/<ID>/contracts.json):
  E45  the restaked-ETH token's cross-chain adapter on Ethereum (a LayerZero OFT adapter: lock on send,
       unlock on receive; it escrows the token for its copies on other chains).
  E49  the Gravity Bridge contract on Ethereum (escrow of Ethereum-native tokens; it also holds the full supply
       of the ERC-20s it issued for Cosmos-native assets and releases those the same way).
  E60  the Verus-Ethereum bridge contract on Ethereum (a delegator that runs the logic of its implementation
       contracts in its own context; reserves of ETH, ERC-20 tokens and DAI held in the DAI savings rate).

Window: [t_fail - 150 d, t_fail - 1 s], t_fail = first unauthorized release (results/incidents.csv).

collect (public RPC through incidents/rpc.py; fixed block chunks cached as JSONL under raw/<ID>/):
  - every log the release point emitted;
  - ERC-20/721 Transfer logs with the release point as sender (topic1) and as recipient (topic2);
  - E45, E60: trace_filter with the release point as caller (value-bearing calls = native outflows; for E60
    also the calls the import logic made); E60 also with the release point as callee (which function each
    transaction called, and native inflows);
  - receipts: E60 import transactions (DAI paid out of the savings-rate balance is minted to the recipient by
    the DAI join adapter, so it appears as a Transfer from the zero address, not from the bridge) and every
    transaction with a native outflow; E49 batch transactions (sender = relayer that receives the batch fee);
  - balances of the release point at the window edges (blocks b0 - 1 and b1) for the reconciliation.
build: match outflows to the bridge's release records, classify, price (DefiLlama), write <ID>.csv
  (ts_utc, leg, asset, amount, usd, kind, priced; no addresses or hashes) and raw/<ID>/summary.json.
Run: python -I -B data/legit/collect_legit_E45_E49_E60.py collect|build E45|E49|E60
"""
import bisect
import calendar
import collections
import csv
import datetime
import json
import pathlib
import re
import sys
import time
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT / "incidents"))
from rpc import Rpc, TRANSFER, topic_addr, addr_from_topic, erc20_meta  # noqa: E402
sys.path.insert(0, str(HERE))
import pricing  # noqa: E402
import pricing_points  # noqa: E402
from Crypto.Hash import keccak  # noqa: E402

RESEARCH = ROOT / "data" / "incidents" / "research"
WINDOW_S = 150 * 86400
ETH_URLS = ["https://rpc.mevblocker.io", "https://mainnet.gateway.tenderly.co", "https://eth.drpc.org"]
ZERO = "0x" + "0" * 40
UA = {"Content-Type": "application/json", "User-Agent": "bridge-limits-probe/1.0"}


def k256(s):
    h = keccak.new(digest_bits=256)
    h.update(s.encode())
    return "0x" + h.hexdigest()


def sel(s):
    return k256(s)[:10]


# events
OFT_RECEIVED = k256("OFTReceived(bytes32,uint32,address,uint256)")
OFT_SENT = k256("OFTSent(bytes32,uint32,address,uint256)")
BATCH_EXECUTED = k256("TransactionBatchExecutedEvent(uint256,address,uint256)")
SEND_TO_COSMOS = k256("SendToCosmosEvent(address,address,string,uint256,uint256)")
ERC20_DEPLOYED = k256("ERC20DeployedEvent(string,address,string,string,uint8,uint256)")
VALSET_UPDATED = k256("ValsetUpdatedEvent(uint256,uint256,uint256,address,address[],uint256[])")
LOGIC_CALL = k256("LogicCallEvent(bytes32,uint256,bytes,uint256)")
TRANSFER_SINGLE = k256("TransferSingle(address,address,address,uint256,uint256)")
TRANSFER_BATCH = k256("TransferBatch(address,address,address,uint256[],uint256[])")
SEL_BALANCEOF = sel("balanceOf(address)")
SEL_DAIJOIN_EXIT = sel("exit(address,uint256)")

# LayerZero v2 endpoint ids (source chains of E45 releases); names only where the id is well known
LZ_EID = {30101: "Ethereum", 30102: "BNB Chain", 30106: "Avalanche", 30109: "Polygon", 30110: "Arbitrum",
          30111: "Optimism", 30165: "zkSync Era", 30181: "Mantle", 30183: "Linea", 30184: "Base",
          30214: "Scroll", 30243: "Blast", 30260: "Mode", 30320: "Unichain"}

CFG = {
    "E45": {"batch": "batch_F.json", "release_role": "escrow (rsETH OFT adapter)",
            "leg": "Ethereum adapter (escrow)",
            "failure_roles": ["recipient of the release", "release transaction sender", "downstream recipient"],
            "endpoint_role": "LayerZero EndpointV2",
            "traces_from": True, "traces_to": False},
    "E49": {"batch": "batch_L.json", "release_role": "Gravity bridge contract (escrow)",
            "leg": "Ethereum contract (escrow)",
            "failure_roles": ["recipient address of all four releases", "second holding address",
                              "address that made the four ERC-20 deployment calls",
                              "orchestrator Ethereum key of the validator registered"],
            "traces_from": False, "traces_to": False},
    "E60": {"batch": "batch_M.json", "release_role": "bridge contract (Delegator; reserves)",
            "leg": "Ethereum bridge contract (escrow)",
            "failure_roles": ["initiating address", "recipient address"],
            # an earlier failure of the same bridge (E48, 2026-05-17) lies inside the window
            "prior_failure": {"batch": "batch_F.json", "eid": "E48",
                              "tx_role": "release transaction (submitImports",
                              "roles": ["sender of the release transaction", "recipient address"]},
            "traces_from": True, "traces_to": True},
}
LOG_STEP = 5000
TRACE_STEP = 5000


# ------------------------------------------------------------------------------------------------ utilities
def iso(ts):
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def to_ts(s):
    return calendar.timegm(time.strptime(s.strip(), "%Y-%m-%dT%H:%M:%SZ"))


def raw_dir(eid):
    d = HERE / "raw" / eid
    d.mkdir(parents=True, exist_ok=True)
    return d


def failure_time(eid):
    with open(ROOT / "results" / "incidents.csv", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["id"] == eid:
                return to_ts(r["first_release_utc"])
    raise KeyError(eid)


def research_refs(batch, eid):
    d = json.loads((RESEARCH / batch).read_text(encoding="utf-8"))
    for ev in d["events"]:
        if ev["event_id"] == eid:
            return ev.get("onchain_refs", [])
    raise KeyError(eid)


def is_addr(v):
    return bool(re.fullmatch(r"0x[0-9a-fA-F]{40}", v or ""))


def resolve(eid):
    """Addresses by role from the research notes; saved to raw/<ID>/contracts.json."""
    cfg = CFG[eid]
    refs = research_refs(cfg["batch"], eid)
    rp = [r["value"].lower() for r in refs if r["role"] == cfg["release_role"] and r["chain"] == "Ethereum"]
    assert len(rp) == 1, rp
    out = {"release_point": rp[0], "failure_parties": {}, "failure_txs": {}}
    for r in refs:
        if r["chain"] == "Ethereum" and is_addr(r["value"]) and any(s in r["role"] for s in cfg["failure_roles"]):
            out["failure_parties"][r["value"].lower()] = f"{eid}: {r['role']}"
    if cfg.get("endpoint_role"):
        ep = [r["value"].lower() for r in refs if r["role"] == cfg["endpoint_role"]]
        out["endpoint"] = ep[0]
    pf = cfg.get("prior_failure")
    if pf:
        prefs = research_refs(pf["batch"], pf["eid"])
        for r in prefs:
            if r["chain"] != "Ethereum":
                continue
            if r["role"].startswith(pf["tx_role"]):
                out["failure_txs"][r["value"].lower()] = f"{pf['eid']}: {r['role']}"
            elif is_addr(r["value"]) and any(s in r["role"] for s in pf["roles"]):
                out["failure_parties"][r["value"].lower()] = f"{pf['eid']}: {r['role']}"
    (raw_dir(eid) / "contracts.json").write_text(json.dumps(out, indent=1))
    return out


def eth_rpc():
    r = Rpc("ethereum")
    r.urls = ETH_URLS[:]
    return r


def batch_call(method, params_list, url="https://rpc.mevblocker.io", size=40):
    """JSON-RPC batch; returns results in order (None where an item failed after retries)."""
    out = [None] * len(params_list)
    for i in range(0, len(params_list), size):
        chunk = params_list[i:i + size]
        body = json.dumps([{"jsonrpc": "2.0", "id": i + j, "method": method, "params": p}
                           for j, p in enumerate(chunk)]).encode()
        for attempt in range(6):
            try:
                req = urllib.request.Request(url, data=body, headers=UA)
                with urllib.request.urlopen(req, timeout=120) as r:
                    j = json.loads(r.read().decode())
                if isinstance(j, dict):
                    raise RuntimeError(str(j)[:200])
                bad = [x for x in j if "result" not in x]
                for x in j:
                    if "result" in x:
                        out[x["id"]] = x["result"]
                if bad and attempt < 5:
                    raise RuntimeError(f"{len(bad)} items failed: {str(bad[0])[:150]}")
                break
            except Exception as e:  # noqa: BLE001
                time.sleep(1.5 * (attempt + 1))
                if attempt == 5:
                    print("   batch failed", method, str(e)[:120], flush=True)
    return out


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


def ranged(fn, b0, b1, step, cache, label):
    """Fixed chunk grid (stable cache keys); a chunk that fails is split in four."""
    out = []
    b = b0
    n = 0
    while b <= b1:
        e = min(b + step - 1, b1)
        try:
            out += cache.get(b, e, lambda: fn(b, e))
        except Exception as ex:  # noqa: BLE001
            if step <= 50:
                raise
            print(f"   {label}: split {b}-{e} ({str(ex)[:80]})", flush=True)
            out += ranged(fn, b, e, max(50, step // 4), cache, label)
        b = e + 1
        n += 1
        if n % 40 == 0:
            print(f"   {label}: block {e} / {b1}, rows {len(out)}", flush=True)
    return out


def compact_traces(res):
    keep = []
    for x in res or []:
        a = x.get("action", {})
        if x.get("type") != "call":
            continue
        inp = a.get("input") or ""
        keep.append({"block": x.get("blockNumber"), "tx": x.get("transactionHash"),
                     "ta": x.get("traceAddress"), "ct": a.get("callType"),
                     "from": (a.get("from") or "").lower(), "to": (a.get("to") or "").lower(),
                     "value": a.get("value", "0x0"),
                     "input": inp[:10] if a.get("callType") == "delegatecall" else inp[:202],
                     "error": x.get("error")})
    return keep


def window(eid, rpc):
    cdir = raw_dir(eid)
    t_fail = failure_time(eid)
    t0, t1 = t_fail - WINDOW_S, t_fail - 1
    f = cdir / "blocks.json"
    if f.exists():
        j = json.loads(f.read_text())
    else:
        b0 = rpc.block_at(t0, lo=20000000)
        bf = rpc.block_at(t_fail, lo=b0)
        j = {"t_fail": t_fail, "t0": t0, "t1": t1, "b0": b0, "b1": bf - 1, "bf": bf,
             "ts_b0m1": rpc.block_ts(b0 - 1), "ts_b0": rpc.block_ts(b0), "ts_b1": rpc.block_ts(bf - 1),
             "ts_bf": rpc.block_ts(bf)}
        assert j["ts_b0m1"] < t0 <= j["ts_b0"] and j["ts_b1"] <= t1 and j["ts_bf"] >= t_fail, j
        f.write_text(json.dumps(j, indent=1))
    return j


def headers(blocks, cdir):
    f = cdir / "block_ts.json"
    have = {int(k): v for k, v in json.loads(f.read_text()).items()} if f.exists() else {}
    need = sorted({b for b in blocks if b not in have})
    if need:
        res = batch_call("eth_getBlockByNumber", [[hex(b), False] for b in need])
        for b, r in zip(need, res):
            if r:
                have[b] = int(r["timestamp"], 16)
        f.write_text(json.dumps(have))
    missing = [b for b in blocks if b not in have]
    if missing:
        rpc = eth_rpc()
        for b in missing:
            have[b] = rpc.block_ts(b)
        f.write_text(json.dumps(have))
    return have


def receipts(txs, cdir, name="receipts.jsonl"):
    f = cdir / name
    have = {}
    if f.exists():
        for line in f.read_text().splitlines():
            if line.strip():
                j = json.loads(line)
                have[j["transactionHash"]] = j
    need = sorted({t for t in txs if t not in have})
    for i in range(0, len(need), 200):
        part = need[i:i + 200]
        res = batch_call("eth_getTransactionReceipt", [[t] for t in part], size=20)
        with f.open("a") as fh:
            for t, r in zip(part, res):
                if r is None:
                    r = eth_rpc().receipt(t)
                keep = {"transactionHash": t, "from": (r.get("from") or "").lower(), "to": (r.get("to") or "").lower(),
                        "status": r.get("status"), "blockNumber": r.get("blockNumber"),
                        "logs": [{"address": lg["address"].lower(), "topics": lg["topics"], "data": lg["data"],
                                  "logIndex": lg["logIndex"]} for lg in r.get("logs", [])]}
                fh.write(json.dumps(keep) + "\n")
                have[t] = keep
        print(f"   receipts {min(i + 200, len(need))} / {len(need)}", flush=True)
    return have


def balance_of(rpc, token, holder, block):
    try:
        r = rpc.eth_call(token, SEL_BALANCEOF + holder[2:].rjust(64, "0"), block)
        return int(r, 16) if r and r != "0x" else None
    except Exception:  # noqa: BLE001
        return None


# ------------------------------------------------------------------------------------------------ collect
def collect(eid):
    cfg = CFG[eid]
    cdir = raw_dir(eid)
    rpc = eth_rpc()
    rt = Rpc("ethereum_trace")
    A = resolve(eid)
    rp = A["release_point"]
    W = window(eid, rpc)
    b0, b1 = W["b0"], W["b1"]
    print(f"== {eid}: blocks {b0}-{b1} ({iso(W['ts_b0'])} to {iso(W['ts_b1'])})", flush=True)

    def logs(params):
        return lambda a, b: rpc.call("eth_getLogs", [dict(params, fromBlock=hex(a), toBlock=hex(b))])

    own = ranged(logs({"address": rp}), b0, b1, LOG_STEP, ChunkCache(cdir / "logs_own.jsonl"), "own logs")
    print("own logs", len(own), flush=True)
    xout = ranged(logs({"topics": [TRANSFER, topic_addr(rp)]}), b0, b1, LOG_STEP,
                  ChunkCache(cdir / "transfers_out.jsonl"), "transfers out")
    print("transfers out", len(xout), flush=True)
    xin = ranged(logs({"topics": [TRANSFER, None, topic_addr(rp)]}), b0, b1, LOG_STEP,
                 ChunkCache(cdir / "transfers_in.jsonl"), "transfers in")
    print("transfers in", len(xin), flush=True)
    trf, trt = [], []
    if cfg["traces_from"]:
        trf = ranged(lambda a, b: compact_traces(rt.call("trace_filter", [{"fromBlock": hex(a), "toBlock": hex(b),
                                                                           "fromAddress": [rp]}])),
                     b0, b1, TRACE_STEP, ChunkCache(cdir / "traces_from.jsonl"), "traces from")
        print("traces from", len(trf), flush=True)
    if cfg["traces_to"]:
        trt = ranged(lambda a, b: compact_traces(rt.call("trace_filter", [{"fromBlock": hex(a), "toBlock": hex(b),
                                                                           "toAddress": [rp]}])),
                     b0, b1, TRACE_STEP, ChunkCache(cdir / "traces_to.jsonl"), "traces to")
        print("traces to", len(trt), flush=True)

    # receipts
    need = set()
    for x in trf:
        if x["ct"] == "call" and int(x["value"] or "0x0", 16) > 0:
            need.add(x["tx"])
    if eid == "E60":
        imp = import_selectors(cdir)
        need |= {x["tx"] for x in trt if x["input"][:10] in imp}
    if eid == "E49":
        need |= {lg["transactionHash"] for lg in own if lg["topics"][0] in (BATCH_EXECUTED, LOGIC_CALL, VALSET_UPDATED)}
        need |= {lg["transactionHash"] for lg in xout}
    print("receipts needed", len(need), flush=True)
    receipts(need, cdir)

    # block timestamps for traces (logs carry blockTimestamp on the main endpoint; checked in build)
    blocks = {x["block"] for x in trf + trt}
    blocks |= {int(lg["blockNumber"], 16) for lg in own + xout + xin if not lg.get("blockTimestamp")}
    headers(blocks, cdir)

    # balances at the window edges
    bf = cdir / "balances.json"
    bal = json.loads(bf.read_text()) if bf.exists() else {}
    toks = sorted({lg["address"].lower() for lg in xout + xin})
    for tag, blk in (("start", b0 - 1), ("end", b1)):
        bal.setdefault(tag, {"block": blk, "tokens": {}})
        if "native" not in bal[tag]:
            bal[tag]["native"] = rpc.balance(rp, blk)
        for tk in toks:
            if tk not in bal[tag]["tokens"]:
                v = balance_of(rpc, tk, rp, blk)
                bal[tag]["tokens"][tk] = None if v is None else str(v)
    bf.write_text(json.dumps(bal, indent=1))

    # token metadata
    mf = cdir / "token_meta.json"
    meta = {k: tuple(v) for k, v in json.loads(mf.read_text()).items()} if mf.exists() else {}
    for tk in toks:
        if tk not in meta:
            erc20_meta(rpc, tk, meta)
    mf.write_text(json.dumps(meta, indent=1))
    print(eid, "collected", flush=True)


# ------------------------------------------------------------------------------------------------ E60 helpers
def abi_type(inp):
    t = inp["type"]
    if t.startswith("tuple"):
        return "(" + ",".join(abi_type(c) for c in inp["components"]) + ")" + t[5:]
    return t


def delegator_selectors(cdir):
    j = json.loads((cdir / "src" / "delegator.json").read_text())
    out = {}
    for x in j.get("abi") or []:
        if x["type"] == "function":
            out[sel(x["name"] + "(" + ",".join(abi_type(i) for i in x["inputs"]) + ")")] = x["name"]
    return out


def import_selectors(cdir):
    return {s for s, n in delegator_selectors(cdir).items() if n == "submitImports"}


def verus_usage_contract(cdir):
    j = json.loads((cdir / "src" / "si_v3.json").read_text())
    for s in j.get("additional_sources") or []:
        if s["file_path"].endswith("VerusConstants.sol"):
            m = re.search(r"VERUS_USAGE_CONTRACT\s*=\s*address\((0x[0-9a-fA-F]{40})\)", s["source_code"])
            if m:
                return m.group(1).lower()
    return None


def dai_address(cdir):
    """DAI token of the import logic: constructor argument DaiERC20Address of the verified TokenManager."""
    out = set()
    for tag in ("tm_v2", "tm_v3"):
        j = json.loads((cdir / "src" / f"{tag}.json").read_text())
        for v, spec in j.get("decoded_constructor_args") or []:
            if spec.get("name") == "DaiERC20Address":
                out.add(v.lower())
    assert len(out) == 1, out
    return out.pop()


def token_fee_recipients(rpc, tokens, block, cdir):
    """Fee-on-transfer tokens (PAXG style) expose feeRecipient(); their fee transfers follow each transfer."""
    f = cdir / "token_fee_recipients.json"
    have = json.loads(f.read_text()) if f.exists() else {}
    s = sel("feeRecipient()")
    for tk in sorted(tokens):
        if tk in have:
            continue
        try:
            r = rpc.call("eth_call", [{"to": tk, "data": s}, hex(block)], retries=2)
            have[tk] = ("0x" + r[-40:]).lower() if r and len(r) >= 66 and int(r, 16) != 0 else None
        except Exception:  # noqa: BLE001
            have[tk] = None
    f.write_text(json.dumps(have, indent=1))
    return have


def notary_mains(rpc, rp, block, cdir):
    f = cdir / "notaries.json"
    if f.exists():
        return json.loads(f.read_text())
    out = []
    s_not = sel("notaries(uint256)")
    s_map = sel("notaryAddressMapping(address)")
    for i in range(64):
        try:
            r = rpc.eth_call(rp, s_not + hex(i)[2:].rjust(64, "0"), block)
        except Exception:  # noqa: BLE001
            break
        if not r or r == "0x":
            break
        n = "0x" + r[-40:]
        m = rpc.eth_call(rp, s_map + n[2:].rjust(64, "0"), block)
        w = [m[2 + 64 * k: 2 + 64 * (k + 1)] for k in range(3)]
        out.append({"notary": n, "main": "0x" + w[0][-40:], "revoke": "0x" + w[1][-40:], "state": int(w[2], 16)})
    f.write_text(json.dumps(out, indent=1))
    return out


# ------------------------------------------------------------------------------------------------ build
class Prices:
    """DefiLlama: hourly chart (2 h), then batchHistorical at the middle of the release hour (2 h), then the daily
    chart (36 h); otherwise unpriced."""

    def __init__(self, cdir, t0, t1):
        self.pdir = cdir / "prices"
        self.pdir.mkdir(parents=True, exist_ok=True)
        self.t0, self.t1 = t0, t1
        self.h, self.d = {}, {}

    def series(self, cid):
        if cid not in self.h:
            self.h[cid] = [(p[0], p[1]) for p in pricing.chart(cid, self.t0, self.t1, "1h", self.pdir, search_width=1800)]
        return self.h[cid]

    def daily(self, cid):
        if cid not in self.d:
            self.d[cid] = [(p[0], p[1]) for p in pricing.chart(cid, self.t0, self.t1, "1d", self.pdir, search_width=43200)]
        return self.d[cid]

    @staticmethod
    def near(series, ts, tol):
        if not series:
            return None
        i = bisect.bisect_left(series, (ts, -1e300))
        best = None
        for j in (i - 1, i):
            if 0 <= j < len(series):
                dd = abs(series[j][0] - ts)
                if dd <= tol and (best is None or dd < best[0]):
                    best = (dd, series[j][1])
        return None if best is None else best[1]

    def price_rows(self, rows):
        for r in rows:
            r["price"], r["src"] = None, ""
        todo = [r for r in rows if r.get("cid")]
        for r in todo:
            p = self.near(self.series(r["cid"]), r["ts"], 2 * 3600)
            if p is not None:
                r["price"], r["src"] = p, "defillama chart 1h"
        miss = [r for r in todo if r["price"] is None]
        if miss:
            table = pricing_points.lookup([(r["cid"], r["ts"]) for r in miss], self.pdir)
            for r in miss:
                p = pricing_points.price(table, r["cid"], r["ts"])
                if p is not None:
                    r["price"], r["src"] = p, "defillama batchHistorical 2h"
        miss = [r for r in todo if r["price"] is None]
        for r in miss:
            p = self.near(self.daily(r["cid"]), r["ts"], 36 * 3600)
            if p is not None:
                r["price"], r["src"] = p, "defillama chart 1d"
        for r in rows:
            r["usd"] = r["amount"] * r["price"] if r["price"] is not None else None


def load_chunks(cdir, name):
    c = ChunkCache(cdir / name)
    out = []
    for k in sorted(c.done):
        out += c.done[k]
    return out


def word(data, i):
    return data[2 + 64 * i: 2 + 64 * (i + 1)]


def amt(lg):
    """Amount of an ERC-20 Transfer log (0 for empty data or ERC-721 logs, whose id is a topic)."""
    d = lg.get("data") or "0x"
    if len(lg.get("topics", [])) != 3 or d in ("0x", ""):
        return 0
    return int(d[:66], 16)


def log_ts(lg, bts):
    if lg.get("blockTimestamp"):
        return int(lg["blockTimestamp"], 16)
    return bts[int(lg["blockNumber"], 16)]


def ancestors_ok(tr, frames):
    """False if the trace or any recorded ancestor frame in the same transaction has an error."""
    if tr.get("error"):
        return False
    ta = tr["ta"] or []
    for k in range(len(ta)):
        f = frames.get((tr["tx"], tuple(ta[:k])))
        if f is not None and f.get("error"):
            return False
    return True


def build(eid):
    cfg = CFG[eid]
    cdir = raw_dir(eid)
    rpc = eth_rpc()
    A = json.loads((cdir / "contracts.json").read_text())
    rp = A["release_point"]
    W = json.loads((cdir / "blocks.json").read_text())
    t_fail, t0, t1, b0, b1 = W["t_fail"], W["t0"], W["t1"], W["b0"], W["b1"]
    fparty = A["failure_parties"]
    ftx = A["failure_txs"]
    own = load_chunks(cdir, "logs_own.jsonl")
    xout = load_chunks(cdir, "transfers_out.jsonl")
    xin = load_chunks(cdir, "transfers_in.jsonl")
    trf = load_chunks(cdir, "traces_from.jsonl") if cfg["traces_from"] else []
    trt = load_chunks(cdir, "traces_to.jsonl") if cfg["traces_to"] else []
    bts = {int(k): v for k, v in json.loads((cdir / "block_ts.json").read_text()).items()} \
        if (cdir / "block_ts.json").exists() else {}
    rc = receipts(set(), cdir)
    meta = {k: tuple(v) for k, v in json.loads((cdir / "token_meta.json").read_text()).items()}
    bal = json.loads((cdir / "balances.json").read_text())
    excluded = collections.Counter()
    excluded_detail = collections.defaultdict(lambda: collections.defaultdict(lambda: [0, 0.0]))
    notes = {}
    rows = []
    side_rows = collections.defaultdict(list)   # excluded outflows valued for the README only
    leg = cfg["leg"]

    def tok_meta(tk):
        if tk not in meta:
            erc20_meta(rpc, tk, meta)
        return meta[tk]

    def mkrow(ts, kind, tok, raw, to, tx, path, nft=False):
        if tok == "native":
            sym, dec, cid = "ETH", 18, "coingecko:ethereum"
        else:
            sym, dec = tok_meta(tok)
            cid = None if nft else f"ethereum:{tok}"
        return {"ts": ts, "kind": kind, "token": tok, "asset": (sym or "?").strip() + (" (ERC-721)" if nft else ""),
                "cid": cid, "amount": 1 if nft else raw / 10 ** dec, "raw": str(raw), "to": to, "tx": tx,
                "path": path, "nft": nft}

    def add(ts, kind, tok, raw, to, tx, path, nft=False):
        if to == ZERO:
            exclude("to_zero_address (burn)", tok, raw, nft)
            return
        rows.append(mkrow(ts, kind, tok, raw, to, tx, path, nft))

    def side(name, ts, kind, tok, raw, to, tx, nft=False):
        """An excluded outflow, valued for the README only."""
        side_rows[name].append(mkrow(ts, kind, tok, raw, to, tx, name, nft))

    def exclude(reason, tok, raw, nft=False):
        excluded[reason] += 1
        if tok == "native":
            sym, dec = "ETH", 18
        else:
            sym, dec = tok_meta(tok)
        e = excluded_detail[reason][(sym or "?").strip()]
        e[0] += 1
        e[1] += 0 if nft else raw / 10 ** dec

    xfers_out = []
    seen = set()
    for lg in xout:
        k = (lg["transactionHash"], lg["logIndex"])
        if k in seen or lg.get("removed"):
            continue
        seen.add(k)
        xfers_out.append(lg)

    # ======================================================================== E45: OFT adapter
    if eid == "E45":
        ep = A["endpoint"]
        recv = collections.defaultdict(list)
        sent = []
        topic_counts = collections.Counter(lg["topics"][0] for lg in own if lg["topics"])
        for lg in own:
            t = lg["topics"][0] if lg["topics"] else None
            if t == OFT_RECEIVED:
                recv[lg["transactionHash"]].append({"guid": lg["topics"][1], "to": addr_from_topic(lg["topics"][2]).lower(),
                                                    "eid": int(word(lg["data"], 0), 16), "amount": int(word(lg["data"], 1), 16),
                                                    "ts": log_ts(lg, bts), "li": int(lg["logIndex"], 16), "matched": False})
            elif t == OFT_SENT:
                sent.append({"eid": int(word(lg["data"], 0), 16), "amount": int(word(lg["data"], 1), 16),
                             "ts": log_ts(lg, bts)})
        n_events = sum(len(v) for v in recv.values())
        src_eid = collections.Counter()
        for lg in sorted(xfers_out, key=lambda x: (int(x["blockNumber"], 16), int(x["logIndex"], 16))):
            if len(lg["topics"]) != 3:
                exclude("nft_or_nonstandard_transfer", lg["address"].lower(), 0, nft=True)
                continue
            tok = lg["address"].lower()
            to = addr_from_topic(lg["topics"][2]).lower()
            raw = amt(lg)
            ts = log_ts(lg, bts)
            m = [e for e in recv.get(lg["transactionHash"], []) if not e["matched"] and e["to"] == to and e["amount"] == raw]
            if not m:
                exclude("erc20_out_without_release_event", tok, raw)
                continue
            m[0]["matched"] = True
            if to in fparty:
                exclude("to_failure_party", tok, raw)
                continue
            if to == rp:
                exclude("to_release_point_itself", tok, raw)
                continue
            src_eid[m[0]["eid"]] += 1
            add(ts, "erc20", tok, raw, to, lg["transactionHash"], f"OFTReceived from eid {m[0]['eid']}")
        unmatched_ev = [e for v in recv.values() for e in v if not e["matched"]]
        # native outflows: value-bearing calls by the adapter
        frames = {(x["tx"], tuple(x["ta"] or [])): x for x in trf}
        nat = collections.Counter()
        for x in trf:
            v = int(x["value"] or "0x0", 16)
            if x["ct"] != "call" or v == 0:
                continue
            if not ancestors_ok(x, frames):
                nat["error_frame"] += 1
                continue
            r = rc.get(x["tx"])
            if r is not None and r["status"] != "0x1":
                nat["reverted_tx"] += 1
                continue
            if x["to"] == ep:
                nat["to_messaging_endpoint"] += 1
                exclude("native_to_messaging_endpoint (fee forwarded on outbound sends)", "native", v)
                continue
            nat["other"] += 1
            if x["to"] in fparty:
                exclude("to_failure_party", "native", v)
                continue
            add(bts[x["block"]], "native", "native", v, x["to"], x["tx"], "native call")
        rsETH = sorted({lg["address"].lower() for lg in xfers_out}, key=lambda t: -sum(1 for lg in xfers_out if lg["address"].lower() == t))
        lzf = cdir / "public" / "lzscan_check.json"
        names = dict(LZ_EID)
        if lzf.exists():   # chain names as LayerZero Scan labels the endpoint ids
            names.update({int(k): v for k, v in json.loads(lzf.read_text()).get("eid_chain", {}).items()})
        LZ_EID.update(names)
        notes.update({"own_log_topics": {("OFTReceived" if k == OFT_RECEIVED else "OFTSent" if k == OFT_SENT else k[:12]): v
                                         for k, v in topic_counts.items()},
                      "n_release_events": n_events, "n_unmatched_release_events": len(unmatched_ev),
                      "unmatched_release_events": [{"ts_utc": iso(e["ts"]), "eid": e["eid"], "amount_raw": str(e["amount"])}
                                                   for e in unmatched_ev][:20],
                      "n_transfer_logs_out": len(xfers_out), "native_calls": dict(nat),
                      "tokens_out": [tok_meta(t)[0] for t in rsETH],
                      "releases_by_source_eid": {f"{k} ({LZ_EID.get(k, 'unnamed')})": v for k, v in src_eid.most_common()},
                      "outbound_sends": {"n": len(sent), "by_dst_eid": {f"{k} ({LZ_EID.get(k, 'unnamed')})": v
                                                                       for k, v in collections.Counter(s["eid"] for s in sent).most_common()}}})

    # ======================================================================== E49: Gravity contract
    if eid == "E49":
        ev_by_tx = collections.defaultdict(list)
        topic_counts = collections.Counter()
        validators = set()
        n_deploy = []
        for lg in own:
            t = lg["topics"][0] if lg["topics"] else None
            name = {BATCH_EXECUTED: "batch", SEND_TO_COSMOS: "deposit", ERC20_DEPLOYED: "deploy",
                    VALSET_UPDATED: "valset", LOGIC_CALL: "logic"}.get(t, "other")
            topic_counts[name] += 1
            e = {"name": name, "li": int(lg["logIndex"], 16), "ts": log_ts(lg, bts)}
            if name == "batch":
                e["token"] = addr_from_topic(lg["topics"][2]).lower()
                e["nonce"] = int(lg["topics"][1], 16)
            if name == "valset":
                d = lg["data"]
                off = int(word(d, 3), 16) // 32
                n = int(word(d, off), 16)
                validators |= {("0x" + word(d, off + 1 + i)[-40:]).lower() for i in range(n)}
                e["reward_token"] = ("0x" + word(d, 2)[-40:]).lower()
                e["reward_amount"] = int(word(d, 1), 16)
            if name == "deploy":
                n_deploy.append(iso(e["ts"]))
            ev_by_tx[lg["transactionHash"]].append(e)
        for v in ev_by_tx.values():
            v.sort(key=lambda e: e["li"])
        # group transfers by the next Gravity event in the same transaction
        groups = collections.defaultdict(list)
        lone = []
        for lg in xfers_out:
            li = int(lg["logIndex"], 16)
            nxt = [e for e in ev_by_tx.get(lg["transactionHash"], []) if e["li"] > li]
            if not nxt:
                lone.append(lg)
                continue
            groups[(lg["transactionHash"], nxt[0]["li"])].append(lg)
        fee_check = collections.Counter()
        fee_rcpt_validator = 0
        batch_sizes = []
        token_fees = collections.Counter()
        fee_rcp = token_fee_recipients(rpc, {e["token"] for v in ev_by_tx.values() for e in v if e["name"] == "batch"},
                                       b1, cdir)
        for (tx, eli), lgs in groups.items():
            ev = [e for e in ev_by_tx[tx] if e["li"] == eli][0]
            lgs.sort(key=lambda x: int(x["logIndex"], 16))
            r = rc.get(tx)
            if ev["name"] == "batch":
                same = [x for x in lgs if x["address"].lower() == ev["token"]]
                other = [x for x in lgs if x["address"].lower() != ev["token"]]
                for x in other:
                    exclude("transfer_of_other_token_in_batch_tx", x["address"].lower(), amt(x))
                if not same:
                    continue
                # a fee-on-transfer token (PAXG) emits its own fee transfer after each transfer: fold it into the
                # preceding transfer, so each item carries the gross amount that left escrow (as in E14)
                frc = fee_rcp.get(ev["token"])
                core = []
                for x in same:
                    to_x = addr_from_topic(x["topics"][2]).lower()
                    if frc and to_x == frc and core:
                        core[-1]["gross"] += amt(x)
                        token_fees[tok_meta(ev["token"])[0]] += 1
                    else:
                        core.append({"lg": x, "to": to_x, "gross": amt(x)})
                fee = core[-1]["lg"]
                fee_to = core[-1]["to"]
                fee_raw = core[-1]["gross"]
                if r is not None and fee_to in (r["from"], r["to"]):
                    fee_check["fee_to_tx_sender_or_called_contract"] += 1
                else:
                    fee_check["fee_recipient_not_sender"] += 1
                if fee_to in validators:
                    fee_rcpt_validator += 1
                if fee_raw == 0:
                    excluded["zero_amount_batch_fee"] += 1
                elif fee_to in fparty:
                    exclude("to_failure_party", fee["address"].lower(), fee_raw)
                else:
                    add(log_ts(fee, bts), "erc20", fee["address"].lower(), fee_raw, fee_to, tx, "batch fee to relayer")
                batch_sizes.append(len(core) - 1)
                for item in core[:-1]:
                    x = item["lg"]
                    if len(x["topics"]) != 3:
                        exclude("nft_or_nonstandard_transfer", x["address"].lower(), 0, nft=True)
                        continue
                    to = item["to"]
                    raw = item["gross"]
                    tok = x["address"].lower()
                    if raw == 0:
                        excluded["zero_amount"] += 1
                        continue
                    if to in fparty:
                        exclude("to_failure_party", tok, raw)
                        continue
                    if to == rp:
                        exclude("to_release_point_itself", tok, raw)
                        continue
                    if to in validators:
                        notes.setdefault("payouts_to_validator_keys", 0)
                        notes["payouts_to_validator_keys"] += 1
                    add(log_ts(x, bts), "erc20", tok, raw, to, tx, f"batch {ev['nonce']}")
            elif ev["name"] == "valset":
                for x in lgs:
                    to = addr_from_topic(x["topics"][2]).lower()
                    if amt(x) == 0:
                        excluded["zero_amount_valset_reward"] += 1
                    elif to in fparty:
                        exclude("to_failure_party", x["address"].lower(), amt(x))
                    else:
                        add(log_ts(x, bts), "erc20", x["address"].lower(), amt(x), to, tx, "valset reward to relayer")
            elif ev["name"] == "logic":
                for x in lgs:
                    to = addr_from_topic(x["topics"][2]).lower()
                    raw = amt(x)
                    if raw == 0:
                        excluded["zero_amount"] += 1
                    elif to in fparty:
                        exclude("to_failure_party", x["address"].lower(), raw)
                    elif r is not None and to in (r["from"], r["to"]):
                        add(log_ts(x, bts), "erc20", x["address"].lower(), raw, to, tx, "logic call fee to relayer")
                    else:
                        add(log_ts(x, bts), "erc20", x["address"].lower(), raw, to, tx, "logic call")
            else:
                for x in lgs:
                    exclude(f"transfer_before_{ev['name']}_event", x["address"].lower(), amt(x))
        for x in lone:
            exclude("erc20_out_without_release_event", x["address"].lower(), amt(x))
        # completeness: the contract numbers every event it emits with a consecutive event nonce
        nonce_word = {"batch": 0, "deposit": 2, "deploy": 4, "valset": 0, "logic": 3}
        enon = sorted(int(word(lg["data"], nonce_word[nm]), 16) for lg in own
                      for nm in [{BATCH_EXECUTED: "batch", SEND_TO_COSMOS: "deposit", ERC20_DEPLOYED: "deploy",
                                  VALSET_UPDATED: "valset", LOGIC_CALL: "logic"}.get(lg["topics"][0] if lg["topics"] else None)]
                      if nm)
        notes["event_nonce_check"] = {"first": enon[0], "last": enon[-1], "n": len(enon),
                                      "contiguous": enon == list(range(enon[0], enon[-1] + 1)),
                                      "missing": sorted(set(range(enon[0], enon[-1] + 1)) - set(enon))[:20]} if enon else None
        bn = sorted(e["nonce"] for v in ev_by_tx.values() for e in v if e["name"] == "batch")
        notes["batch_nonce_range"] = [bn[0], bn[-1]] if bn else None
        # Cosmos-native tokens (the contract holds nearly the full uint256 supply)
        cosmos = {tk for tk, v in bal["end"]["tokens"].items() if v is not None and int(v) > 2 ** 255}
        # As in E14/E15, tokens the bridge issues for assets native to the other chain are issued, not released
        # from escrow: kept out of the series and reported (count and units) in the exclusions.
        kept = []
        cos_rel = sorted({tok_meta(r_["token"])[0] for r_ in rows if r_["token"] in cosmos})
        for r_ in rows:
            if r_["token"] in cosmos:
                exclude(f"issued token of a Cosmos-native asset ({path_of(r_)})", r_["token"], int(r_["raw"]))
                side_rows["issued tokens of Cosmos-native assets (excluded)"].append(r_)
            else:
                kept.append(r_)
        rows[:] = kept
        bsz = sorted(batch_sizes)
        notes.update({"own_log_counts": dict(topic_counts), "n_batches": topic_counts["batch"],
                      "n_validator_keys_seen": len(validators), "fee_check": dict(fee_check),
                      "fee_transfers_to_validator_keys": fee_rcpt_validator,
                      "token_fee_transfers_folded": dict(token_fees),
                      "fee_on_transfer_tokens": sorted(tok_meta(t)[0] for t, v in fee_rcp.items() if v),
                      "batch_size_quantiles": {q: bsz[min(len(bsz) - 1, int(q * len(bsz)))] for q in (0.5, 0.9, 0.99, 1.0)} if bsz else None,
                      "erc20_deployments_in_window": n_deploy,
                      "cosmos_native_tokens_released": cos_rel,
                      "n_transfer_logs_out": len(xfers_out)})
        A["cosmos_tokens"] = sorted(cosmos)

    # ======================================================================== E60: Verus bridge contract
    if eid == "E60":
        sels = delegator_selectors(cdir)
        usage = verus_usage_contract(cdir)
        dai = dai_address(cdir)
        nots = notary_mains(rpc, rp, b1, cdir)
        mains = {n["main"].lower() for n in nots} | {n["revoke"].lower() for n in nots}
        impls = set()
        impl_f = cdir / "implementations_probe.json"
        if impl_f.exists():
            for v in json.loads(impl_f.read_text()).values():
                impls |= {a.lower() for a in v["contracts"]}
        impls |= {x["to"] for x in trf if x["ct"] == "delegatecall"}
        tx_fn = collections.defaultdict(list)
        for x in trt:
            tx_fn[x["tx"]].append((len(x["ta"] or []), sels.get(x["input"][:10], x["input"][:10] or "plain transfer"),
                                   x.get("error")))
        def tx_class(tx):
            fns = [f for _, f, err in sorted(tx_fn.get(tx, [])) if not err]
            if tx in ftx:
                return "failure_" + ftx[tx].split(":")[0]
            for f in ("submitImports", "claimfees", "sendfees", "claimRefund", "upgradeContracts", "replacecontract"):
                if f in fns:
                    return f
            return fns[0] if fns else "unknown"
        fn_counts = collections.Counter()
        for tx in tx_fn:
            fn_counts[tx_class(tx)] += 1
        frames = {(x["tx"], tuple(x["ta"] or [])): x for x in trf}
        frames.update({(x["tx"], tuple(x["ta"] or [])): x for x in trt})
        cls_out = collections.defaultdict(collections.Counter)
        # native
        for x in trf:
            v = int(x["value"] or "0x0", 16)
            if x["ct"] != "call" or v == 0:
                continue
            if not ancestors_ok(x, frames):
                excluded["native_call_in_failed_frame"] += 1
                continue
            r = rc.get(x["tx"])
            if r is None or r["status"] != "0x1":
                excluded["native_call_in_reverted_tx"] += 1
                continue
            c = tx_class(x["tx"])
            cls_out[c]["native"] += 1
            ts = bts[x["block"]]
            if c.startswith("failure_"):
                exclude(f"{c} (earlier unauthorized release inside the window)", "native", v)
                side(f"{c} (earlier unauthorized release inside the window)", ts, "native", "native", v, x["to"], x["tx"])
            elif x["to"] in fparty:
                exclude("to_failure_party", "native", v)
                side("to_failure_party", ts, "native", "native", v, x["to"], x["tx"])
            elif x["to"] == rp or x["to"] in impls:
                exclude("to_bridge_contracts", "native", v)
            elif c == "submitImports":
                if x["to"] == usage:
                    add(ts, "native", "native", v, x["to"], x["tx"], "import protocol fee share")
                else:
                    if x["to"] in mains:
                        notes.setdefault("import_payouts_to_notary_addresses", 0)
                        notes["import_payouts_to_notary_addresses"] += 1
                    add(ts, "native", "native", v, x["to"], x["tx"], "import")
            elif c in ("claimfees", "sendfees"):
                add(ts, "native", "native", v, x["to"], x["tx"], f"fee claim ({c})")
            else:
                exclude(f"native_out_in_{c}_tx", "native", v)
                side(f"native_out_in_{c}_tx", ts, "native", "native", v, x["to"], x["tx"])
        # ERC-20 / ERC-721 transfers from the bridge
        for lg in xfers_out:
            tok = lg["address"].lower()
            c = tx_class(lg["transactionHash"])
            nft = len(lg["topics"]) == 4
            to = addr_from_topic(lg["topics"][2]).lower()
            raw = 0 if nft else (amt(lg))
            cls_out[c]["erc721" if nft else "erc20"] += 1
            ts = log_ts(lg, bts)
            if c.startswith("failure_"):
                exclude(f"{c} (earlier unauthorized release inside the window)", tok, raw, nft)
                side(f"{c} (earlier unauthorized release inside the window)", ts, "erc20", tok, raw, to,
                     lg["transactionHash"], nft)
            elif to in fparty:
                exclude("to_failure_party", tok, raw, nft)
                side("to_failure_party", ts, "erc20", tok, raw, to, lg["transactionHash"], nft)
            elif c == "submitImports":
                if to == rp or to in impls:
                    exclude("to_bridge_contracts", tok, raw, nft)
                elif raw == 0 and not nft:
                    excluded["zero_amount"] += 1
                elif to == ZERO and not nft:
                    # wrapper ("proxy") token: its transfer() burns the bridge's units and pays the linked token,
                    # held by the wrapper contract, to the recipient; the release is that payment
                    r = rc.get(lg["transactionHash"]) or {"logs": []}
                    li = int(lg["logIndex"], 16)
                    paid = sorted((x for x in r["logs"] if x["topics"] and x["topics"][0] == TRANSFER
                                   and len(x["topics"]) == 3 and addr_from_topic(x["topics"][1]).lower() == tok
                                   and int(x["logIndex"], 16) > li), key=lambda x: int(x["logIndex"], 16))
                    if paid:
                        p0 = paid[0]
                        to2 = addr_from_topic(p0["topics"][2]).lower()
                        if to2 in fparty:
                            exclude("to_failure_party", p0["address"], amt(p0))
                        else:
                            cls_out[c]["wrapper_payout"] += 1
                            add(ts, "erc20", p0["address"].lower(), amt(p0), to2, lg["transactionHash"],
                                "import (linked token paid by a wrapper token)")
                    else:
                        exclude("to_zero_address (burn)", tok, raw)
                else:
                    add(ts, "erc20", tok, raw, to, lg["transactionHash"], "import", nft=nft)
            else:
                exclude(f"token_out_in_{c}_tx", tok, raw, nft)
                if to != ZERO:
                    side(f"token_out_in_{c}_tx", ts, "erc20", tok, raw, to, lg["transactionHash"], nft)
        # DAI from the savings-rate balance and mints, from the import receipts
        imp_sel = import_selectors(cdir)
        imp_txs = {x["tx"] for x in trt if x["input"][:10] in imp_sel}
        exits = collections.defaultdict(list)
        for x in trf:
            if x["ct"] == "call" and x["input"][:10] == SEL_DAIJOIN_EXIT and not x.get("error"):
                usr = "0x" + x["input"][10 + 24:10 + 64]
                wad = int(x["input"][74:138], 16)
                exits[x["tx"]].append({"usr": usr.lower(), "wad": wad, "used": False})
        mints = collections.Counter()
        for tx in sorted(imp_txs):
            r = rc.get(tx)
            if r is None or r["status"] != "0x1":
                continue
            c = tx_class(tx)
            for lg in r["logs"]:
                t = lg["topics"]
                if not t:
                    continue
                if t[0] == TRANSFER and len(t) >= 3 and addr_from_topic(t[1]).lower() == ZERO:
                    tok = lg["address"]
                    to = addr_from_topic(t[2]).lower()
                    raw = int(lg["data"], 16) if len(t) == 3 and lg["data"] not in ("0x", "") else 0
                    if tok == dai:
                        m = [e for e in exits.get(tx, []) if not e["used"] and e["usr"] == to and e["wad"] == raw]
                        if m:
                            m[0]["used"] = True
                        else:
                            excluded["dai_mint_without_bridge_exit_call"] += 1
                            continue
                        ts = bts.get(int(r["blockNumber"], 16)) or rpc.block_ts(int(r["blockNumber"], 16))
                        bts[int(r["blockNumber"], 16)] = ts
                        if c.startswith("failure_"):
                            exclude(f"{c} (earlier unauthorized release inside the window)", tok, raw)
                            side(f"{c} (earlier unauthorized release inside the window)", ts, "erc20", tok, raw, to, tx)
                        elif to in fparty:
                            exclude("to_failure_party", tok, raw)
                            side("to_failure_party", ts, "erc20", tok, raw, to, tx)
                        else:
                            cls_out[c]["dai_exit"] += 1
                            add(ts, "erc20", tok, raw, to, tx, "import (DAI from the savings-rate balance)")
                    else:
                        sym = tok_meta(tok)[0]
                        mints[sym + (" (ERC-721)" if len(t) == 4 else "")] += 1
                elif t[0] in (TRANSFER_SINGLE, TRANSFER_BATCH) and addr_from_topic(t[2]).lower() == rp:
                    excluded["erc1155_out"] += 1
        # DAI exits outside imports (burnFees reimburses its caller in DAI from the savings-rate balance)
        other = {tx for tx in exits if tx not in imp_txs}
        if other:
            rc.update(receipts(other, cdir))
        for tx in sorted(other):
            r = rc.get(tx)
            if r is None or r["status"] != "0x1":
                continue
            c = tx_class(tx)
            for lg in r["logs"]:
                t = lg["topics"]
                if not (t and t[0] == TRANSFER and len(t) == 3 and lg["address"] == dai
                        and addr_from_topic(t[1]).lower() == ZERO):
                    continue
                to = addr_from_topic(t[2]).lower()
                raw = amt(lg)
                m = [e for e in exits[tx] if not e["used"] and e["usr"] == to and e["wad"] == raw]
                if not m:
                    continue
                m[0]["used"] = True
                b = int(r["blockNumber"], 16)
                ts = bts.get(b) or rpc.block_ts(b)
                bts[b] = ts
                cls_out[c]["dai_exit"] += 1
                if c.startswith("failure_") or to in fparty:
                    exclude("to_failure_party", dai, raw)
                elif c == "burnFees":
                    add(ts, "erc20", dai, raw, to, tx, "fee claim (burnFees, DAI reimbursement)")
                else:
                    exclude(f"dai_exit_in_{c}_tx", dai, raw)
                    side(f"dai_exit_in_{c}_tx", ts, "erc20", dai, raw, to, tx)
        notes.update({"calls_into_contract_by_function": dict(fn_counts),
                      "outflows_by_transaction_function": {k: dict(v) for k, v in cls_out.items()},
                      "import_transactions": len(imp_txs),
                      "issued_token_mints_in_imports (not escrow releases)": dict(mints),
                      "dai_exit_calls": sum(len(v) for v in exits.values()),
                      "dai_exit_calls_unmatched": sum(1 for v in exits.values() for e in v if not e["used"]),
                      "n_notaries": len(nots), "n_transfer_logs_out": len(xfers_out),
                      "n_implementation_contracts_seen": len(impls)})
        # native reconciliation: balance change = inflows - outflows (all value-bearing calls, any class)
        nin = sum(int(x["value"] or "0x0", 16) for x in trt
                  if x["ct"] == "call" and int(x["value"] or "0x0", 16) > 0 and ancestors_ok(x, frames)
                  and (rc.get(x["tx"]) is None or rc[x["tx"]]["status"] == "0x1"))
        nout = sum(int(x["value"] or "0x0", 16) for x in trf
                   if x["ct"] == "call" and int(x["value"] or "0x0", 16) > 0 and ancestors_ok(x, frames)
                   and rc.get(x["tx"]) is not None and rc[x["tx"]]["status"] == "0x1")
        notes["native_reconciliation_eth"] = {"start": bal["start"]["native"] / 1e18, "end": bal["end"]["native"] / 1e18,
                                              "inflows": nin / 1e18, "outflows": nout / 1e18,
                                              "residual": (bal["end"]["native"] - bal["start"]["native"] - nin + nout) / 1e18}
        (cdir / "block_ts.json").write_text(json.dumps(bts))

    # ======================================================================== token reconciliation (all IDs)
    recon = {}
    flows = collections.defaultdict(lambda: [0, 0])
    for lg in xfers_out:
        if len(lg["topics"]) == 3:
            flows[lg["address"].lower()][1] += amt(lg)
    seen_in = set()
    for lg in xin:
        k = (lg["transactionHash"], lg["logIndex"])
        if k in seen_in or len(lg["topics"]) != 3:
            continue
        seen_in.add(k)
        flows[lg["address"].lower()][0] += amt(lg)
    for tk, (fi, fo) in flows.items():
        s, e = bal["start"]["tokens"].get(tk), bal["end"]["tokens"].get(tk)
        sym, dec = tok_meta(tk)
        if s is None or e is None:
            recon[sym] = {"status": "balance unreadable"}
            continue
        res = int(e) - int(s) - fi + fo
        recon.setdefault(sym, {"n_tokens": 0, "residual_units": 0.0, "out_units": 0.0, "exact_tokens": 0})
        recon[sym]["n_tokens"] += 1
        recon[sym]["residual_units"] += res / 10 ** dec
        recon[sym]["out_units"] += fo / 10 ** dec
        recon[sym]["exact_tokens"] += res == 0
    notes["token_reconciliation"] = recon

    # ======================================================================== price, write, summarize
    for r in rows:
        assert t0 <= r["ts"] <= t1, (r["ts"], t0, t1)
    rows.sort(key=lambda r: (r["ts"], r["tx"]))
    P = Prices(cdir, t0, t1)
    P.price_rows(rows)
    for name, srows in side_rows.items():
        P.price_rows(srows)
        tab = collections.defaultdict(lambda: {"n": 0, "units": 0.0, "usd": 0.0, "n_priced": 0})
        for r in srows:
            o = tab[r["asset"]]
            o["n"] += 1
            o["units"] += r["amount"]
            o["usd"] += r["usd"] or 0.0
            o["n_priced"] += r["usd"] is not None
        notes[name] = {"n": len(srows), "usd_priced": sum(r["usd"] or 0.0 for r in srows),
                       "by_asset": dict(sorted(tab.items(), key=lambda kv: -kv[1]["usd"]))}
    if eid == "E45":
        bs = collections.defaultdict(lambda: [0, 0.0])
        for r in rows:
            m = re.search(r"eid (\d+)", r["path"])
            if m:
                bs[int(m.group(1))][0] += 1
                bs[int(m.group(1))][1] += r["usd"] or 0.0
        notes["releases_by_source_chain"] = {f"{k} ({LZ_EID.get(k, '?')})": {"n": v[0], "usd": v[1]}
                                             for k, v in sorted(bs.items(), key=lambda kv: -kv[1][1])}
    with (HERE / f"{eid}.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["ts_utc", "leg", "asset", "amount", "usd", "kind", "priced"])
        for r in rows:
            w.writerow([iso(r["ts"]), leg, r["asset"], r["amount"] if r["nft"] else f"{r['amount']:.12g}",
                        "" if r["usd"] is None else f"{r['usd']:.2f}", r["kind"], "yes" if r["usd"] is not None else "no"])
    (cdir / "rows_with_detail.json").write_text(json.dumps(rows))
    (cdir / "contracts.json").write_text(json.dumps(A, indent=1))
    s = summarize(eid, rows, t0, t1, W)
    s.update({"excluded": dict(excluded),
              "excluded_detail": {k: {a: {"n": v[0], "units": v[1]} for a, v in d.items()} for k, d in excluded_detail.items()},
              "notes": notes})
    # excluded USD (indicative): price excluded outflows of each asset at the median price of priced rows
    (cdir / "summary.json").write_text(json.dumps(s, indent=1, default=str))
    print(json.dumps({k: s[k] for k in ("n_rows", "n_priced", "share_priced", "usd_priced", "by_kind", "largest",
                                        "busiest_hour_usd", "busiest_day_usd", "excluded")}, indent=1, default=str))
    print(json.dumps(notes, indent=1, default=str)[:6000])


def path_of(r):
    p = r["path"]
    if p.startswith("OFTReceived"):
        return "release (OFTReceived)"
    if re.fullmatch(r"batch \d+", p):
        return "batch payout to destination"
    return p


def path_table(rows):
    out = collections.defaultdict(lambda: {"n": 0, "usd": 0.0, "n_priced": 0})
    for r in rows:
        o = out[path_of(r)]
        o["n"] += 1
        o["usd"] += r["usd"] or 0.0
        o["n_priced"] += r["usd"] is not None
    return dict(out)


def summarize(eid, rows, t0, t1, W):
    import numpy as np
    pr = [r for r in rows if r["usd"] is not None]
    fung = [r for r in rows if not r["nft"]]
    by_asset = collections.defaultdict(lambda: {"n": 0, "amount": 0.0, "usd": 0.0, "n_priced": 0, "src": collections.Counter()})
    for r in rows:
        a = by_asset[r["asset"]]
        a["n"] += 1
        a["amount"] += r["amount"]
        a["usd"] += r["usd"] or 0.0
        a["n_priced"] += r["usd"] is not None
        a["src"][r["src"] or "unpriced"] += 1
    hour = collections.defaultdict(lambda: [0, 0.0])
    day = collections.defaultdict(lambda: [0, 0.0])
    for r in rows:
        h = hour[r["ts"] // 3600 * 3600]
        h[0] += 1
        h[1] += r["usd"] or 0.0
        d = day[r["ts"] // 86400 * 86400]
        d[0] += 1
        d[1] += r["usd"] or 0.0
    d0 = t0 // 86400 * 86400
    all_days = [d0 + 86400 * i for i in range((t1 - d0) // 86400 + 1)]
    dvals = np.array([day.get(d, [0, 0.0])[1] for d in all_days])
    usd = np.array([r["usd"] for r in pr]) if pr else np.array([0.0])
    tl = sorted(r["ts"] for r in rows)
    gaps = sorted(((b - a, a, b) for a, b in zip([t0] + tl, tl + [t1])), reverse=True)
    big = max(pr, key=lambda r: r["usd"]) if pr else None
    top = sorted(pr, key=lambda r: -r["usd"])[:10]
    return {
        "id": eid, "window_utc": [iso(t0), iso(t1)], "blocks": [W["b0"], W["b1"]],
        "block_times": [iso(W["ts_b0"]), iso(W["ts_b1"])],
        "n_rows": len(rows), "n_fungible": len(fung), "n_priced": len(pr),
        "share_priced": len(pr) / len(rows) if rows else None,
        "share_priced_fungible": len(pr) / len(fung) if fung else None,
        "usd_priced": float(usd.sum()) if pr else 0.0,
        "by_kind": dict(collections.Counter(r["kind"] for r in rows)),
        "by_path": path_table(rows),
        "price_sources": dict(collections.Counter(r["src"] or "unpriced" for r in rows)),
        "by_asset": {k: {"n": v["n"], "amount": v["amount"], "usd": v["usd"], "n_priced": v["n_priced"],
                         "src": dict(v["src"])} for k, v in sorted(by_asset.items(), key=lambda kv: -kv[1]["usd"])},
        "largest": None if big is None else {"ts_utc": iso(big["ts"]), "asset": big["asset"], "amount": big["amount"],
                                             "usd": big["usd"]},
        "top10": [{"ts_utc": iso(r["ts"]), "asset": r["asset"], "amount": r["amount"], "usd": r["usd"]} for r in top],
        "release_usd_quantiles": {q: float(np.quantile(usd, q)) for q in (0.5, 0.9, 0.99, 0.999)} if pr else None,
        "busiest_hour_usd": (lambda h: {"hour_utc": iso(h), "usd": hour[h][1], "n": hour[h][0]})(max(hour, key=lambda k: hour[k][1])) if hour else None,
        "busiest_hour_count": (lambda h: {"hour_utc": iso(h), "usd": hour[h][1], "n": hour[h][0]})(max(hour, key=lambda k: hour[k][0])) if hour else None,
        "busiest_day_usd": (lambda d: {"day_utc": iso(d)[:10], "usd": day[d][1], "n": day[d][0]})(max(day, key=lambda k: day[k][1])) if day else None,
        "busiest_day_count": (lambda d: {"day_utc": iso(d)[:10], "usd": day[d][1], "n": day[d][0]})(max(day, key=lambda k: day[k][0])) if day else None,
        "days_with_release": len(day), "calendar_days_in_window": len(all_days),
        "daily_usd_over_window": {"mean": float(dvals.mean()), "median": float(np.median(dvals)),
                                  "p90": float(np.quantile(dvals, 0.9)), "p99": float(np.quantile(dvals, 0.99)),
                                  "max": float(dvals.max())},
        "mean_daily_usd_150d": float(usd.sum()) / 150 if pr else 0.0,
        "longest_gaps": [{"hours": round(g[0] / 3600, 1), "from": iso(g[1]), "to": iso(g[2])} for g in gaps[:8]],
        "n_gaps_over_6h": sum(1 for g in gaps if g[0] > 6 * 3600),
        "n_gaps_over_2d": sum(1 for g in gaps if g[0] > 2 * 86400),
        "first_row": iso(tl[0]) if tl else None, "last_row": iso(tl[-1]) if tl else None,
    }


if __name__ == "__main__":
    step, eid = sys.argv[1], sys.argv[2]
    {"collect": collect, "build": build}[step](eid)
