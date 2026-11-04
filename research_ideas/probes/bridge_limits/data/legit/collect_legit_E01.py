"""Legitimate release history before the failure, for E01 (liquidity pools of a V3 cross-chain router, July 2021).

Inputs  results/incidents.csv               (failure time; read only)
        data/legit/raw/E01/targets.json     (router contracts and deploy blocks, router key, failure recipient;
                                             addresses stay in raw/)
Outputs data/legit/E01.csv                  (ts_utc, leg, asset, amount, usd, kind, priced; no addresses or hashes)
        data/legit/raw/E01/<chain>/         (raw RPC caches)
        data/legit/raw/E01/prices/          (DefiLlama caches)
        data/legit/raw/E01/rows_with_detail.json, summary.json (numbers quoted in E01_README.md)

Design of the release point (verified router source AnyswapV4Router, anyToken source AnyswapV5ERC20)
- Each pool is an anyToken contract that holds an underlying token. A release signed by the router key calls
  anySwapInUnderlying or anySwapInAuto: the router mints the anyToken to the recipient, emits
  LogAnySwapIn(bytes32 indexed txhash, address indexed token, address indexed to, uint amount, uint fromChainID,
  uint toChainID), and the anyToken burns it and transfers the underlying from the pool to the recipient
  (withdrawVault). anySwapIn (and anySwapInAuto when the pool is short) only mints the anyToken; the trade variants
  mint into an exchange pair. Holders can also redeem anyTokens against the pool directly (withdraw), without the router.
Method
- Window: [t_fail - 150 d, t_fail - 1 s], t_fail = first_release_utc of E01 (the first Ethereum release); the window
  ends there on every leg. The routers were deployed inside the window, so each leg starts at its router's deploy block.
- Pools: tokens named in the router's LogAnySwapIn and LogAnySwapOut events whose underlying() is not zero.
- Release (kind erc20): a Transfer of the pool's underlying token from the pool, in a transaction that holds a
  LogAnySwapIn of that pool with the same amount (one event per transfer). If the underlying goes to the router (the
  wrapped-native path of anySwapInAuto), the row is the native coin paid out (kind native).
- Not releases, counted and valued in summary.json: LogAnySwapIn events of a pool with no pool outflow in the
  transaction (anyToken minted instead of underlying paid; trade variants), and pool outflows without a LogAnySwapIn
  (holder redemptions against the pool, which include later redemptions of minted claims and liquidity withdrawals).
- Exclusions: transfers to the router, to a pool, to the router key, or to the failure recipient.
- Prices: as collect_legit_E21.py (DefiLlama daily chart for every asset, hourly chart for assets with 1M USD or 100
  releases, batchHistorical at the release hour, daily within 36 h; documented 1:1 pegs fall back to the underlying
  coin's series).
Run: python -I data/legit/collect_legit_E01.py
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
sys.path.insert(0, str(ROOT / "incidents"))
from rpc import Rpc, TRANSFER, topic_addr, addr_from_topic, erc20_meta  # noqa: E402
sys.path.insert(0, str(HERE))
import pricing  # noqa: E402
import pricing_points  # noqa: E402
from collect_legit_E21 import ChunkCache, ranged, coverage_gaps, price_rows, summarize, iso, to_ts, failure_time  # noqa: E402

EID = "E01"
RAW = HERE / "raw" / EID
WINDOW_S = 150 * 86400
SWAPIN = "0xaac9ce45fe3adf5143598c4f18a369591a20a3384aedaf1b525d29127e1fcd55"   # LogAnySwapIn(bytes32,address,address,uint256,uint256,uint256)
SWAPOUT = "0x97116cf6cd4f6412bb47914d6db18da9e16ab2142f543b86e207c24fbd16b23a"  # LogAnySwapOut(address,address,address,uint256,uint256,uint256)
SEL_UNDERLYING = "0x6f307dc3"  # underlying()
ZERO = "0x" + "0" * 40
NATIVE_CID = {"ethereum": "coingecko:ethereum", "bsc": "coingecko:binancecoin", "fantom": "coingecko:fantom"}
NATIVE_SYM = {"ethereum": "ETH", "bsc": "BNB", "fantom": "FTM"}
LLAMA_CHAIN = {"ethereum": "ethereum", "bsc": "bsc", "fantom": "fantom"}
CHAIN_CFG = {
    "ethereum": {"urls": ["https://rpc.mevblocker.io", "https://mainnet.gateway.tenderly.co"], "router_step": 5000,
                 "transfer_step": 5000},
    "bsc": {"urls": None, "router_step": 50000, "transfer_step": 50000},
    "fantom": {"urls": ["https://rpcapi.fantom.network"], "router_step": 500000, "transfer_step": 100000},
}
# 1:1 pegs used only when a token's own series has no point within tolerance (filled after the pool list is known;
# see the README for the documentation of each peg)
PEG = {
    "bsc:0x8ac76a51cc950d9822d68b83fe1ad97b32cd580d": "coingecko:usd-coin",   # USDC (Binance-Peg, issuer-backed 1:1)
    "bsc:0x55d398326f99059ff775485246999027b3197955": "coingecko:tether",     # USDT (Binance-Peg)
    "bsc:0xe9e7cea3dedca5984780bafc599bd69add087d56": "coingecko:binance-usd",  # BUSD (Binance-Peg)
    "bsc:0x2170ed0880ac9a755fd29b2688956bd959f933f8": "coingecko:ethereum",   # ETH (Binance-Peg)
    "bsc:0x7130d2a12b9bcbfae4f2634d864a1ee1ce3ead9c": "coingecko:bitcoin",    # BTCB (Binance-Peg)
    # added 2026-10-16: DefiLlama has no series for these two in the window, so 1,947 Fantom releases and
    # 4 Ethereum releases were left unpriced
    "fantom:0x04068da6c83afcfa0e13ba15a6696662335d5b75": "coingecko:usd-coin",  # USDC on Fantom (bridged 1:1)
    "ethereum:0x99d8a9c45b2eca8864373a26d1459e3dff1e17f3": "coingecko:magic-internet-money",  # MIM
}


def make_rpc(chain):
    rpc = Rpc(chain)
    urls = CHAIN_CFG[chain]["urls"]
    rpc.urls = urls if urls else rpc.urls[:1]
    return rpc


def batch_headers(url, blocks, cache):
    """Block timestamps by batched eth_getBlockByNumber (50 per request); falls back to single calls."""
    need = sorted(b for b in set(blocks) if b not in cache)
    for i in range(0, len(need), 50):
        chunk = need[i:i + 50]
        body = json.dumps([{"jsonrpc": "2.0", "id": b, "method": "eth_getBlockByNumber", "params": [hex(b), False]}
                           for b in chunk]).encode()
        for attempt in range(6):
            try:
                req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json",
                                                                      "User-Agent": "bridge-limits-probe/1.0"})
                with urllib.request.urlopen(req, timeout=90) as r:
                    j = json.loads(r.read().decode())
                for x in j:
                    cache[int(x["id"])] = int(x["result"]["timestamp"], 16)
                break
            except Exception:  # noqa: BLE001
                time.sleep(1.5 * (attempt + 1))
        if i % 1000 == 0:
            print(f"   headers {i + len(chunk)}/{len(need)}", flush=True)
    return cache


def collect_leg(chain, L, t_fail):
    rpc = make_rpc(chain)
    cfg = CHAIN_CFG[chain]
    ldir = RAW / chain
    ldir.mkdir(parents=True, exist_ok=True)
    t0 = t_fail - WINDOW_S
    bfile = ldir / "blocks.json"
    if bfile.exists():
        b_win0, b1 = json.loads(bfile.read_text())
    else:
        b_win0 = rpc.block_at(t0)
        b1 = rpc.block_at(t_fail) - 1
        bfile.write_text(json.dumps([b_win0, b1]))
    b0 = max(b_win0, L["router_deploy_block"])
    router = L["router"].lower()
    print(f"== {EID} {L['leg']}: window blocks {b_win0}-{b1}, router from {b0}", flush=True)
    rc = ChunkCache(ldir / "router_logs.jsonl")
    rlogs = ranged(lambda a, b: rpc.call("eth_getLogs", [{"address": router, "fromBlock": hex(a), "toBlock": hex(b)}]),
                   b0, b1, cfg["router_step"], rc, f"{chain} router")
    toks = set()
    for lg in rlogs:
        if lg["topics"] and lg["topics"][0] == SWAPIN:
            toks.add(addr_from_topic(lg["topics"][2]).lower())
        elif lg["topics"] and lg["topics"][0] == SWAPOUT:
            toks.add(addr_from_topic(lg["topics"][1]).lower())
    pf = ldir / "pools.json"
    pools = json.loads(pf.read_text()) if pf.exists() else {}
    for t in sorted(toks):
        if t not in pools:
            r = rpc.eth_call(t, SEL_UNDERLYING, b1)
            pools[t] = ("0x" + r[-40:]).lower() if r and len(r) >= 66 else ZERO
    pf.write_text(json.dumps(pools, indent=1))
    pool_list = sorted(p for p, u in pools.items() if u != ZERO)
    xfer = []
    xc = ChunkCache(ldir / "pool_transfers.jsonl")
    if pool_list:
        xfer = ranged(lambda a, b: rpc.call("eth_getLogs", [{"topics": [TRANSFER, [topic_addr(p) for p in pool_list]],
                                                             "fromBlock": hex(a), "toBlock": hex(b)}]),
                      b0, b1, cfg["transfer_step"], xc, f"{chain} pool transfers")
    gaps = {"router": coverage_gaps(rc, b0, b1), "pool_transfers": coverage_gaps(xc, b0, b1) if pool_list else None}
    return rpc, b_win0, b0, b1, rlogs, pools, pool_list, xfer, gaps


def main():
    targets = json.loads((HERE / "targets" / f"{EID}.json").read_text())
    fail_to = {a.lower() for a in targets.get("failure_recipients", [])}
    mpc = {a.lower() for a in targets.get("router_mpc", [])}
    t_fail = failure_time(EID)
    t0, t1 = t_fail - WINDOW_S, t_fail - 1
    rows, legs_info = [], []
    excluded = collections.Counter()
    not_release = {"mint_only_swapins": collections.defaultdict(lambda: [0, 0]),
                   "pool_outflows_without_swapin": collections.defaultdict(lambda: [0, 0])}
    pending_np = []  # not-release items to value
    for ch, L in targets["legs"].items():
        rpc, b_win0, b0, b1, rlogs, pools, pool_list, xfer, gaps = collect_leg(ch, L, t_fail)
        ldir = RAW / ch
        router = L["router"].lower()
        tsf = ldir / "block_ts.json"
        tsc = {int(k): v for k, v in json.loads(tsf.read_text()).items()} if tsf.exists() else {}
        need = [int(x["blockNumber"], 16) for x in rlogs + xfer if not x.get("blockTimestamp")]
        if need:
            batch_headers(rpc.urls[0], need, tsc)
            tsf.write_text(json.dumps(tsc))

        def ts_of(x):
            if x.get("blockTimestamp"):
                return int(x["blockTimestamp"], 16)
            b = int(x["blockNumber"], 16)
            if b not in tsc:
                tsc[b] = rpc.block_ts(b)
            return tsc[b]

        mf = ldir / "token_meta.json"
        meta = {k: tuple(v) for k, v in json.loads(mf.read_text()).items()} if mf.exists() else {}
        swapins = collections.defaultdict(list)
        topic_n = collections.Counter()
        seen = set()
        for lg in rlogs:
            k = (lg["transactionHash"], lg["logIndex"])
            if lg.get("removed") or k in seen:
                continue
            seen.add(k)
            topic_n[lg["topics"][0] if lg["topics"] else "none"] += 1
            if lg["topics"] and lg["topics"][0] == SWAPIN:
                w = lg["data"][2:]
                swapins[lg["transactionHash"]].append({
                    "token": addr_from_topic(lg["topics"][2]).lower(), "to": addr_from_topic(lg["topics"][3]).lower(),
                    "amount": int(w[0:64], 16), "from_chain": int(w[64:128], 16), "ts": ts_of(lg),
                    "block": int(lg["blockNumber"], 16), "matched": False})
        internal = {router} | set(pools) | mpc
        n_rel = 0
        seen_x = set()
        for lg in xfer:
            k = (lg["transactionHash"], lg["logIndex"])
            if lg.get("removed") or k in seen_x or len(lg["topics"]) != 3:
                continue
            seen_x.add(k)
            src = addr_from_topic(lg["topics"][1]).lower()
            tok = lg["address"].lower()
            if pools.get(src) != tok:
                excluded[f"{ch}: transfer from a pool of a token other than its underlying"] += 1
                continue
            to = addr_from_topic(lg["topics"][2]).lower()
            raw = int(lg["data"], 16) if lg["data"] not in ("0x", "") else 0
            ts = ts_of(lg)
            evs = [e for e in swapins.get(lg["transactionHash"], []) if e["token"] == src and not e["matched"]]
            evs.sort(key=lambda e: e["amount"] != raw)
            if not evs or evs[0]["amount"] != raw:
                not_release["pool_outflows_without_swapin"][(ch, tok)][0] += 1
                not_release["pool_outflows_without_swapin"][(ch, tok)][1] += raw
                pending_np.append({"cls": "pool_outflows_without_swapin", "chain": ch, "token": tok, "raw": raw,
                                   "ts": ts, "to": to})
                continue
            e = evs[0]
            e["matched"] = True
            kind, asset_tok, payee = "erc20", tok, to
            if to == router:  # wrapped-native path: the router unwraps and pays the native coin to the event recipient
                kind, asset_tok, payee = "native", "native", e["to"]
            if payee in fail_to:
                excluded[f"{ch}: to the recipient of the failure"] += 1
                continue
            if payee in internal:
                excluded[f"{ch}: to the router, a pool or the router key"] += 1
                continue
            if ts < t0 or ts > t1:
                excluded[f"{ch}: outside window"] += 1
                continue
            if asset_tok == "native":
                sym, dec, cid = NATIVE_SYM[ch], 18, NATIVE_CID[ch]
            else:
                sym, dec = erc20_meta(rpc, tok, meta)
                cid = f"{LLAMA_CHAIN[ch]}:{tok}"
            rows.append({"ts": ts, "leg": L["leg"], "chain": ch, "symbol": (sym or "?").strip() or "?", "token": asset_tok,
                         "cid": cid, "amount": raw / 10 ** dec, "raw": str(raw), "kind": kind, "pool": src,
                         "from_chain": e["from_chain"]})
            n_rel += 1
        for evs in swapins.values():
            for e in evs:
                if not e["matched"]:
                    u = pools.get(e["token"], ZERO)
                    key = (ch, u if u != ZERO else e["token"])
                    not_release["mint_only_swapins"][key][0] += 1
                    not_release["mint_only_swapins"][key][1] += e["amount"]
                    pending_np.append({"cls": "mint_only_swapins", "chain": ch, "token": u if u != ZERO else None,
                                       "anytoken": e["token"], "raw": e["amount"], "ts": e["ts"], "to": e["to"]})
        for tk in set(pools.values()) - {ZERO}:
            erc20_meta(rpc, tk, meta)
        mf.write_text(json.dumps(meta))
        tsf.write_text(json.dumps(tsc))
        legs_info.append({"leg": L["leg"], "chain": ch, "window_block_from": b_win0, "block_from": b0, "block_to": b1,
                          "block_ts_from": iso(rpc.block_ts(b0)), "block_ts_to": iso(rpc.block_ts(b1)),
                          "router_log_topics": dict(topic_n), "n_swapin_events": sum(len(v) for v in swapins.values()),
                          "pools": [{"underlying_symbol": meta.get(u, ("?", 0))[0], "anytoken_has_underlying": u != ZERO}
                                    for p, u in sorted(pools.items())],
                          "n_pools_with_underlying": len(pool_list), "n_pool_transfer_logs": len(seen_x),
                          "n_releases": n_rel, "coverage_gaps": gaps})
    # label duplicate symbols per chain
    by_sym = collections.defaultdict(collections.Counter)
    for r in rows:
        by_sym[(r["chain"], r["symbol"])][r["token"]] += 1
    label = {}
    for (ch, sym), cnt in by_sym.items():
        for i, (tok, _n) in enumerate(cnt.most_common()):
            label[(ch, tok)] = sym if i == 0 else f"{sym}#{i + 1}"
    for r in rows:
        r["asset"] = label[(r["chain"], r["token"])]
    pinfo = price_rows(rows, RAW / "prices", t0, t1, PEG)
    # value the non-release flows on the same ladder (for the README only)
    metas = {}
    for ch in targets["legs"]:
        mf = RAW / ch / "token_meta.json"
        metas[ch] = {k: tuple(v) for k, v in json.loads(mf.read_text()).items()} if mf.exists() else {}
    np_rows = []
    for x in pending_np:
        if x["token"] is None:
            continue
        sym, dec = metas[x["chain"]].get(x["token"], ("?", 18))
        np_rows.append({"cls": x["cls"], "chain": x["chain"], "ts": x["ts"], "cid": f"{LLAMA_CHAIN[x['chain']]}:{x['token']}",
                        "amount": x["raw"] / 10 ** dec, "symbol": sym,
                        "in_window": t0 <= x["ts"] <= t1})
    price_rows(np_rows, RAW / "prices", t0, t1, PEG)
    np_sum = collections.defaultdict(lambda: {"n": 0, "usd": 0.0, "n_unpriced": 0, "by_symbol": collections.Counter()})
    for x in np_rows:
        if not x["in_window"]:
            continue
        d = np_sum[f"{x['chain']}: {x['cls']}"]
        d["n"] += 1
        d["usd"] += x["usd"] or 0.0
        d["n_unpriced"] += x["usd"] is None
        d["by_symbol"][x["symbol"]] += 1
    rows.sort(key=lambda r: (r["ts"], r["leg"]))
    with (HERE / f"{EID}.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["ts_utc", "leg", "asset", "amount", "usd", "kind", "priced"])
        for r in rows:
            w.writerow([iso(r["ts"]), r["leg"], r["asset"], f"{r['amount']:.10g}",
                        "" if r["usd"] is None else f"{r['usd']:.2f}", r["kind"], "yes" if r["usd"] is not None else "no"])
    (RAW / "rows_with_detail.json").write_text(json.dumps(rows))
    (RAW / "not_release_rows.json").write_text(json.dumps(np_rows))
    s = summarize(rows, t0, t1)
    s.update({"id": EID, "t_fail_utc": iso(t_fail), "window_utc": [iso(t0), iso(t1)], "legs": legs_info,
              "excluded": dict(excluded), "not_releases_in_window": {k: dict(v, by_symbol=dict(v["by_symbol"]))
                                                                      for k, v in np_sum.items()},
              "from_chain_ids": dict(collections.Counter(r["from_chain"] for r in rows)), "pricing": pinfo})
    (RAW / "summary.json").write_text(json.dumps(s, indent=1, default=str))
    print(json.dumps({k: s[k] for k in ("n_rows", "n_priced", "share_priced_count", "usd_total_priced", "excluded",
                                        "not_releases_in_window", "largest_release", "busiest_hour_usd",
                                        "busiest_day_usd")}, indent=1, default=str))
    print(json.dumps(legs_info, indent=1, default=str))


if __name__ == "__main__":
    main()
