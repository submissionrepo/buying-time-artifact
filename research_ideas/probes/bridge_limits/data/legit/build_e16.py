"""Build data/legit/E16.csv (BSC Token Hub releases, 150 days before the first unauthorized release).

Reads the cached chunks written by collect_e16.py and writes:
  E16.csv            ts_utc, leg, asset, amount, usd, kind, priced (no addresses, no hashes)
  E16_prices.csv     price source per asset (coin id kind, granularity, releases priced)
  raw/E16/stats.json totals and checks used in E16_README.md (no addresses)
  raw/E16/assets.json token address -> label map (raw cache, stays under raw/)
Run: python -I build_e16.py
"""
import collections
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

RAW = HERE / "raw" / "E16"
T = json.loads((HERE.parent / "incidents" / "onchain_targets.json").read_text())["E16_bsc"]
HUB = T["hub"].lower()
TOPIC = {
    "0x471eb9cc1ffe55ffadf15b32595415eb9d80f22e761d24bd6dffc607e1284d59": "transferInSuccess",
    "0xd468d4fa5e8fb4adc119b29a983fd0785e04af5cb8b7a3a69a47270c54b6901a": "refundSuccess",
    "0x203f9f67a785f4f81be4d48b109aa0c498d1bc8097ecc2627063f480cc5fe73e": "refundFailure",
    "0xf8b71c64315fc33b2ead2adfa487955065152a8ac33d9d5193aafd7f45dc15a0": "rewardTo",
    "0x74eab09b0e53aefc23f2e1b16da593f95c2dd49c6f5a23720463d10d9c330b2a": "transferOutSuccess",
    "0x6c98249d85d88c3753a04a22230f595e4dc8d3dc86c34af35deeeedc861b89db": "receiveDeposit",
}
ZERO = "0x" + "0" * 40
# DefiLlama has no series under the contract key for these 1:1 pegged tokens (checked 2026-10-16); they are
# valued at the underlying asset's series. Contracts matched in full, not by symbol.
CG_ALIAS = {"0x2170ed0880ac9a755fd29b2688956bd959f933f8": "coingecko:ethereum",
            "0x1af3f329e8be154074d8769d1ffa4ee058b1dbc3": "coingecko:dai",
            "0xe9e7cea3dedca5984780bafc599bd69add087d56": "coingecko:binance-usd",
            "0x55d398326f99059ff775485246999027b3197955": "coingecko:tether",
            "0x8ac76a51cc950d9822d68b83fe1ad97b32cd580d": "coingecko:usd-coin"}
# symbol() of this contract did not answer through the archive endpoint on 2026-10-16
SYMBOL_FIX = {"0xe9e7cea3dedca5984780bafc599bd69add087d56": "BUSD"}
SYSTEM = {"0x" + "0" * 36 + s for s in ("1000", "1001", "1002", "1003", "1004", "1005", "1006", "1007",
                                         "1008", "2000", "2001", "2002", "2003", "2004", "2005")}


def iso(ts):
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def words(data):
    d = data[2:]
    return [int(d[i:i + 64], 16) for i in range(0, len(d), 64)]


def w2a(w):
    return "0x" + format(w, "040x")


