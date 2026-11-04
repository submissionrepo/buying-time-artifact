"""Legitimate release history before the failure, for E21 (lock proxy custody, July 2023 failure).

Inputs  results/incidents.csv               (failure time; read only)
        data/legit/raw/E21/targets.json     (release-point contracts, failure recipients, peg map; addresses stay in raw/)
Outputs data/legit/E21.csv                  (ts_utc, leg, asset, amount, usd, kind, priced; no addresses or hashes)
        data/legit/raw/E21/<chain>/         (raw RPC caches, append-only JSONL so that interrupted runs resume)
        data/legit/raw/E21/prices/          (DefiLlama caches)
        data/legit/raw/E21/rows_with_detail.json, summary.json (numbers quoted in E21_README.md)

Method (copied from collect_legit_E05_E25.py, mode "poly"; the same lock proxy contract on Ethereum)
- Window: [t_fail - 150 d, t_fail - 1 s], t_fail = first_release_utc of E21 in results/incidents.csv.
- Release record: the lock proxy's UnlockEvent(address toAssetHash, address toAddress, uint256 amount), all fields
  non-indexed (polynetwork/eth-contracts, LockProxy.sol); toAssetHash == 0 marks the native coin.
- ERC-20 releases (kind erc20): Transfer logs with the lock proxy as sender, each matched to an UnlockEvent of the same
  token in the same transaction. Unlike E05, BSC Transfer logs are fetched too (50,000-block queries answer quickly).
- Native releases (kind native): UnlockEvent with a zero asset; the lock proxy sends the native coin only inside unlock.
- ERC-20 release events without a matching Transfer log: kind event (amount from the event).
- Transfer logs without a release event in the same transaction are excluded and counted (fee forwarding, admin moves).
- Exclusions: transfers to a lock proxy of this bridge (the legs' contracts, and the 60 most frequent recipients that
  answer managerProxyContract()); releases to a recipient of the failure (targets.json); releases at or after a leg's
  cut_utc (BSC: the first forged BSC release, 12 s before t_fail).
- Prices: DefiLlama /chart daily series for every asset; hourly series for assets worth at least 1M USD on the daily
  pass or with at least 100 releases (nearest point within 2 h); /batchHistorical at the release hour for rows still
  unpriced (pricing_points.py, 2 h); the daily series within 36 h as the last resort. Tokens with a documented issuer peg
  (targets.json "peg") fall back to the underlying coin's series in the same order. Otherwise unpriced.
- Labels: a second token contract with the same symbol on the same chain gets the suffix "#2" (contracts ordered by
  number of releases), so that different contracts are not merged under one symbol.
Run: python -I data/legit/collect_legit_E21.py
"""
import collections
import csv
import datetime
import json
import pathlib
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT / "incidents"))
from rpc import Rpc, TRANSFER, topic_addr, addr_from_topic, erc20_meta  # noqa: E402
sys.path.insert(0, str(HERE))
import pricing  # noqa: E402
import pricing_points  # noqa: E402

EID = "E21"
RAW = HERE / "raw" / EID
UNLOCK = "0xd90288730b87c2b8e0c45bd82260fd22478aba30ae1c4d578b8daba9261604df"  # UnlockEvent(address,address,uint256)
WINDOW_S = 150 * 86400
ZERO = "0x" + "0" * 40
NATIVE_CID = {"ethereum": "coingecko:ethereum", "bsc": "coingecko:binancecoin", "polygon": "coingecko:matic-network",
              "avalanche": "coingecko:avalanche-2", "fantom": "coingecko:fantom", "arbitrum": "coingecko:ethereum",
              "optimism": "coingecko:ethereum", "gnosis": "coingecko:xdai", "metis": "coingecko:metis-token",
              "heco": "coingecko:huobi-token", "okc": "coingecko:oec-token"}
