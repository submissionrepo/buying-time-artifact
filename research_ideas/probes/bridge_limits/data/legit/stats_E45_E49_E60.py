"""Extra figures for the E45, E49 and E60 READMEs (2026-10-16).

Reads raw/<ID>/rows_with_detail.json, summary.json, balances.json and the raw chunk caches written by
collect_legit_E45_E49_E60.py. Writes raw/<ID>/stats_extra.json (no addresses or hashes):
  - monthly release counts and USD;
  - variants: without the largest recipient by USD (E45), destination payouts only (E49, E60: fee rows dropped);
  - USD value of the release point's balances at the window edges (DefiLlama prices at those times), for the
    comparison with published TVL or balance figures;
  - E60: dates of contract upgrades, of large native inflows, and the gap left by the halt after E48.
Run: python -I -B data/legit/stats_E45_E49_E60.py E45|E49|E60
"""
import collections
import datetime
import json
import pathlib
import sys

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import collect_legit_E45_E49_E60 as C  # noqa: E402
import pricing_points  # noqa: E402


def iso(ts):
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def series_stats(rows, t0, t1):
    pr = [r for r in rows if r["usd"] is not None]
    if not pr:
        return None
    hour = collections.defaultdict(float)
    day = collections.defaultdict(float)
    for r in pr:
        hour[r["ts"] // 3600] += r["usd"]
        day[r["ts"] // 86400] += r["usd"]
    d0 = t0 // 86400
    dv = np.array([day.get(d, 0.0) for d in range(d0, t1 // 86400 + 1)])
    big = max(pr, key=lambda r: r["usd"])
    bh = max(hour, key=hour.get)
    bd = max(day, key=day.get)
    u = np.array([r["usd"] for r in pr])
    return {"n": len(rows), "n_priced": len(pr), "usd": float(u.sum()),
            "largest": {"ts_utc": iso(big["ts"]), "asset": big["asset"], "amount": big["amount"], "usd": big["usd"]},
            "busiest_hour": {"hour_utc": iso(bh * 3600), "usd": hour[bh]},
            "busiest_day": {"day_utc": iso(bd * 86400)[:10], "usd": day[bd]},
            "release_usd_quantiles": {q: float(np.quantile(u, q)) for q in (0.5, 0.9, 0.99)},
            "daily": {"mean": float(dv.mean()), "median": float(np.median(dv)), "p90": float(np.quantile(dv, 0.9)),
                      "p99": float(np.quantile(dv, 0.99)), "max": float(dv.max())}}


def main(eid):
    cdir = HERE / "raw" / eid
    rows = json.loads((cdir / "rows_with_detail.json").read_text())
    W = json.loads((cdir / "blocks.json").read_text())
    t0, t1 = W["t0"], W["t1"]
    bal = json.loads((cdir / "balances.json").read_text())
    meta = {k: tuple(v) for k, v in json.loads((cdir / "token_meta.json").read_text()).items()}
    out = {}
    month = collections.defaultdict(lambda: [0, 0.0])
    for r in rows:
        k = iso(r["ts"])[:7]
        month[k][0] += 1
        month[k][1] += r["usd"] or 0.0
    out["monthly"] = {k: {"n": v[0], "usd": v[1]} for k, v in sorted(month.items())}
    out["all"] = series_stats(rows, t0, t1)
    if eid == "E45":
        by = collections.defaultdict(float)
        for r in rows:
            by[r["to"]] += r["usd"] or 0.0
        top = max(by, key=by.get)
        out["without_largest_recipient"] = series_stats([r for r in rows if r["to"] != top], t0, t1)
        out["largest_recipient"] = {"n": sum(1 for r in rows if r["to"] == top), "usd": by[top]}
    else:
        pay = [r for r in rows if "fee" not in r["path"]]
        out["payouts_only"] = series_stats(pay, t0, t1)
        out["fee_rows"] = {"n": len(rows) - len(pay), "usd": sum(r["usd"] or 0.0 for r in rows if "fee" in r["path"])}
    # balances at the window edges in USD (DefiLlama batchHistorical at the edge times)
    pairs = []
    for tag, ts in (("start", t0 - 1), ("end", t1)):
        pairs.append(("coingecko:ethereum", ts))
        for tk, v in bal[tag]["tokens"].items():
            if v is not None and 0 < int(v) < 2 ** 200:
                pairs.append((f"ethereum:{tk}", ts))
    table = pricing_points.lookup(pairs, cdir / "prices")
    edges = {}
    for tag, ts in (("start", t0 - 1), ("end", t1)):
        tot, unpriced, parts = 0.0, [], {}
        p = pricing_points.price(table, "coingecko:ethereum", ts)
        if bal[tag]["native"] and p:
            parts["ETH (native)"] = bal[tag]["native"] / 1e18 * p
        for tk, v in bal[tag]["tokens"].items():
            if v is None or not (0 < int(v) < 2 ** 200):
                continue
            sym, dec = meta.get(tk, ("?", 18))
            p = pricing_points.price(table, f"ethereum:{tk}", ts)
            if p is None:
                unpriced.append(sym)
                continue
            parts[sym] = parts.get(sym, 0.0) + int(v) / 10 ** dec * p
        tot = sum(parts.values())
        edges[tag] = {"time_utc": iso(ts), "usd_priced": tot,
                      "largest_parts": dict(sorted(parts.items(), key=lambda kv: -kv[1])[:8]),
                      "n_unpriced_tokens": len(unpriced)}
    out["balances_usd"] = edges
    if eid == "E60":
        sels = C.delegator_selectors(cdir)
        trt = C.load_chunks(cdir, "traces_to.jsonl")
        bts = {int(k): v for k, v in json.loads((cdir / "block_ts.json").read_text()).items()}
        up = sorted({iso(bts[x["block"]]) for x in trt if sels.get(x["input"][:10]) in ("upgradeContracts", "replacecontract")
                     and not x.get("error")})
        out["upgrade_calls_utc"] = up
        big_in = sorted(((bts[x["block"]], int(x["value"], 16) / 1e18, sels.get(x["input"][:10], x["input"][:10]))
                         for x in trt if x["ct"] == "call" and not x.get("error") and int(x["value"] or "0x0", 16) > 50 * 10 ** 18),
                        key=lambda z: -z[1])[:10]
        out["native_inflows_over_50_eth"] = [{"ts_utc": iso(a), "eth": b, "function": c} for a, b, c in big_in]
        imp = C.import_selectors(cdir)
        ok_imp = sorted(bts[x["block"]] for x in trt if x["input"][:10] in imp and not x.get("error"))
        mid = [t for t in ok_imp if iso(t) > "2026-05-17T23:55:23Z"]
        out["imports_ok"] = {"n": len(ok_imp), "last_before_E48": iso(max(t for t in ok_imp if iso(t) < "2026-05-17T23:55:23Z")),
                             "first_after_E48": iso(min(mid)) if mid else None,
                             "failed_import_calls": sum(1 for x in trt if x["input"][:10] in imp and x.get("error"))}
    if eid == "E49":
        own = C.load_chunks(cdir, "logs_own.jsonl")
        out["valset_updates_utc"] = [iso(int(lg["blockTimestamp"], 16)) for lg in own if lg["topics"][0] == C.VALSET_UPDATED]
        bt = sorted(int(lg["blockTimestamp"], 16) for lg in own if lg["topics"][0] == C.BATCH_EXECUTED)
        out["batch_executions"] = {"n": len(bt), "first": iso(bt[0]), "last": iso(bt[-1]),
                                   "per_month": dict(collections.Counter(iso(t)[:7] for t in bt))}
    if eid == "E45":
        own = C.load_chunks(cdir, "logs_own.jsonl")
        sent = [int(C.word(lg["data"], 1), 16) / 1e18 for lg in own if lg["topics"][0] == C.OFT_SENT]
        out["outbound_sends"] = {"n": len(sent), "rsETH": sum(sent)}
    (cdir / "stats_extra.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1)[:7000])


if __name__ == "__main__":
    main(sys.argv[1])
