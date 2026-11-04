"""Legitimate release history before the failure, for E58 (Cardano-side treasury of a Cardano-BNB Chain bridge).

Inputs  results/incidents.csv              (failure time; read only)
        data/legit/raw/E58/targets.json    (treasury payment credential, failure recipient; addresses stay in raw/)
Outputs data/legit/E58.csv                 (ts_utc, leg, asset, amount, usd, kind, priced; no addresses or hashes)
        data/legit/raw/E58/koios/          (Koios caches: block heights, credential_txs pages, tx_info batches, asset_info)
        data/legit/raw/E58/prices/         (DefiLlama caches)
        data/legit/raw/E58/tx_flows.json, rows_with_detail.json, summary.json (numbers quoted in E58_README.md)

Source: the public Koios API (https://api.koios.rest/api/v1, no key): /blocks for the window's block heights,
/credential_txs for every transaction that touches the treasury's payment credential (inputs or outputs, any stake
part), /tx_info for inputs, outputs, native assets and metadata, /asset_info for token-registry decimals.

Method
- Window: [t_fail - 150 d, t_fail - 1 s], t_fail = first_release_utc of E58 in results/incidents.csv.
- UTXO accounting per transaction and asset: net outflow = value of spent treasury outputs - value of new treasury
  outputs (lovelace and each native asset). A release is a positive net outflow of a native asset or of ADA.
- Receiving outputs: outputs at an address that is not the treasury credential and does not also fund an input of the
  same transaction (the fee payer's change and the release-check script's own token output come back to an input
  address). The release row's amount is the treasury's net outflow; the recipient outputs are checked to hold it.
- One row per (transaction, asset). kind "erc20" marks a native-token outflow (Cardano has no ERC-20; the label keeps
  the column's three values) and kind "native" an ADA outflow. ADA that only accompanies a token release as the ledger's
  minimum UTXO deposit (net ADA outflow at most MIN_ADA_COMPANION in a transaction that also releases a token) is not a
  separate row; it is counted and valued in summary.json.
- Exclusions: outflows to a recipient of the failure (targets.json); transactions with no net outflow (deposits, UTXO
  management); outflows that only go to other script addresses are listed separately for inspection.
- Bridge metadata (label 1) is decoded where present: type 1 marks a deposit (cross-chain lock), type 2 a release; the
  type of every release row is recorded in rows_with_detail.json.
- Prices: DefiLlama /chart hourly series (2 h) for ADA and NIGHT, /batchHistorical at the release hour for other rows
  (2 h), the daily series (36 h) as the last resort; keys coingecko:cardano for ADA and cardano:<policy><asset name>
  for native tokens. Decimals from the Cardano token registry (Koios asset_info), cross-checked with DefiLlama's.
Run: python -I data/legit/collect_legit_E58.py
"""
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
sys.path.insert(0, str(HERE))
import pricing  # noqa: E402
import pricing_points  # noqa: E402

EID = "E58"
RAW = HERE / "raw" / EID
KDIR = RAW / "koios"
KOIOS = "https://api.koios.rest/api/v1"
WINDOW_S = 150 * 86400
LEG = "Cardano treasury"
MIN_ADA_COMPANION = 5_000_000  # lovelace; min-UTXO deposits attached to token outputs are about 1.2 to 1.6 ADA
TXINFO_BATCH = 50


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


def koios(path, body=None, params="", tries=6):
    url = KOIOS + path + params
    data = json.dumps(body).encode() if body is not None else None
    last = None
    for k in range(tries):
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json",
                                                              "Accept": "application/json",
                                                              "User-Agent": "bridge-limits-probe/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.loads(r.read().decode())
        except Exception as e:  # noqa: BLE001  (HTTP 429/5xx, network)
            last = e
            time.sleep(4 * (k + 1))
    raise RuntimeError(f"koios {path}: {last}")


def cached(path, fn):
    if path.exists():
        return json.loads(path.read_text())
    v = fn()
    path.write_text(json.dumps(v))
    return v


