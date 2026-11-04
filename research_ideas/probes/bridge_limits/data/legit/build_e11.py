"""Build data/legit/E11.csv (Ethereum escrow leg of the token bridge, 150 days before the first unauthorized release).

Reads raw/E11/chunk_*.json (collect_e11.py) and raw/E11/traces/*.json.gz (collect_e11_traces.py); writes
  E11.csv            ts_utc, leg, asset, amount, usd, kind, priced (no addresses, no hashes)
  E11_prices.csv     price source per asset
  raw/E11/stats.json totals and checks used in E11_README.md (no addresses)
  raw/E11/assets.json token address -> label map (raw cache)
Rows:
  erc20  Transfer logs with the bridge as sender, excluding transfers to the bridge itself and to the zero
         address (burns of wrapped assets on outbound transfers, which are not releases).
  native ETH paid out by completeTransferAndUnwrapETH, one row per WETH Withdrawal log with the bridge as
         src (the bridge unwraps exactly the amount it then sends). Checked transaction by transaction
         against the trace_filter payouts.
Run: python -I build_e11.py
"""
import collections
import csv
import datetime
import gzip
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent / "incidents"))
sys.path.insert(0, str(HERE))
from rpc import Rpc, erc20_meta  # noqa: E402
import pricing  # noqa: E402
import pricing_points  # noqa: E402

RAW = HERE / "raw" / "E11"
T = json.loads((HERE.parent / "incidents" / "onchain_targets.json").read_text())["E11_eth"]
BRIDGE = T["custody"][0].lower()
BAD = {a.lower() for a in T.get("recipients", [])}
WETH = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"
ZERO = "0x" + "0" * 40
# DefiLlama has no series under the contract key for these canonical contracts but has one under the
# CoinGecko id (checked 2026-10-16); the contracts were matched in full, not by symbol
CG_ALIAS = {"0x7d1afa7b718fb893db30a3abc0cfc608aacfebb0": "coingecko:matic-network",
            "0x1c48f86ae57291f7686349f12601910bd8d470bb": "coingecko:usdk",
            "0xc4e15973e6ff2a35cc804c2cf9d2a1b817a8b40f": "coingecko:interest-bearing-bitcoin"}
DUST = 10 ** 10  # normalisation to 8 decimals leaves at most 1e10 - 1 wei of dust


