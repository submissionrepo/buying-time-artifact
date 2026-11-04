"""Release timings of bridge drain events measured from chain data (2026-10-16).

Input  data/incidents/onchain_targets.json   (custody contracts, block windows; the recipient addresses are
                                              withheld, see `selected_releases`)
Output data/incidents/onchain/<target>.json   (untracked: every candidate release row, with hashes)
       data/incidents/onchain_summary.json    (no addresses or hashes: times, counts, USD path)

Method:
- ERC-20 releases: Transfer logs with topic1 = a custody address, over the block window.
- Native-coin releases: trace_filter (callType "call", value > 0) from the custody addresses.
- Selection: rows sent to the listed recipient addresses when the target lists them (in this copy the
  recipients are withheld and `selected_releases` lists the selected rows by block, symbol and amount
  instead); otherwise rows
  of at least `min_usd` USD; optional per-transaction classification (`classify`) for events with
  many independent withdrawers (Nomad: transactions that reached the Replica through process(bytes)
  without a proof count as unauthorized; proveAndProcess counts as authorized).
- USD at the time: DefiLlama coins API historical price at the first selected row (searchWidth 6h).
- Times are block timestamps (UTC). Durations are first to last selected release on the leg.
- Pause times: first log matching a target's `pause_logs` entry at or after the first release.
Run: python -I incidents/02_onchain_timing.py [target_id ...]
"""
import datetime
import json
import pathlib
import sys
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from rpc import (Rpc, TRANSFER, topic_addr, addr_from_topic, erc20_meta)  # noqa: E402

HERE = pathlib.Path(__file__).resolve().parent
DATA = HERE.parent / "data" / "incidents"
CONFIG = DATA / "onchain_targets.json"
OUTDIR = DATA / "onchain"
SUMMARY = DATA / "onchain_summary.json"
PRICES = DATA / "prices"

LLAMA_CHAIN = {"ethereum": "ethereum", "bsc": "bsc", "polygon": "polygon", "arbitrum": "arbitrum",
               "base": "base", "fantom": "fantom", "avalanche": "avax", "optimism": "optimism"}
NATIVE_ID = {"ethereum": "coingecko:ethereum", "bsc": "coingecko:binancecoin",
             "polygon": "coingecko:matic-network", "arbitrum": "coingecko:ethereum",
             "base": "coingecko:ethereum", "optimism": "coingecko:ethereum",
             "fantom": "coingecko:fantom", "avalanche": "coingecko:avalanche-2"}


def to_ts(s):
    return int(datetime.datetime.fromisoformat(s).replace(tzinfo=datetime.timezone.utc).timestamp())


def iso(ts):
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def llama_prices(coins, ts, cache_file):
    if cache_file.exists():
        cached = json.loads(cache_file.read_text())
        if set(coins) <= set(cached.get("coins", {})) | set(cached.get("missing", [])):
            return cached
    out = {"ts": ts, "coins": {}, "missing": []}
    for i in range(0, len(coins), 40):
        chunk = coins[i:i + 40]
        url = f"https://coins.llama.fi/prices/historical/{ts}/{','.join(chunk)}?searchWidth=6h"
        req = urllib.request.Request(url, headers={"User-Agent": "bridge-limits-probe/1.0"})
        with urllib.request.urlopen(req, timeout=60) as r:
            j = json.loads(r.read().decode())
        out["coins"].update(j.get("coins", {}))
    out["missing"] = [c for c in coins if c not in out["coins"]]
    cache_file.write_text(json.dumps(out, indent=1))
    return out


class TsCache:
    def __init__(self, rpc):
        self.rpc, self.c = rpc, {}

    def __call__(self, b):
        if b not in self.c:
            self.c[b] = self.rpc.block_ts(b)
        return self.c[b]