def collect(cred, t0, t_fail):
    KDIR.mkdir(parents=True, exist_ok=True)
    b0 = cached(KDIR / "block_start.json", lambda: koios(
        "/blocks", params=f"?block_time=gte.{t0}&order=block_time.asc&limit=1&select=block_height,block_time"))[0]
    bf = cached(KDIR / "block_fail.json", lambda: koios(
        "/blocks", params=f"?block_time=gte.{t_fail}&order=block_time.asc&limit=1&select=block_height,block_time"))[0]
    txs, off = [], 0
    while True:
        page = cached(KDIR / f"credential_txs_{b0['block_height'] - 1}_{off}.json", lambda: koios(
            "/credential_txs", {"_payment_credentials": [cred], "_after_block_height": b0["block_height"] - 1},
            f"?order=block_height.asc&offset={off}&limit=1000"))
        txs += page
        if len(page) < 1000:
            break
        off += 1000
    # the page cache is complete only if it reaches past the failure block
    assert txs and txs[-1]["block_height"] >= bf["block_height"], "credential_txs did not reach the failure block"
    win = sorted({(t["block_height"], t["block_time"], t["tx_hash"]) for t in txs if t0 <= t["block_time"] < t_fail})
    hashes = [h for _, _, h in win]
    info = {}
    for i in range(0, len(hashes), TXINFO_BATCH):
        part = hashes[i:i + TXINFO_BATCH]
        res = cached(KDIR / f"tx_info_{i:05d}.json", lambda: koios(
            "/tx_info", {"_tx_hashes": part, "_inputs": True, "_metadata": True, "_assets": True,
                         "_withdrawals": False, "_certs": False, "_scripts": False, "_bytecode": False}))
        for t in res:
            info[t["tx_hash"]] = t
        print(f"   tx_info {min(i + TXINFO_BATCH, len(hashes))}/{len(hashes)}", flush=True)
    missing = [h for h in hashes if h not in info]
    assert not missing, f"tx_info missing {len(missing)}"
    return b0, bf, win, info


def asset_key(a):
    return a["policy_id"] + (a.get("asset_name") or "")


def flows(tx, cred):
    """Net treasury outflow per asset ('lovelace' or policy+name) and the transaction's receiving outputs."""
    out = collections.Counter()
    in_addrs = set()
    for o in tx["inputs"]:
        pa = o.get("payment_addr") or {}
        if pa.get("cred") == cred:
            out["lovelace"] += int(o["value"])
            for a in o.get("asset_list") or []:
                out[asset_key(a)] += int(a["quantity"])
        else:
            in_addrs.add(pa.get("bech32"))
    recv = []
    for o in tx["outputs"]:
        pa = o.get("payment_addr") or {}
        if pa.get("cred") == cred:
            out["lovelace"] -= int(o["value"])
            for a in o.get("asset_list") or []:
                out[asset_key(a)] -= int(a["quantity"])
        elif pa.get("bech32") not in in_addrs:
            recv.append({"addr": pa.get("bech32"), "cred": pa.get("cred"), "lovelace": int(o["value"]),
                         "assets": {asset_key(a): int(a["quantity"]) for a in o.get("asset_list") or []}})
    return dict(out), recv, in_addrs


def is_script_addr(bech32):
    # Shelley header types 1, 3, 5, 7 have a script payment part: bech32 prefixes addr1z, addr1x, addr1w
    return bool(bech32) and bech32[:6] in ("addr1z", "addr1x", "addr1w")


def meta_type(tx):
    m = tx.get("metadata") or {}
    v = m.get("1") if isinstance(m, dict) else None
    if isinstance(v, dict):
        return v.get("type"), v.get("tokenPairID")
    return None, None


