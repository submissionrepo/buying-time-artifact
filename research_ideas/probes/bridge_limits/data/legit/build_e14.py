"""E14 (Horizon bridge managers): legitimate release series over the 150 days before the failure.

usage: python -I build_e14.py
Inputs (raw caches in raw/E14/, addresses never printed):
  custody0_*  ERC20 manager (escrow), Ethereum      custody1_*  ETH manager (escrow), Ethereum
  busd_eth_*  BUSD manager (escrow), Ethereum        busd_bsc_*  BUSD manager (escrow), BSC
  other_<chain>_<k>_*  further escrow managers found among the bridge multisig's executions
                       (fetch_e14_other.py), when present
Every manager emits Unlocked(address ethToken, uint256 amount, address recipient, bytes32 receiptId) on
release. An ERC-20 Transfer out of a manager is a release when the same transaction carries an Unlocked
event for the same token and amount. Native releases (ETH manager, and a native-coin manager on BSC if one
was found) are taken from the Unlocked event whose token field is the native placeholder (kind "event");
the managers' only native outflow path is that unlock function, which emits the event.
Outputs: E14.csv, raw/E14/rows_full.json, raw/E14/process_summary.json
"""
import csv
import json
import pathlib
import sys
from collections import Counter, defaultdict

BL = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BL / "incidents"))
sys.path.insert(0, str(BL / "data/legit"))
from rpc import Rpc, addr_from_topic, erc20_meta  # noqa: E402
from process_e15 import hourly_prices, daily_prices, nearest, words, iso, to_ts  # noqa: E402
from fetch_e14_extra import refs  # noqa: E402

UNLOCKED = "0xb24e65d2501e29a3ce014b0cc2283699c081ad27f10d64f036f96912b6f8943e"
NATIVE = {"0x00" + "e" * 38, "0x" + "e" * 40}  # source placeholder; the deployed ETH manager emits the latter
ZERO = "0x" + "0" * 40
RAW = BL / "data/legit/raw/E14"
ETH_B = (14067979, 15012645)
BSC_B = (14643287, 18937748)
T = to_ts("2022-06-23T11:06:46")
LO, HI = T - 150 * 86400, T - 1
# Binance-Peg tokens on BSC (1:1 custodial pegs of the named asset). DefiLlama keeps no historical series
# under their BSC contract keys, so they are priced from the underlying asset's series; the symbol read
# on chain must agree, otherwise the token stays unpriced.
PEG = {"0xe9e7cea3dedca5984780bafc599bd69add087d56": ("BUSD", "coingecko:binance-usd"),
       "0x8ac76a51cc950d9822d68b83fe1ad97b32cd580d": ("USDC", "coingecko:usd-coin"),
       "0x55d398326f99059ff775485246999027b3197955": ("USDT", "coingecko:tether"),
       "0x2170ed0880ac9a755fd29b2688956bd959f933f8": ("ETH", "coingecko:ethereum"),
       "0x1af3f329e8be154074d8769d1ffa4ee058b1dbc3": ("DAI", "coingecko:dai"),
       "0xcc42724c6683b7e57334c4e856f4c9965ed682bd": ("MATIC", "coingecko:matic-network"),
       "0x3d6545b08693dae087e957cb1180ee38b9e3c25e": ("ETC", "coingecko:ethereum-classic"),
       "0x7130d2a12b9bcbfae4f2634d864a1ee1ce3ead9c": ("BTCB", "coingecko:bitcoin")}
NATIVE_COIN = {"ethereum": ("coingecko:ethereum", "ETH"), "bsc": ("coingecko:binancecoin", "BNB")}


def legs():
    t = json.loads((BL / "data/incidents/onchain_targets.json").read_text())["E14_eth"]
    r = refs()
    out = [
        {"label": "ERC20 manager (escrow)", "chain": "ethereum", "pre": "custody0", "b": ETH_B,
         "addr": t["custody"][0].lower()},
        {"label": "ETH manager (escrow)", "chain": "ethereum", "pre": "custody1", "b": ETH_B,
         "addr": t["custody"][1].lower()},
        {"label": "BUSD manager (escrow)", "chain": "ethereum", "pre": "busd_eth", "b": ETH_B,
         "addr": r["busd_manager"]},
        {"label": "BSC token manager (escrow)", "chain": "bsc", "pre": "busd_bsc", "b": BSC_B,
         "addr": r["busd_manager"]},
    ]
    of = RAW / "other_managers.json"
    if of.exists():
        for o in json.loads(of.read_text()):
            out.append({"label": o["label"], "chain": o["chain"], "pre": o["pre"],
                        "b": ETH_B if o["chain"] == "ethereum" else BSC_B, "addr": o["addr"]})
    return [lg for lg in out if (RAW / f"{lg['pre']}_ownlogs_{lg['b'][0]}_{lg['b'][1]}.json").exists()], r