def collect(t):
    chain = t["chain"]
    rpc = Rpc(chain)
    tsc = TsCache(rpc)
    w0, w1 = to_ts(t["window_utc"][0]), to_ts(t["window_utc"][1])
    b0 = t.get("block_from") or rpc.block_at(w0)
    b1 = t.get("block_to") or rpc.block_at(w1)
    custody = [a.lower() for a in t["custody"]]
    exclude = set(a.lower() for a in t.get("exclude_to", [])) | set(custody)
    rows = []
    meta = {}
    if t.get("erc20", True):
        for c in custody:
            for lg in rpc.logs(None, [TRANSFER, topic_addr(c)], b0, b1, step=t.get("log_step", 5000)):
                if len(lg["topics"]) != 3:
                    continue  # ERC-721 transfers carry the token id as a fourth topic
                to = addr_from_topic(lg["topics"][2]).lower()
                if to in exclude:
                    continue
                blk = int(lg["blockNumber"], 16)
                ts = int(lg["blockTimestamp"], 16) if lg.get("blockTimestamp") else tsc(blk)
                tok = lg["address"].lower()
                sym, dec = erc20_meta(rpc, tok, meta)
                raw = int(lg["data"], 16) if lg["data"] not in ("0x", "") else 0
                rows.append({"kind": "erc20", "token": tok, "symbol": sym, "decimals": dec, "raw": str(raw),
                             "amount": raw / 10 ** dec, "to": to, "block": blk, "ts": ts,
                             "tx": lg["transactionHash"], "custody": c})
    if t.get("native") == "trace":
        rt = Rpc(chain + "_trace")
        for x in rt.trace_filter(custody, b0, b1, step=t.get("trace_step", 2000)):
            a = x.get("action", {})
            if x.get("type") != "call" or a.get("callType") != "call":
                continue
            v = int(a.get("value", "0x0"), 16)
            to = (a.get("to") or "").lower()
            if v == 0 or to in exclude:
                continue
            blk = x["blockNumber"]
            rows.append({"kind": "native", "token": "native", "symbol": t.get("native_symbol", "ETH"),
                         "decimals": 18, "raw": str(v), "amount": v / 1e18, "to": to, "block": blk,
                         "ts": tsc(blk), "tx": x["transactionHash"], "custody": a.get("from", "").lower()})
    return rpc, tsc, b0, b1, rows


def classify_nomad(rows, t):
    """Mark each transaction as unauthorized when a Replica was entered through process(bytes).

    Nomad ran one Replica per remote domain on Ethereum; `replicas` lists every Replica proxy and
    implementation seen in the traces (2026-10-16 re-run: the earlier single-Replica setting left
    68 transactions through a second Replica unclassified)."""
    rt = Rpc(t["chain"] + "_trace")
    replicas = set(a.lower() for a in (t["classify"].get("replicas") or [t["classify"]["replica"]]))
    bad = set(s.lower() for s in t["classify"]["unauthorized_selectors"])
    good = set(s.lower() for s in t["classify"]["authorized_selectors"])
    verdict = {}
    for txh in sorted(set(r["tx"] for r in rows)):
        res = "unknown"
        try:
            traces = rt.call("trace_transaction", [txh]) or []
        except Exception:
            traces = []
        sels = [(tr.get("action", {}).get("input") or "")[:10].lower() for tr in traces
                if (tr.get("action", {}).get("to") or "").lower() in replicas]
        if any(s in bad for s in sels):
            res = "unauthorized"
        elif any(s in good for s in sels):
            res = "authorized"
        verdict[txh] = res
    for r in rows:
        r["class"] = verdict[r["tx"]]
    return verdict