NATIVE_SYM = {"ethereum": "ETH", "bsc": "BNB", "polygon": "MATIC", "avalanche": "AVAX", "fantom": "FTM",
              "arbitrum": "ETH", "optimism": "ETH", "gnosis": "XDAI", "metis": "METIS", "heco": "HT", "okc": "OKT"}
LLAMA_CHAIN = {"ethereum": "ethereum", "bsc": "bsc", "polygon": "polygon", "avalanche": "avax", "fantom": "fantom",
               "arbitrum": "arbitrum", "optimism": "optimism", "gnosis": "xdai", "metis": "metis", "heco": "heco",
               "okc": "okexchain"}
CG_PLATFORM = {"ethereum": "ethereum", "bsc": "binance-smart-chain", "polygon": "polygon-pos", "avalanche": "avalanche",
               "fantom": "fantom", "arbitrum": "arbitrum-one", "optimism": "optimistic-ethereum", "gnosis": "xdai",
               "metis": "metis-andromeda", "okc": "okex-chain", "heco": "huobi-token"}
LEG_CFG = {  # query steps (blocks) and the cut for failure releases that precede t_fail
    "ethereum": {"step": 5000, "unlock_step": 5000, "urls": ["https://rpc.mevblocker.io", "https://mainnet.gateway.tenderly.co"]},
    "bsc": {"step": 50000, "unlock_step": 50000, "cut_utc": "2023-07-01T18:47:35Z"},
}


def _keccak_sel(sig):
    from Crypto.Hash import keccak
    h = keccak.new(digest_bits=256)
    h.update(sig.encode())
    return "0x" + h.hexdigest()[:8]


SEL_MANAGER_PROXY = _keccak_sel("managerProxyContract()")


def iso(ts):
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def to_ts(s):
    return int(datetime.datetime.fromisoformat(s.replace("Z", "")).replace(tzinfo=datetime.timezone.utc).timestamp())