def main():
    meta = json.loads((RAW / "window.json").read_text())
    chunks = sorted(RAW.glob("chunk_*.json.gz"), key=lambda p: int(p.name.split("_")[1]))
    cov, hub, trf = [], [], []
    for p in chunks:
        with gzip.open(p, "rt") as fh:
            c = json.load(fh)
        cov.append((c["b0"], c["b1"]))
        hub += c["hub"]
        trf += c["transfer"]
    gaps = []
    expect = meta["b0"]
    for a, b in cov:
        if a != expect:
            gaps.append([expect, a - 1])
        expect = b + 1
    if expect <= meta["b1"]:
        gaps.append([expect, meta["b1"]])

    # failure recipient (raw cache) to make sure no earlier row belongs to the failure
    fr = RAW / "failure_logs.json"
    if not fr.exists():
        r = Rpc("bsc")
        lg = r.logs(HUB, [list(TOPIC)[0]], meta["b1"] + 1, meta["b1"] + 1, step=1)
        fr.write_text(json.dumps(lg))
    flogs = json.loads(fr.read_text())
    bad_recip = {w2a(words(l["data"])[1]) for l in flogs if words(l["data"])[2] == T["amount_wei"]}

    tally = collections.Counter()
    sums = collections.defaultdict(int)
    rows = []
    ev_token_keys = collections.Counter()  # (tx, token, to, amount) from hub events for BEP20
    for l in hub:
        name = TOPIC.get(l["topics"][0], "other:" + l["topics"][0][:10])
        tally[name] += 1
        w = words(l["data"])
        ts = int(l["blockTimestamp"], 16)
        if name in ("transferInSuccess", "refundSuccess"):
            tok, to, amt = w2a(w[0]), w2a(w[1]), w[2]
            if tok == ZERO:
                sums[name + "_bnb_wei"] += amt
                if to in bad_recip:
                    tally["excluded_failure_recipient"] += 1
                    continue
                rows.append({"ts": ts, "leg": "hub transfer-in" if name == "transferInSuccess" else "hub refund",
                             "token": "native", "raw": amt, "kind": "event", "blk": int(l["blockNumber"], 16)})
            else:
                tally[name + "_bep20"] += 1
                ev_token_keys[(l["transactionHash"], tok, to, amt)] += 1
                ev_token_keys[("leg", l["transactionHash"], tok, to, amt)] = name
        elif name == "rewardTo":
            sums["rewardTo_wei"] += w[1]
        elif name == "transferOutSuccess":
            tok = w2a(w[0])
            if tok == ZERO:
                sums["transferOut_bnb_amount_wei"] += w[2]
            sums["transferOut_relayfee_wei"] += w[3]
        elif name == "receiveDeposit":
            sums["receiveDeposit_wei"] += w[1]
        elif name == "refundFailure":
            pass

    excl = collections.Counter()
    unmatched = 0
    unmatched_tok = collections.Counter()
    ev_tokens = {k[1] for k in ev_token_keys if k[0] != "leg"}
    for l in trf:
        if len(l["topics"]) != 3:
            excl["not_erc20_shape"] += 1
            continue
        to = "0x" + l["topics"][2][-40:]
        tok = l["address"].lower()
        amt = int(l["data"], 16) if l["data"] not in ("0x", "") else 0
        if to == HUB or to == ZERO or to in SYSTEM:
            excl["to_hub_zero_or_system"] += 1
            continue
        if to in bad_recip:
            excl["to_failure_recipient"] += 1
            continue
        key = (l["transactionHash"], tok, to, amt)
        if ev_token_keys.get(key, 0) > 0:
            ev_token_keys[key] -= 1
            leg = "hub transfer-in" if ev_token_keys[("leg",) + key] == "transferInSuccess" else "hub refund"
        else:
            # every BEP20 release by the hub emits transferInSuccess or refundSuccess in the same
            # transaction; a Transfer log naming the hub as sender without one is emitted by the token
            # contract itself (mass airdrop logs) and moves nothing out of the hub's custody
            unmatched += 1
            unmatched_tok["bound" if tok in ev_tokens else "never_in_hub_events"] += 1
            continue
        rows.append({"ts": int(l["blockTimestamp"], 16), "leg": leg, "token": tok, "raw": amt, "kind": "erc20",
                     "blk": int(l["blockNumber"], 16)})
    events_without_transfer = sum(v for k, v in ev_token_keys.items() if k[0] != "leg" and isinstance(v, int) and v > 0)

    # token metadata
    r = Rpc("bsc")
    r.urls = r.urls[:1]  # the fallback endpoint has a daily quota and no archive state
    ap = RAW / "assets.json"
    assets = json.loads(ap.read_text()) if ap.exists() else {}
    cache = {}
    for tok in sorted({x["token"] for x in rows if x["token"] != "native"}):
        if tok not in assets:
            sym, dec = erc20_meta(r, tok, cache)
            assets[tok] = {"symbol": sym, "decimals": dec}
    for tok, sym in SYMBOL_FIX.items():
        if tok in assets:
            assets[tok]["symbol"] = sym
    labels = {}
    seen = collections.Counter()
    for tok in sorted(assets, key=lambda t: t):
        s = assets[tok]["symbol"] or "?"
        seen[s] += 1
        labels[tok] = s if seen[s] == 1 else f"{s}#{seen[s]}"
        assets[tok]["label"] = labels[tok]
    labels["native"] = "BNB"
    ap.write_text(json.dumps(assets, indent=1))
    for x in rows:
        dec = 18 if x["token"] == "native" else assets[x["token"]]["decimals"]
        x["amount"] = x["raw"] / 10 ** dec
        x["asset"] = labels[x["token"]]

    # prices: daily for every asset, hourly for assets above 1M USD on the daily pass
    t0, t1 = meta["t_start"], meta["t_end"]
    pdir = RAW / "prices"
    coin = {tok: ("coingecko:binancecoin" if tok == "native" else CG_ALIAS.get(tok, f"bsc:{tok}"))
            for tok in {x["token"] for x in rows}}
    daily = {tok: pricing.chart(c, t0, t1, "1d", pdir) for tok, c in coin.items()}
    vol = collections.defaultdict(float)
    for x in rows:
        p = pricing.nearest(daily[x["token"]], x["ts"], 36 * 3600)
        if p is not None:
            vol[x["token"]] += x["amount"] * p
    hourly = {tok: pricing.chart(coin[tok], t0, t1, "1h", pdir) for tok in coin if vol[tok] >= 1e6}
    psrc = collections.defaultdict(lambda: collections.Counter())
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
    import csv
    with open(HERE / "E16.csv", "w", newline="", encoding="utf-8") as f:
        wr = csv.writer(f)
        wr.writerow(["ts_utc", "leg", "asset", "amount", "usd", "kind", "priced"])
        for x in rows:
            wr.writerow([iso(x["ts"]), x["leg"], x["asset"], repr(x["amount"]),
                         "" if x["usd"] is None else f"{x['usd']:.2f}", x["kind"],
                         "yes" if x["usd"] is not None else "no"])
    with open(HERE / "E16_prices.csv", "w", newline="", encoding="utf-8") as f:
        wr = csv.writer(f)
        wr.writerow(["asset", "price_source", "releases_1h", "releases_1d", "releases_point", "releases_unpriced",
                     "usd_priced"])
        for tok in sorted(coin, key=lambda t: -vol[t]):
            key = coin[tok] if coin[tok].startswith("coingecko:") else "bsc:<token contract>"
            src = "DefiLlama coins chart (1h/1d) + batchHistorical (point) " + key
            usd = sum(x["usd"] for x in rows if x["token"] == tok and x["usd"] is not None)
            wr.writerow([labels[tok], src, psrc[tok]["1h"], psrc[tok]["1d"], psrc[tok]["point"],
                         psrc[tok]["unpriced"], f"{usd:.2f}"])

    # balance reconciliation of BNB held by the hub
    bal0 = r.balance(HUB, meta["b0"] - 1)
    bal1 = r.balance(HUB, meta["b1"])
    inflow = sums["transferOut_bnb_amount_wei"] + sums["transferOut_relayfee_wei"] + sums["receiveDeposit_wei"]
    outflow = sums["transferInSuccess_bnb_wei"] + sums["refundSuccess_bnb_wei"] + sums["rewardTo_wei"]
    stats = {"window": meta, "gaps_blocks": gaps, "n_chunks": len(cov), "hub_event_counts": dict(tally),
             "transfer_exclusions": dict(excl), "bep20_transfers_without_hub_event_excluded": unmatched,
             "bep20_transfers_without_hub_event_by_token_class": dict(unmatched_tok),
             "bep20_hub_events_without_transfer": events_without_transfer,
             "failure_recipient_rows_excluded": tally["excluded_failure_recipient"] + excl["to_failure_recipient"],
             "sums_bnb": {k: v / 1e18 for k, v in sums.items()},
             "bnb_reconciliation": {"balance_start": bal0 / 1e18, "balance_end": bal1 / 1e18,
                                    "inflow_events": inflow / 1e18, "outflow_events": outflow / 1e18,
                                    "residual_unexplained": (bal1 - bal0 - inflow + outflow) / 1e18},
             "n_rows": len(rows)}
    (RAW / "stats.json").write_text(json.dumps(stats, indent=1))
    print(json.dumps(stats, indent=1))


if __name__ == "__main__":
    main()