def run(tid, t):
    rpc, tsc, b0, b1, rows = collect(t)
    chain = t["chain"]
    # prices
    if rows:
        ts_first = min(r["ts"] for r in rows)
        coins = sorted({(NATIVE_ID[chain] if r["token"] == "native" else f"{LLAMA_CHAIN[chain]}:{r['token']}")
                        for r in rows})
        coins += [c for c in t.get("extra_price_ids", []) if c not in coins]
        coins += [c for c in t.get("price_alias", {}).values() if c not in coins]
        PRICES.mkdir(parents=True, exist_ok=True)
        pr = llama_prices(coins, ts_first, PRICES / f"{tid}.json")
        manual = t.get("manual_prices", {})
        for r in rows:
            cid = NATIVE_ID[chain] if r["token"] == "native" else f"{LLAMA_CHAIN[chain]}:{r['token']}"
            cid = t.get("price_alias", {}).get(r["token"], cid)
            p = pr["coins"].get(cid, {}).get("price")
            if p is None and r["token"] in manual:
                p = manual[r["token"]]
            r["price"] = p
            r["usd"] = r["amount"] * p if p is not None else None
    # selection
    recips = set(a.lower() for a in t.get("recipients", []))
    # artifact copy: the recipient addresses are withheld; the rows they received are listed by
    # (block, symbol, amount)
    sel_rel = t.get("selected_releases")
    min_usd = t.get("min_usd", 0)
    if t.get("expand_to_recipients") and min_usd:
        # recipients of the large releases; then every release to them counts, whatever its size
        recips = {r["to"] for r in rows if (r["usd"] or 0) >= min_usd}
    if t.get("classify", {}).get("type") == "replica_selector":
        classify_nomad(rows, t)
    for r in rows:
        ok = True
        if sel_rel is not None:
            ok = any(r["block"] == b and r["symbol"] == s and abs(r["amount"] - a) <= 1e-9 * max(1.0, abs(a))
                     for b, s, a in sel_rel)
        elif recips:
            ok = r["to"] in recips
        elif min_usd:
            ok = (r["usd"] or 0) >= min_usd
        if "class" in r:
            ok = ok and r["class"] == "unauthorized"
        r["selected"] = ok
    sel = sorted([r for r in rows if r["selected"]], key=lambda r: (r["ts"], r["block"]))
    # pause logs
    pauses = []
    for p in t.get("pause_logs", []):
        pb1 = rpc.block_at(to_ts(p["until_utc"])) if p.get("until_utc") else b1
        pb0 = rpc.block_at(sel[0]["ts"]) if sel else b0
        for lg in rpc.logs(p["address"], [p["topic0"]], pb0, pb1, step=t.get("log_step", 5000)):
            blk = int(lg["blockNumber"], 16)
            ts = int(lg["blockTimestamp"], 16) if lg.get("blockTimestamp") else tsc(blk)
            pauses.append({"label": p["label"], "ts": ts, "utc": iso(ts), "block": blk, "tx": lg["transactionHash"]})
    pauses.sort(key=lambda x: x["ts"])
    OUTDIR.mkdir(parents=True, exist_ok=True)
    (OUTDIR / f"{tid}.json").write_text(json.dumps({"target": tid, "config": t, "blocks": [b0, b1],
                                                    "rows": rows, "pauses": pauses}, indent=1))
    # summary without addresses or hashes
    s = {"target": tid, "event_id": t["event_id"], "leg": t.get("leg", chain), "chain": chain,
         "selection": ("recipients of releases >= min_usd " + str(min_usd)) if t.get("expand_to_recipients")
         else ("recipients" if (recips or sel_rel is not None) else (f"min_usd {min_usd}" if min_usd else "all")),
         "classified": "class" in (rows[0] if rows else {}),
         "n_candidate_rows": len(rows), "n_selected_rows": len(sel)}
    if sel:
        txs = {}
        for r in sel:
            d = txs.setdefault(r["tx"], {"ts": r["ts"], "usd": 0.0, "usd_missing": 0})
            d["ts"] = min(d["ts"], r["ts"])
            if r["usd"] is None:
                d["usd_missing"] += 1
            else:
                d["usd"] += r["usd"]
        tl = sorted(txs.values(), key=lambda d: d["ts"])
        t0, t1 = tl[0]["ts"], tl[-1]["ts"]
        tot = sum(d["usd"] for d in tl)
        by_sym = {}
        for r in sel:
            by_sym.setdefault(r["symbol"], [0.0, 0.0])
            by_sym[r["symbol"]][0] += r["amount"]
            by_sym[r["symbol"]][1] += r["usd"] or 0.0
        s.update({
            "first_release_utc": iso(t0), "last_release_utc": iso(t1), "duration_s": t1 - t0,
            "n_release_tx": len(tl), "usd_total": tot,
            "usd_missing_rows": sum(d["usd_missing"] for d in tl),
            "by_symbol": {k: {"amount": round(v[0], 6), "usd": round(v[1], 2)} for k, v in
                          sorted(by_sym.items(), key=lambda kv: -kv[1][1])},
            "path": [[d["ts"] - t0, round(d["usd"], 2)] for d in tl],
            "share_within": {str(h): (sum(d["usd"] for d in tl if d["ts"] - t0 <= h) / tot if tot else None)
                             for h in (600, 3600, 21600, 86400)},
        })
    if pauses:
        s["pause_logs"] = [{"label": p["label"], "utc": p["utc"],
                            "lag_from_first_release_s": (p["ts"] - sel[0]["ts"]) if sel else None}
                           for p in pauses[:3]]
    return s


def main():
    cfg = json.loads(CONFIG.read_text())
    want = set(sys.argv[1:])
    summary = json.loads(SUMMARY.read_text()) if SUMMARY.exists() else {}
    for tid, t in cfg.items():
        if tid.startswith("_") or (want and tid not in want):
            continue
        print("==", tid, flush=True)
        s = run(tid, t)
        # re-read before writing so that concurrent runs on other targets are not overwritten
        summary = json.loads(SUMMARY.read_text()) if SUMMARY.exists() else {}
        summary[tid] = s
        SUMMARY.write_text(json.dumps(summary, indent=1))
        keys = ("first_release_utc", "last_release_utc", "duration_s", "n_release_tx", "usd_total",
                "n_candidate_rows", "n_selected_rows", "share_within", "pause_logs", "usd_missing_rows")
        print(json.dumps({k: s.get(k) for k in keys}, indent=None))
        if s.get("by_symbol"):
            print("   ", {k: v for k, v in list(s["by_symbol"].items())[:8]})


if __name__ == "__main__":
    main()