def failure_time(eid):
    with open(ROOT / "results" / "incidents.csv", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["id"] == eid:
                return to_ts(r["first_release_utc"])
    raise KeyError(eid)


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

    def covered(self):
        return sorted(self.done)


def patient(fn, a, b, tries=6):
    """Retry a range query that failed on rate limits (HTTP 429, shared public keys) before giving up."""
    for k in range(tries):
        try:
            return fn(a, b)
        except Exception as ex:  # noqa: BLE001
            msg = str(ex)
            if ("429" not in msg and "Too Many" not in msg and "rate" not in msg.lower()) or k == tries - 1:
                raise
            time.sleep(15 * (k + 1))


def ranged(method_fn, b0, b1, step, cache, label):
    """Fixed chunk grid (stable cache keys); a chunk that fails is split in four (down to 50 blocks)."""
    out = []
    b = b0
    n = 0
    while b <= b1:
        e = min(b + step - 1, b1)
        try:
            out += cache.get(b, e, lambda: patient(method_fn, b, e))
        except Exception as ex:  # noqa: BLE001
            if step <= 50:
                raise
            print(f"   {label}: split {b}-{e} ({str(ex)[:80]})", flush=True)
            out += ranged(method_fn, b, e, max(50, step // 4), cache, label)
        b = e + 1
        n += 1
        if n % 50 == 0:
            print(f"   {label}: block {e} / {b1}, rows {len(out)}", flush=True)
    return out


def coverage_gaps(cache, b0, b1):
    """Block ranges of [b0, b1] not covered by any cached chunk (should be empty)."""
    iv = sorted(cache.covered())
    gaps, expect = [], b0
    for a, b in iv:
        if a > expect:
            gaps.append([expect, a - 1])
        expect = max(expect, b + 1)
    if expect <= b1:
        gaps.append([expect, b1])
    return gaps


def abi_words(data):
    h = data[2:]
    return [h[i:i + 64] for i in range(0, len(h), 64)]


def parse_unlock(lg):
    w = abi_words(lg["data"])
    return {"asset": ("0x" + w[0][-40:]).lower(), "to": ("0x" + w[1][-40:]).lower(), "amount": int(w[2], 16)}


def make_rpc(chain):
    rpc = Rpc(chain)
    urls = LEG_CFG.get(chain, {}).get("urls")
    if urls:
        rpc.urls = urls
    elif chain == "bsc":
        rpc.urls = rpc.urls[:1]  # the fallback endpoint caps logs at 50 blocks
    return rpc


def collect_leg(chain, L, t_fail):
    cfg = LEG_CFG[chain]
    rpc = make_rpc(chain)
    ldir = RAW / chain
    ldir.mkdir(parents=True, exist_ok=True)
    t0 = t_fail - WINDOW_S
    bfile = ldir / "blocks.json"
    if bfile.exists():
        b0, b1 = json.loads(bfile.read_text())
    else:
        b0 = rpc.block_at(t0)
        b1 = rpc.block_at(t_fail) - 1
        bfile.write_text(json.dumps([b0, b1]))
    print(f"== {EID} {L['leg']}: blocks {b0}-{b1}", flush=True)
    rel, xfer, gaps = [], [], {}
    for c in L["custody"]:
        rc = ChunkCache(ldir / f"release_{c[2:10]}.jsonl")
        rel += ranged(lambda a, b: rpc.call("eth_getLogs", [{"address": c, "topics": [UNLOCK],
                                                             "fromBlock": hex(a), "toBlock": hex(b)}]),
                      b0, b1, cfg["unlock_step"], rc, f"{chain} release")
        xc = ChunkCache(ldir / f"transfer_{c[2:10]}.jsonl")
        xfer += ranged(lambda a, b: rpc.call("eth_getLogs", [{"topics": [TRANSFER, topic_addr(c)],
                                                              "fromBlock": hex(a), "toBlock": hex(b)}]),
                       b0, b1, cfg["step"], xc, f"{chain} transfer")
        gaps[c[2:10]] = {"release": coverage_gaps(rc, b0, b1), "transfer": coverage_gaps(xc, b0, b1)}
    return rpc, b0, b1, rel, xfer, gaps


def ts_of(x, rpc, tsc):
    if x.get("blockTimestamp"):
        return int(x["blockTimestamp"], 16)
    b = int(x["blockNumber"], 16)
    if b not in tsc:
        tsc[b] = rpc.block_ts(b)
    return tsc[b]


# ------------------------------------------------------------------------------------------------ prices
def price_rows(rows, pdir, t0, t1, peg, same=None):
    """Assign r["usd"], r["src"] to rows with keys cid, ts, amount (see module docstring for the ladder).

    Keys tried in order: the token's own DefiLlama key; `same` (the same token under its CoinGecko id, where CoinGecko
    lists this contract); `peg` (the asset a documented 1:1 peg tracks; the value "usd:par" prices a USD-pegged
    stablecoin at 1.0)."""
    same = same or {}
    coins = sorted({r["cid"] for r in rows})
    under = sorted({m[c] for m in (same, peg) for c in coins if c in m and m[c] != "usd:par"})
    daily = {c: pricing.chart(c, t0, t1, "1d", pdir, search_width=43200) for c in coins + under}
    vol, n_rel = collections.defaultdict(float), collections.Counter(r["cid"] for r in rows)
    for r in rows:
        for c in (r["cid"], same.get(r["cid"]), peg.get(r["cid"])):
            if c is None or c == "usd:par":
                continue
            p = pricing.nearest(daily[c], r["ts"], 36 * 3600)
            if p is not None:
                vol[r["cid"]] += r["amount"] * p
                break
    hourly = {}
    for c in coins:
        if vol[c] >= 1e6 or n_rel[c] >= 100:
            for cc in (c, same.get(c), peg.get(c)):
                if cc is not None and cc != "usd:par" and cc not in hourly:
                    hourly[cc] = pricing.chart(cc, t0, t1, "1h", pdir, search_width=1800)
    for r in rows:
        r["usd"], r["src"] = None, ""
    for tag, key in (("", lambda r: r["cid"]), (" (same token, CoinGecko id)", lambda r: same.get(r["cid"])),
                     (" (documented peg, tracked asset's series)", lambda r: peg.get(r["cid"]))):
        par = [r for r in rows if r["usd"] is None and key(r) == "usd:par"]
        for r in par:
            r["usd"], r["src"] = r["amount"] * 1.0, "USD par (USD-pegged stablecoin)"
        todo = [r for r in rows if r["usd"] is None and key(r) is not None]
        for r in todo:
            c = key(r)
            p = pricing.nearest(hourly.get(c, []), r["ts"], 2 * 3600)
            if p is not None:
                r["usd"], r["src"] = r["amount"] * p, "defillama chart 1h" + tag
        miss = [r for r in todo if r["usd"] is None]
        tab = pricing_points.lookup([(key(r), r["ts"]) for r in miss], pdir)
        for r in miss:
            c = key(r)
            p = pricing_points.price(tab, c, r["ts"])
            if p is not None:
                r["usd"], r["src"] = r["amount"] * p, "defillama batchHistorical (release hour)" + tag
                continue
            p = pricing.nearest(daily.get(c, []), r["ts"], 36 * 3600)
            if p is not None:
                r["usd"], r["src"] = r["amount"] * p, "defillama chart 1d" + tag
    return {"coins": len(coins), "hourly_series": sorted(hourly), "underlying_used": under}


# ------------------------------------------------------------------------------------------------ main
def main():
    targets = json.loads((HERE / "targets" / f"{EID}.json").read_text())
    peg = targets["peg"]
    fail_to = {a.lower() for a in targets.get("failure_recipients", [])}
    t_fail = failure_time(EID)
    t0, t1 = t_fail - WINDOW_S, t_fail - 1
    legs = {ch: L for ch, L in targets["legs"].items() if ch in LEG_CFG}
    collected = {ch: collect_leg(ch, L, t_fail) for ch, L in legs.items()}
    all_custody = {c.lower() for L in legs.values() for c in L["custody"]}
    excluded = collections.Counter()
    excluded_detail = collections.defaultdict(lambda: [0, collections.Counter()])
    pending, legs_info = [], []
    for ch, (rpc, b0, b1, rel, xfer, gaps) in collected.items():
        L = legs[ch]
        ldir = RAW / ch
        cut = to_ts(LEG_CFG[ch]["cut_utc"]) if LEG_CFG[ch].get("cut_utc") else None
        tsf = ldir / "block_ts.json"
        tsc = {int(k): v for k, v in json.loads(tsf.read_text()).items()} if tsf.exists() else {}
        mf = ldir / "token_meta.json"
        meta = {k: tuple(v) for k, v in json.loads(mf.read_text()).items()} if mf.exists() else {}
        ev_by_tx = collections.defaultdict(list)
        seen = set()
        for lg in rel:
            k = (lg["transactionHash"], lg["logIndex"])
            if lg.get("removed") or k in seen:
                continue
            seen.add(k)
            ev = parse_unlock(lg)
            ev.update({"ts": ts_of(lg, rpc, tsc), "block": int(lg["blockNumber"], 16), "tx": lg["transactionHash"],
                       "li": int(lg["logIndex"], 16), "matched": False})
            ev_by_tx[lg["transactionHash"]].append(ev)
        n_events = sum(len(v) for v in ev_by_tx.values())

        def drop(reason, ts, asset_key, amount_raw):
            excluded[f"{ch}: {reason}"] += 1
            d = excluded_detail[f"{ch}: {reason}"]
            d[0] += 1
            d[1][asset_key] += 1

        def keep(ts, kind, tok, raw, to):
            if to in all_custody:
                drop("to a lock proxy of this bridge", ts, tok, raw)
                return
            if to in fail_to:
                drop("to a recipient of the failure", ts, tok, raw)
                return
            if cut is not None and ts >= cut:
                drop("at or after the first forged release on this leg", ts, tok, raw)
                return
            if ts < t0 or ts > t1:
                drop("outside window", ts, tok, raw)
                return
            if tok == "native":
                sym, dec, cid = NATIVE_SYM[ch], 18, NATIVE_CID[ch]
            else:
                sym, dec = erc20_meta(rpc, tok, meta)
                cid = f"{LLAMA_CHAIN[ch]}:{tok}"
            pending.append({"ts": ts, "leg": L["leg"], "chain": ch, "symbol": (sym or "?").strip() or "?", "token": tok,
                            "cid": cid, "amount": raw / 10 ** dec, "raw": str(raw), "kind": kind, "to": to})

        unmatched_out = []
        seen_x = set()
        for lg in xfer:
            k = (lg["transactionHash"], lg["logIndex"])
            if lg.get("removed") or k in seen_x:
                continue
            seen_x.add(k)
            if len(lg["topics"]) != 3:
                excluded[f"{ch}: transfer log with nonstandard topics (NFT)"] += 1
                continue
            ts = ts_of(lg, rpc, tsc)
            to = addr_from_topic(lg["topics"][2]).lower()
            tok = lg["address"].lower()
            raw = int(lg["data"], 16) if lg["data"] not in ("0x", "") else 0
            evs = ev_by_tx.get(lg["transactionHash"], [])
            m = [e for e in evs if e["asset"] == tok and not e["matched"]]
            if not m:
                excluded[f"{ch}: token outflow without a release event of that token in the transaction"] += 1
                unmatched_out.append({"ts": ts, "token": tok, "raw": str(raw), "to": to, "tx": lg["transactionHash"],
                                      "has_any_event": bool(evs)})
                continue
            # prefer the event with the same recipient and amount
            m.sort(key=lambda e: (e["to"] != to, e["amount"] != raw))
            m[0]["matched"] = True
            m[0]["xfer_amount"] = raw
            keep(ts, "erc20", tok, raw, to)
        for evs in ev_by_tx.values():
            for e in evs:
                if e["asset"] == ZERO:
                    e["matched"] = True
                    keep(e["ts"], "native", "native", e["amount"], e["to"])
        unmatched_ev = []
        for evs in ev_by_tx.values():
            for e in evs:
                if not e["matched"]:
                    unmatched_ev.append(e)
                    keep(e["ts"], "event", e["asset"], e["amount"], e["to"])
        amount_mismatch = sum(1 for evs in ev_by_tx.values() for e in evs
                              if "xfer_amount" in e and e["xfer_amount"] != e["amount"])
        tsf.write_text(json.dumps(tsc))
        mf.write_text(json.dumps(meta))
        (ldir / "unmatched_release_events.json").write_text(json.dumps(unmatched_ev, indent=0))
        (ldir / "outflows_without_release_event.json").write_text(json.dumps(unmatched_out, indent=0))
        legs_info.append({"leg": L["leg"], "chain": ch, "block_from": b0, "block_to": b1,
                          "block_ts_from": iso(rpc.block_ts(b0)), "block_ts_to": iso(rpc.block_ts(b1)),
                          "n_release_events": n_events, "n_transfer_logs": len(seen_x),
                          "n_release_events_without_transfer": len(unmatched_ev),
                          "n_transfer_amount_differs_from_event": amount_mismatch,
                          "n_outflows_without_release_event": len(unmatched_out),
                          "coverage_gaps": gaps, "cut_utc": LEG_CFG[ch].get("cut_utc")})
    # releases to other lock proxies of the same bridge (lock proxies answer managerProxyContract())
    own, checked = set(), 0
    by_to = collections.Counter((r["chain"], r["to"]) for r in pending)
    rpcs = {ch: v[0] for ch, v in collected.items()}
    for (ch, to), _n in by_to.most_common(60):
        checked += 1
        try:
            code = rpcs[ch].call("eth_getCode", [to, "latest"])
            if code and len(code) > 2:
                r_ = rpcs[ch].eth_call(to, SEL_MANAGER_PROXY)
                if r_ and len(r_) >= 66 and int(r_, 16) != 0:
                    own.add((ch, to))
        except Exception:  # noqa: BLE001
            pass
    (RAW / "own_contract_recipients.json").write_text(json.dumps(sorted(own)))
    kept = []
    for r in pending:
        if (r["chain"], r["to"]) in own:
            excluded[f"{r['chain']}: to another lock proxy of this bridge (managerProxyContract)"] += 1
            continue
        kept.append(r)
    # labels: per chain, contracts with the same symbol ordered by number of releases
    by_sym = collections.defaultdict(collections.Counter)
    for r in kept:
        by_sym[(r["chain"], r["symbol"])][r["token"]] += 1
    label = {}
    for (ch, sym), cnt in by_sym.items():
        for i, (tok, _n) in enumerate(cnt.most_common()):
            label[(ch, tok)] = sym if i == 0 else f"{sym}#{i + 1}"
    for r in kept:
        r["asset"] = label[(r["chain"], r["token"])]
    pinfo = price_rows(kept, RAW / "prices", t0, t1, peg)
    # second pass: tokens with unpriced rows, looked up by contract on CoinGecko (same token, other key)
    same = {}
    for ch in sorted({r["chain"] for r in kept}):
        unp = sorted({r["token"] for r in kept if r["chain"] == ch and r["usd"] is None and r["token"] != "native"})
        if unp and ch in CG_PLATFORM:
            ids = pricing_points.cg_ids(CG_PLATFORM[ch], unp, RAW / "prices" / f"cg_{ch}")
            same.update({f"{LLAMA_CHAIN[ch]}:{t}": f"coingecko:{i}" for t, i in ids.items() if i})
    if same:
        pinfo = price_rows(kept, RAW / "prices", t0, t1, peg, same)
    pinfo["same_token_coingecko"] = len(same)
    kept.sort(key=lambda r: (r["ts"], r["leg"]))
    with (HERE / f"{EID}.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["ts_utc", "leg", "asset", "amount", "usd", "kind", "priced"])
        for r in kept:
            w.writerow([iso(r["ts"]), r["leg"], r["asset"], f"{r['amount']:.10g}",
                        "" if r["usd"] is None else f"{r['usd']:.2f}", r["kind"], "yes" if r["usd"] is not None else "no"])
    (RAW / "rows_with_detail.json").write_text(json.dumps(kept))
    s = summarize(kept, t0, t1)
    s.update({"id": EID, "t_fail_utc": iso(t_fail), "window_utc": [iso(t0), iso(t1)], "legs": legs_info,
              "excluded": dict(excluded),
              "excluded_by_asset": {k: dict(v[1].most_common(10)) for k, v in excluded_detail.items()},
              "own_contract_recipients_checked": checked, "own_contract_recipients_found": len(own),
              "pricing": pinfo})
    (RAW / "summary.json").write_text(json.dumps(s, indent=1, default=str))
    print(json.dumps({k: s[k] for k in ("n_rows", "n_priced", "share_priced_count", "usd_total_priced", "by_leg",
                                        "excluded", "largest_release", "busiest_hour_usd", "busiest_day_usd")},
                     indent=1, default=str))


def summarize(rows, t0, t1):
    import numpy as np
    pr = [r for r in rows if r["usd"] is not None]
    out = {"n_rows": len(rows), "n_priced": len(pr), "share_priced_count": len(pr) / len(rows) if rows else None,
           "usd_total_priced": sum(r["usd"] for r in pr),
           "price_sources": dict(collections.Counter(r["src"] or "unpriced" for r in rows)),
           "by_kind": dict(collections.Counter(r["kind"] for r in rows))}
    legs = sorted({r["leg"] for r in rows})
    out["by_leg"] = {}
    for leg in legs + ["all"]:
        rr = [r for r in rows if leg == "all" or r["leg"] == leg]
        pp = [r for r in rr if r["usd"] is not None]
        hour, day, hour_n, day_n = (collections.defaultdict(float), collections.defaultdict(float),
                                    collections.Counter(), collections.Counter())
        for r in rr:
            h, d = r["ts"] - r["ts"] % 3600, r["ts"] - r["ts"] % 86400
            hour_n[h] += 1
            day_n[d] += 1
            if r["usd"] is not None:
                hour[h] += r["usd"]
                day[d] += r["usd"]
        d_first = t0 - t0 % 86400
        days_all = [d_first + 86400 * i for i in range(int((t1 - d_first) // 86400) + 1)]
        dv = np.array([day.get(d, 0.0) for d in days_all])
        uv = np.array([r["usd"] for r in pp]) if pp else np.array([0.0])
        tl = sorted(r["ts"] for r in rr)
        gaps = sorted(((b - a, iso(a), iso(b)) for a, b in zip([t0] + tl, tl + [t1])), reverse=True)[:5]
        big = max(pp, key=lambda r: r["usd"]) if pp else None
        by_asset = collections.defaultdict(lambda: [0, 0.0, 0.0, 0])
        for r in rr:
            a = by_asset[r["asset"]]
            a[0] += 1
            a[1] += r["amount"]
            a[2] += r["usd"] or 0.0
            a[3] += r["usd"] is not None
        out["by_leg"][leg] = {
            "n": len(rr), "n_priced": len(pp), "usd": float(uv.sum()) if pp else 0.0,
            "by_kind": dict(collections.Counter(r["kind"] for r in rr)),
            "first": iso(tl[0]) if tl else None, "last": iso(tl[-1]) if tl else None,
            "days_with_release": len(day_n), "calendar_days": len(days_all),
            "release_usd_quantiles": {q: float(np.quantile(uv, q)) for q in (0.5, 0.9, 0.99)},
            "daily_usd_quantiles": {q: float(np.quantile(dv, q)) for q in (0.5, 0.9, 1.0)},
            "daily_usd_mean_150d": float(uv.sum()) / 150 if pp else 0.0,
            "largest": None if big is None else {"ts": iso(big["ts"]), "asset": big["asset"], "amount": big["amount"],
                                                 "usd": big["usd"]},
            "busiest_hour_usd": (lambda h: {"hour": iso(h), "usd": hour[h], "n": hour_n[h]})(max(hour, key=hour.get))
            if hour else None,
            "busiest_hour_count": (lambda h: {"hour": iso(h), "n": hour_n[h], "usd": hour.get(h, 0.0)})(
                max(hour_n, key=hour_n.get)) if hour_n else None,
            "busiest_day_usd": (lambda d: {"day": iso(d)[:10], "usd": day[d], "n": day_n[d]})(max(day, key=day.get))
            if day else None,
            "busiest_day_count": (lambda d: {"day": iso(d)[:10], "n": day_n[d], "usd": day.get(d, 0.0)})(
                max(day_n, key=day_n.get)) if day_n else None,
            "longest_gaps": [{"hours": round(g[0] / 3600, 1), "from": g[1], "to": g[2]} for g in gaps],
            "by_asset": sorted([{"asset": k, "n": v[0], "amount": v[1], "usd": v[2], "n_priced": v[3]}
                                for k, v in by_asset.items()], key=lambda x: (-x["usd"], -x["n"]))[:40],
            "unpriced_by_asset": sorted([{"asset": k, "n": v[0] - v[3], "amount_all_rows": v[1]}
                                         for k, v in by_asset.items() if v[0] > v[3]], key=lambda x: -x["n"])[:40],
        }
    out["largest_release"] = out["by_leg"]["all"]["largest"]
    out["busiest_hour_usd"] = out["by_leg"]["all"]["busiest_hour_usd"]
    out["busiest_day_usd"] = out["by_leg"]["all"]["busiest_day_usd"]
    return out


if __name__ == "__main__":
    main()