def main():
    L, r = legs()
    own = {lg["addr"] for lg in L} | {r["multisig"]}
    fail_tx = set()
    fj = BL / "data/incidents/onchain/E14_eth.json"
    if fj.exists():
        fail_tx = {x["tx"] for x in json.loads(fj.read_text())["rows"] if x.get("selected")}
    stats = Counter()
    rows = []
    meta = {}
    rpcs = {}
    for ch in {lg["chain"] for lg in L}:
        f = RAW / f"token_meta_{ch}.json"
        meta[ch] = {k: tuple(v) for k, v in json.loads(f.read_text()).items()} if f.exists() else {}
        rpcs[ch] = Rpc(ch)
    ev_n = Counter()
    unmatched_ev = Counter()
    for li, lg in enumerate(L):
        b0, b1 = lg["b"]
        events = {}
        for x in json.loads((RAW / f"{lg['pre']}_ownlogs_{b0}_{b1}.json").read_text()):
            if not x["topics"] or x["topics"][0] != UNLOCKED:
                continue
            w = words(x["data"])
            tok = ("0x" + w[0][-40:]).lower()
            amt = int(w[1], 16)
            rcpt = ("0x" + w[2][-40:]).lower()
            ts = int(x["blockTimestamp"], 16)
            if not (LO <= ts <= HI):
                stats["event_outside_window"] += 1
                continue
            if x["transactionHash"] in fail_tx:
                stats["event_failure_tx"] += 1
                continue
            ev_n[lg["label"]] += 1
            if tok in NATIVE:
                if rcpt in own:
                    stats["native_to_own"] += 1
                    continue
                rows.append({"ts": ts, "leg": li, "chain": lg["chain"], "token": "native", "amount": amt / 1e18,
                             "kind": "event", "to": rcpt, "tx": x["transactionHash"], "matched": True,
                             "blk": int(x["blockNumber"], 16)})
                continue
            k = (x["transactionHash"], tok, amt)
            events[k] = events.get(k, 0) + 1
        tf = RAW / f"{lg['pre']}_transfers_{b0}_{b1}.json"
        for x in json.loads(tf.read_text()) if tf.exists() else []:
            if len(x["topics"]) != 3:
                stats["skip_not_erc20"] += 1
                continue
            to = addr_from_topic(x["topics"][2]).lower()
            ts = int(x["blockTimestamp"], 16)
            if not (LO <= ts <= HI):
                stats["transfer_outside_window"] += 1
                continue
            if x["transactionHash"] in fail_tx:
                stats["transfer_failure_tx"] += 1
                continue
            if to in own:
                stats["transfer_to_own_address"] += 1
                continue
            if to == ZERO:
                stats["transfer_to_zero"] += 1
                continue
            tok = x["address"].lower()
            amt = int(x["data"], 16) if x["data"] not in ("0x", "") else 0
            if amt == 0:
                stats["zero_amount"] += 1
                continue
            k = (x["transactionHash"], tok, amt)
            m = events.get(k, 0) > 0
            if m:
                events[k] -= 1
            sym, dec = erc20_meta(rpcs[lg["chain"]], tok, meta[lg["chain"]])
            rows.append({"ts": ts, "leg": li, "chain": lg["chain"], "token": tok, "amount": amt / 10 ** dec,
                         "kind": "erc20", "to": to, "tx": x["transactionHash"], "matched": m,
                         "blk": int(x["blockNumber"], 16)})
        # fee-on-transfer tokens: the Transfer logs carry the net amount (plus a fee transfer), the Unlocked
        # event the gross amount that left escrow. Match such events to the unmatched transfers of the same
        # transaction and token; the release row takes the gross (event) amount.
        loose = defaultdict(list)
        for x in rows:
            if x["leg"] == li and x["kind"] == "erc20" and not x["matched"]:
                loose[(x["tx"], x["token"])].append(x)
        for (txh, tok, amt), v in events.items():
            while v > 0 and loose.get((txh, tok)):
                grp = loose.pop((txh, tok))
                dec = meta[lg["chain"]][tok][1]
                head = max(grp, key=lambda y: y["amount"])
                head.update(matched=True, amount=amt / 10 ** dec, gross_from_event=True)
                for y in grp:
                    if y is not head:
                        y["fee_part"] = True
                stats["fee_on_transfer_matched"] += 1
                v -= 1
            events[(txh, tok, amt)] = v
        unmatched_ev[lg["label"]] = sum(v for v in events.values() if v > 0)
    for ch in meta:
        (RAW / f"token_meta_{ch}.json").write_text(json.dumps(meta[ch], indent=1))

    # asset labels; distinct contracts sharing a symbol on one chain get a suffix
    sym_of = {}
    by = defaultdict(list)
    for ch, tok in sorted({(x["chain"], x["token"]) for x in rows if x["token"] != "native"}):
        by[(ch, meta[ch][tok][0] or "?")].append(tok)
    for (ch, s), toks in by.items():
        toks.sort(key=lambda t_: -sum(1 for x in rows if x["token"] == t_))
        for j, tok in enumerate(toks):
            sym_of[(ch, tok)] = s if j == 0 else f"{s}#{j + 1}"
    for ch in NATIVE_COIN:
        sym_of[(ch, "native")] = NATIVE_COIN[ch][1]

    # prices
    pdir = RAW / "prices"
    pdir.mkdir(exist_ok=True)
    series = {}
    src = Counter()
    for x in rows:
        key = (x["chain"], x["token"])
        if key not in series:
            coin = NATIVE_COIN[x["chain"]][0] if x["token"] == "native" else f"{x['chain']}:{x['token']}"
            if x["chain"] == "bsc" and x["token"] in PEG and meta["bsc"][x["token"]][0] == PEG[x["token"]][0]:
                coin = PEG[x["token"]][1]
            tl = [y["ts"] for y in rows if (y["chain"], y["token"]) == key]
            series[key] = [coin, hourly_prices(coin, min(tl), max(tl), pdir), None]
        coin, h, d = series[key]
        p = nearest(h, x["ts"], 2 * 3600)
        s = "defillama_1h" if p is not None else None
        if p is None:
            if d is None:
                d = series[key][2] = daily_prices(coin, LO, HI, pdir)
            p = nearest(d, x["ts"], 36 * 3600)
            s = "defillama_1d" if p is not None else None
        x["usd"] = None if p is None else x["amount"] * p
        x["src"] = s
        if s and coin.startswith("coingecko:") and x["token"] != "native":
            s += "_peg"
        if x["matched"]:
            src[s] += 1

    rows.sort(key=lambda x: (x["ts"], x["chain"], x["blk"]))
    keep = [x for x in rows if x["matched"]]
    drop = [x for x in rows if not x["matched"] and not x.get("fee_part")]
    with open(BL / "data/legit/E14.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["ts_utc", "leg", "asset", "amount", "usd", "kind", "priced"])
        for x in keep:
            w.writerow([iso(x["ts"]), L[x["leg"]]["label"], sym_of[(x["chain"], x["token"])], f"{x['amount']:.10g}",
                        "" if x["usd"] is None else f"{x['usd']:.2f}", x["kind"], "yes" if x["usd"] is not None else "no"])
    (RAW / "rows_full.json").write_text(json.dumps(rows, indent=0))
    summ = {
        "window_utc": [iso(LO), iso(HI)], "eth_blocks": ETH_B, "bsc_blocks": BSC_B,
        "legs": [lg["label"] for lg in L], "unlock_events_in_window": dict(ev_n),
        "unlock_events_without_transfer": dict(unmatched_ev), "stats": dict(stats),
        "n_rows_kept": len(keep), "n_transfers_without_unlock": len(drop),
        "dropped_detail": Counter((sym_of[(x["chain"], x["token"])], L[x["leg"]]["label"]) for x in drop).most_common(30),
        "dropped_usd": sum(x["usd"] or 0 for x in drop), "price_src": dict(src),
    }
    (RAW / "process_summary.json").write_text(json.dumps(summ, indent=1, default=str))
    print(json.dumps(summ, indent=1, default=str))


if __name__ == "__main__":
    main()