def main():
    targets = json.loads((HERE / "targets" / f"{EID}.json").read_text())
    cred = targets["treasury_payment_credential"]
    fail_to = set(targets.get("failure_recipients", []))
    t_fail = failure_time(EID)
    t0, t1 = t_fail - WINDOW_S, t_fail - 1
    b0, bf, win, info = collect(cred, t0, t_fail)
    print(f"== {EID}: blocks {b0['block_height']}-{bf['block_height'] - 1}, transactions {len(win)}", flush=True)
    tx_rows, cat = [], collections.Counter()
    excluded = collections.Counter()
    companion = {"n": 0, "lovelace": 0}
    script_only = []
    fee_from_treasury = 0
    pend, fail_detail = [], []
    for blk, bt, h in win:
        tx = info[h]
        net, recv, in_addrs = flows(tx, cred)
        mt, pair = meta_type(tx)
        ts = int(tx["tx_timestamp"])
        outs = {k: v for k, v in net.items() if v > 0}
        ins = {k: -v for k, v in net.items() if v < 0}
        tok_out = {k: v for k, v in outs.items() if k != "lovelace"}
        if not outs:
            cat["no net outflow (deposit or treasury-only)" if ins else "no net flow"] += 1
            tx_rows.append({"tx": h, "ts": ts, "type": mt, "pair": pair, "net": net, "class": "inflow"})
            continue
        # the treasury paid part of the fee if the outflow exceeds what the receiving outputs hold
        recv_tot = collections.Counter()
        for o in recv:
            recv_tot["lovelace"] += o["lovelace"]
            for k, v in o["assets"].items():
                recv_tot[k] += v
        short = {k: v - recv_tot.get(k, 0) for k, v in outs.items() if v > recv_tot.get(k, 0)}
        if short:
            fee_from_treasury += 1
        non_script = [o for o in recv if not is_script_addr(o["addr"])]
        if not non_script:
            script_only.append({"tx": h, "ts": iso(ts), "type": mt, "outs": outs,
                                "to": [o["addr"] for o in recv]})
            cat["outflow to script addresses only"] += 1
            tx_rows.append({"tx": h, "ts": ts, "type": mt, "pair": pair, "net": net, "class": "script_only"})
            continue
        to_fail = any(o["addr"] in fail_to for o in recv)
        cat[f"release (metadata type {mt})"] += 1
        tx_rows.append({"tx": h, "ts": ts, "type": mt, "pair": pair, "net": net, "class": "release",
                        "recipients": [o["addr"] for o in recv], "short": short})
        for k, v in outs.items():
            if k == "lovelace" and tok_out and v <= MIN_ADA_COMPANION:
                companion["n"] += 1
                companion["lovelace"] += v
                companion.setdefault("ts", []).append(ts)
                continue
            if to_fail:
                excluded["to the recipient of the failure"] += 1
                fail_detail.append({"ts": iso(ts), "asset_key": k, "raw": v})
                continue
            pend.append({"ts": ts, "tx": h, "asset_key": k, "raw": v, "type": mt, "pair": pair,
                         "n_recipients": len(recv), "to": [o["addr"] for o in recv]})
    (RAW / "tx_flows.json").write_text(json.dumps(tx_rows))
    (RAW / "script_only_outflows.json").write_text(json.dumps(script_only, indent=1))
    # asset metadata: token registry decimals (Koios asset_info) and DefiLlama keys
    keys = sorted({p["asset_key"] for p in pend if p["asset_key"] != "lovelace"})
    ai = cached(KDIR / "asset_info.json", lambda: koios(
        "/asset_info", {"_asset_list": [[k[:56], k[56:]] for k in keys]}) if keys else [])
    meta = {}
    for a in ai:
        k = a["policy_id"] + (a.get("asset_name") or "")
        reg = a.get("token_registry_metadata") or {}
        name = a.get("asset_name_ascii") or ""
        meta[k] = {"decimals": reg.get("decimals"), "ticker": reg.get("ticker"), "name_ascii": name}
    (KDIR / "asset_meta.json").write_text(json.dumps(meta, indent=1))
    rows = []
    for p in pend:
        k = p["asset_key"]
        if k == "lovelace":
            sym, dec, cid, kind = "ADA", 6, "coingecko:cardano", "native"
        else:
            m = meta.get(k, {})
            dec = m.get("decimals") if m.get("decimals") is not None else 0
            sym = m.get("ticker") or m.get("name_ascii") or k[56:] or "?"
            cid, kind = f"cardano:{k}", "erc20"
        rows.append({"ts": p["ts"], "leg": LEG, "asset": sym, "asset_key": k, "cid": cid, "decimals": dec,
                     "amount": p["raw"] / 10 ** dec, "raw": str(p["raw"]), "kind": kind, "type": p["type"],
                     "pair": p["pair"], "n_recipients": p["n_recipients"], "tx": p["tx"]})
    fallback = {k: v for k, v in targets.get("price_fallback", {}).items() if not k.startswith("_")}
    pinfo = price_rows(rows, RAW / "prices", t0, t1, fallback)
    rows.sort(key=lambda r: (r["ts"], r["asset"]))
    with (HERE / f"{EID}.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["ts_utc", "leg", "asset", "amount", "usd", "kind", "priced"])
        for r in rows:
            w.writerow([iso(r["ts"]), r["leg"], r["asset"], f"{r['amount']:.10g}",
                        "" if r["usd"] is None else f"{r['usd']:.2f}", r["kind"], "yes" if r["usd"] is not None else "no"])
    (RAW / "rows_with_detail.json").write_text(json.dumps(rows))
    ada_px = [r["usd"] / r["amount"] for r in rows if r["asset"] == "ADA" and r["usd"] and r["amount"]]
    s = {"id": EID, "t_fail_utc": iso(t_fail), "window_utc": [iso(t0), iso(t1)],
         "blocks": [b0["block_height"], bf["block_height"] - 1], "block_time_first": iso(b0["block_time"]),
         "n_transactions": len(win), "tx_categories": dict(cat), "excluded": dict(excluded),
         "excluded_failure_recipient_detail": fail_detail,
         "min_ada_companions": {"n": companion["n"], "ada": companion["lovelace"] / 1e6,
                                "usd_at_median_ada_price": (companion["lovelace"] / 1e6) * (sorted(ada_px)[len(ada_px) // 2]
                                                                                            if ada_px else float("nan"))},
         "releases_where_recipients_hold_less_than_net_outflow": fee_from_treasury,
         "script_only_outflows": len(script_only), "assets_meta": meta, "pricing": pinfo,
         "release_metadata_types": dict(collections.Counter(str(r["type"]) for r in rows))}
    s.update(summarize(rows, t0, t1))
    (RAW / "summary.json").write_text(json.dumps(s, indent=1, default=str))
    print(json.dumps({k: s[k] for k in ("n_transactions", "tx_categories", "excluded", "min_ada_companions", "n_rows",
                                        "n_priced", "usd_total_priced", "largest_release", "busiest_hour_usd",
                                        "busiest_day_usd", "release_metadata_types")}, indent=1, default=str))


def price_rows(rows, pdir, t0, t1, fallback):
    """Ladder per row: hourly chart (assets with 50+ releases), batchHistorical at the release hour, daily chart;
    first under the asset's own key, then under the fallback key of the same token (targets.json price_fallback)."""
    coins = sorted({r["cid"] for r in rows})
    n_rel = collections.Counter(r["cid"] for r in rows)
    alt = sorted({fallback[c] for c in coins if c in fallback})
    daily = {c: pricing.chart(c, t0, t1, "1d", pdir, search_width=43200) for c in coins + alt}
    hourly = {c: pricing.chart(c, t0, t1, "1h", pdir, search_width=1800) for c in coins if n_rel[c] >= 50}
    for r in rows:
        r["usd"], r["src"] = None, ""
    for tag, key in (("", lambda r: r["cid"]), (" (CoinGecko id of the same token)", lambda r: fallback.get(r["cid"]))):
        todo = [r for r in rows if r["usd"] is None and key(r) is not None]
        for r in todo:
            p = pricing.nearest(hourly.get(key(r), []), r["ts"], 2 * 3600)
            if p is not None:
                r["usd"], r["src"] = r["amount"] * p, "defillama chart 1h" + tag
        miss = [r for r in todo if r["usd"] is None]
        tab = pricing_points.lookup([(key(r), r["ts"]) for r in miss], pdir)
        for r in miss:
            p = pricing_points.price(tab, key(r), r["ts"])
            if p is not None:
                r["usd"], r["src"] = r["amount"] * p, "defillama batchHistorical (release hour)" + tag
                continue
            p = pricing.nearest(daily.get(key(r), []), r["ts"], 36 * 3600)
            if p is not None:
                r["usd"], r["src"] = r["amount"] * p, "defillama chart 1d" + tag
    # decimals reported by DefiLlama for the token keys (cross-check of the registry decimals)
    dl_dec = {}
    for c in coins:
        if c.startswith("cardano:"):
            j = pricing_points._get(f"https://coins.llama.fi/prices/current/{c}?searchWidth=4w")
            dl_dec[c] = (j.get("coins") or {}).get(c, {}).get("decimals")
            time.sleep(0.3)
    return {"coins": coins, "hourly_series": sorted(hourly), "defillama_decimals": dl_dec,
            "registry_decimals": {r["cid"]: r["decimals"] for r in rows}}


def summarize(rows, t0, t1):
    import numpy as np
    pr = [r for r in rows if r["usd"] is not None]
    hour, day, hour_n, day_n = (collections.defaultdict(float), collections.defaultdict(float),
                                collections.Counter(), collections.Counter())
    for r in rows:
        h, d = r["ts"] - r["ts"] % 3600, r["ts"] - r["ts"] % 86400
        hour_n[h] += 1
        day_n[d] += 1
        if r["usd"] is not None:
            hour[h] += r["usd"]
            day[d] += r["usd"]
    d_first = t0 - t0 % 86400
    days_all = [d_first + 86400 * i for i in range(int((t1 - d_first) // 86400) + 1)]
    dv = np.array([day.get(d, 0.0) for d in days_all])
    uv = np.array([r["usd"] for r in pr]) if pr else np.array([0.0])
    tl = sorted(r["ts"] for r in rows)
    gaps = sorted(((b - a, iso(a), iso(b)) for a, b in zip([t0] + tl, tl + [t1])), reverse=True)[:8]
    big = max(pr, key=lambda r: r["usd"]) if pr else None
    by_asset = collections.defaultdict(lambda: [0, 0.0, 0.0, 0])
    for r in rows:
        a = by_asset[r["asset"]]
        a[0] += 1
        a[1] += r["amount"]
        a[2] += r["usd"] or 0.0
        a[3] += r["usd"] is not None
    month = collections.defaultdict(lambda: [0, 0.0])
    for r in rows:
        m = iso(r["ts"])[:7]
        month[m][0] += 1
        month[m][1] += r["usd"] or 0.0
    return {
        "n_rows": len(rows), "n_priced": len(pr), "share_priced_count": len(pr) / len(rows) if rows else None,
        "usd_total_priced": float(uv.sum()) if pr else 0.0,
        "by_kind": dict(collections.Counter(r["kind"] for r in rows)),
        "price_sources": dict(collections.Counter(r["src"] or "unpriced" for r in rows)),
        "first": iso(tl[0]) if tl else None, "last": iso(tl[-1]) if tl else None,
        "days_with_release": len(day_n), "calendar_days": len(days_all),
        "release_usd_quantiles": {q: float(np.quantile(uv, q)) for q in (0.5, 0.9, 0.99)},
        "daily_usd_quantiles": {q: float(np.quantile(dv, q)) for q in (0.5, 0.9, 1.0)},
        "daily_usd_mean_150d": (float(uv.sum()) / 150) if pr else 0.0,
        "largest_release": None if big is None else {"ts": iso(big["ts"]), "asset": big["asset"],
                                                     "amount": big["amount"], "usd": big["usd"]},
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
                            for k, v in by_asset.items()], key=lambda x: (-x["usd"], -x["n"])),
        "by_month": {k: {"n": v[0], "usd": v[1]} for k, v in sorted(month.items())},
    }


if __name__ == "__main__":
    main()