def iso(ts):
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main():
    meta = json.loads((RAW / "window.json").read_text())
    chunks = sorted(RAW.glob("chunk_*.json"), key=lambda p: int(p.name.split("_")[1]))
    cov, trf, wd = [], [], []
    for p in chunks:
        c = json.loads(p.read_text())
        cov.append((c["b0"], c["b1"]))
        trf += c["transfer"]
        wd += c["withdrawal"]

    def gaps_of(cv):
        g, expect = [], meta["b0"]
        for a, b in sorted(cv):
            if a != expect:
                g.append([expect, a - 1])
            expect = b + 1
        if expect <= meta["b1"]:
            g.append([expect, meta["b1"]])
        return g

    gaps = gaps_of(cov)
    rows, excl = [], collections.Counter()
    first_block = None
    for l in trf:
        if len(l["topics"]) != 3:
            excl["not_erc20_shape"] += 1
            continue
        to = "0x" + l["topics"][2][-40:]
        if to == BRIDGE:
            excl["to_bridge"] += 1
            continue
        if to == ZERO:
            excl["burn_to_zero"] += 1
            continue
        if to in BAD:
            excl["to_failure_recipient"] += 1
            continue
        blk = int(l["blockNumber"], 16)
        rows.append({"ts": int(l["blockTimestamp"], 16), "blk": blk, "tx": l["transactionHash"],
                     "token": l["address"].lower(), "raw": int(l["data"], 16) if l["data"] not in ("0x", "") else 0,
                     "kind": "erc20"})
    wd_by_tx = collections.defaultdict(int)
    for l in wd:
        blk = int(l["blockNumber"], 16)
        v = int(l["data"], 16)
        wd_by_tx[l["transactionHash"]] += v
        rows.append({"ts": int(l["blockTimestamp"], 16), "blk": blk, "tx": l["transactionHash"], "token": "native",
                     "raw": v, "kind": "native"})

    # trace check of native payouts
    tr_files = sorted((RAW / "traces").glob("traces_*.json.gz"), key=lambda p: int(p.name.split("_")[1]))
    tcov, pay_by_tx, pay_to = [], collections.defaultdict(int), collections.defaultdict(set)
    deposits = 0
    for p in tr_files:
        with gzip.open(p, "rt") as fh:
            c = json.load(fh)
        tcov.append((c["b0"], c["b1"]))
        for x in c["calls"]:
            if x.get("error"):
                continue
            to = (x["to"] or "").lower()
            if to == WETH:
                deposits += int(x["value"])
                continue
            if to == BRIDGE:
                continue
            pay_by_tx[x["tx"]] += int(x["value"])
            pay_to[x["tx"]].add(to)
    tgaps = gaps_of(tcov) if tcov else [[meta["b0"], meta["b1"]]]
    covered = lambda blk: any(a <= blk <= b for a, b in tcov)  # noqa: E731
    tx_blk = {r["tx"]: r["blk"] for r in rows}
    chk = collections.Counter()
    trace_only = []
    for txh, v in pay_by_tx.items():
        w = wd_by_tx.get(txh, 0)
        if w == v:
            chk["tx_payout_equals_withdrawal"] += 1
        elif w == 0 and v < DUST:
            chk["tx_dust_refund_only"] += 1
            chk["dust_wei"] += v
        elif w == 0:
            chk["tx_payout_without_withdrawal"] += 1
            trace_only.append(txh)
        else:
            chk["tx_payout_differs_from_withdrawal"] += 1
    for txh, w in wd_by_tx.items():
        if txh not in pay_by_tx and covered(tx_blk.get(txh, -1)):
            chk["tx_withdrawal_without_traced_payout"] += 1
    chk["weth_deposit_wei_by_bridge"] = deposits

    # token metadata
    r = Rpc("ethereum")
    ap = RAW / "assets.json"
    assets = json.loads(ap.read_text()) if ap.exists() else {}
    cache = {}
    for tok in sorted({x["token"] for x in rows if x["token"] != "native"}):
        if tok not in assets:
            sym, dec = erc20_meta(r, tok, cache)
            assets[tok] = {"symbol": sym, "decimals": dec}
    seen = collections.Counter()
    labels = {"native": "ETH"}
    for tok in sorted(assets):
        s = assets[tok]["symbol"] or "?"
        seen[s] += 1
        labels[tok] = s if seen[s] == 1 else f"{s}#{seen[s]}"
        assets[tok]["label"] = labels[tok]
    ap.write_text(json.dumps(assets, indent=1))
    for x in rows:
        dec = 18 if x["token"] == "native" else assets[x["token"]]["decimals"]
        x["amount"] = x["raw"] / 10 ** dec
        x["asset"] = labels[x["token"]]
        x["leg"] = "token bridge escrow (Ethereum)"

    t0, t1 = meta["t_start"], meta["t_end"]
    pdir = RAW / "prices"
    coin = {tok: ("coingecko:ethereum" if tok == "native" else CG_ALIAS.get(tok, f"ethereum:{tok}"))
            for tok in {x["token"] for x in rows}}
    daily = {tok: pricing.chart(c, t0, t1, "1d", pdir) for tok, c in coin.items()}
    vol = collections.defaultdict(float)
    for x in rows:
        p = pricing.nearest(daily[x["token"]], x["ts"], 36 * 3600)
        if p is not None:
            vol[x["token"]] += x["amount"] * p
    hourly = {tok: pricing.chart(coin[tok], t0, t1, "1h", pdir) for tok in coin if vol[tok] >= 1e6}
    psrc = collections.defaultdict(collections.Counter)
    for x in rows:
        p = pricing.nearest(hourly[x["token"]], x["ts"], 2 * 3600) if x["token"] in hourly else None
        x["usd"], x["g"] = (x["amount"] * p, "1h") if p is not None else (None, None)
    # point prices (batchHistorical, middle of the release hour, 2 h tolerance) where the hourly chart is
    # missing or sparse; the daily chart (36 h tolerance) only as the last resort
    miss = [x for x in rows if x["usd"] is None]
    tab = pricing_points.lookup([(coin[x["token"]], x["ts"]) for x in miss], pdir)
    for x in miss:
        p = pricing_points.price(tab, coin[x["token"]], x["ts"])
        if p is not None:
            x["usd"], x["g"] = x["amount"] * p, "point"
            continue
        p = pricing.nearest(daily[x["token"]], x["ts"], 36 * 3600)
        if p is not None:
            x["usd"], x["g"] = x["amount"] * p, "1d"
    for x in rows:
        psrc[x["token"]][x["g"] or "unpriced"] += 1
    rows.sort(key=lambda x: (x["ts"], x["blk"]))
    with open(HERE / "E11.csv", "w", newline="", encoding="utf-8") as f:
        wr = csv.writer(f)
        wr.writerow(["ts_utc", "leg", "asset", "amount", "usd", "kind", "priced"])
        for x in rows:
            wr.writerow([iso(x["ts"]), x["leg"], x["asset"], repr(x["amount"]),
                         "" if x["usd"] is None else f"{x['usd']:.2f}", x["kind"],
                         "yes" if x["usd"] is not None else "no"])
    with open(HERE / "E11_prices.csv", "w", newline="", encoding="utf-8") as f:
        wr = csv.writer(f)
        wr.writerow(["asset", "price_source", "releases_1h", "releases_1d", "releases_point", "releases_unpriced",
                     "usd_priced"])
        for tok in sorted(coin, key=lambda t: -vol[t]):
            key = coin[tok] if coin[tok].startswith("coingecko:") else "ethereum:<token contract>"
            src = "DefiLlama coins chart (1h/1d) + batchHistorical (point) " + key
            usd = sum(x["usd"] for x in rows if x["token"] == tok and x["usd"] is not None)
            wr.writerow([labels[tok], src, psrc[tok]["1h"], psrc[tok]["1d"], psrc[tok]["point"],
                         psrc[tok]["unpriced"], f"{usd:.2f}"])
    first_act = min((x["ts"] for x in rows), default=None)
    stats = {"window": meta, "gaps_blocks": gaps, "trace_gaps_blocks": tgaps, "n_chunks": len(cov),
             "transfer_exclusions": dict(excl), "native_trace_check": dict(chk),
             "n_trace_only_payout_tx": len(trace_only), "n_rows": len(rows),
             "first_release_in_window": iso(first_act) if first_act else None,
             "n_tx": len({x["tx"] for x in rows})}
    (RAW / "stats.json").write_text(json.dumps(stats, indent=1))
    print(json.dumps(stats, indent=1))


if __name__ == "__main__":
    main()
