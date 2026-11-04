"""Ronin Ethereum gateway (v2/v3 proxy, June 2022 to now): withdrawals held for review and their unlock times.

Contract: the v2/v3 mainchain gateway proxy (custody leg E30_eth in data/incidents/onchain_targets.json;
deployment block from the MainchainGatewayV3Proxy deployment record in
data/code/axieinfinity_ronin-dpos-contracts/deployments/ethereum/).
Events (MainchainGatewayV3, unchanged in MainchainGatewayV2):
  WithdrawalLocked(bytes32 receiptHash, Transfer.Receipt receipt)    emitted when a signed withdrawal is held
  WithdrawalUnlocked(bytes32 receiptHash, Transfer.Receipt receipt)  emitted by unlockWithdrawal (unlocker role)
  Withdrew(bytes32 receiptHash, Transfer.Receipt receipt)            every completed release
A held withdrawal is matched to its unlock by the receipt id. Latency = unlock block time - lock block time.

Sources: eth_getLogs on mainnet.gateway.tenderly.co (500,000-block ranges, address and topic filter) and,
as an independent count, the Blockscout Ethereum logs API over the whole range.
Context: a scan of all gateway logs (50,000-block chunks) counts releases per month, so the held count
has a denominator; limit parameters (lockedThreshold, highTierThreshold, dailyWithdrawalLimit) are read
by eth_call at the block before each lock.

Outputs: raw/ronin/ (caches, addresses live here only), raw/ronin/summary.json,
         results/review_latency_ronin.csv (no addresses or hashes).
Run: python -I data/review_latency/ronin_locks.py
"""
import collections
import csv
import datetime
import json
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import rl_common as rc  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

RECEIPT_T = "(uint256,uint8,(address,address,uint256),(address,address,uint256),(uint8,uint256,uint256))"
LOCK = rc.k256(f"WithdrawalLocked(bytes32,{RECEIPT_T})")
UNLOCK = rc.k256(f"WithdrawalUnlocked(bytes32,{RECEIPT_T})")
WITHDREW = rc.k256(f"Withdrew(bytes32,{RECEIPT_T})")
DEPOSIT_REQ = "0xd7b25068d9dc8d00765254cfb7f5070f98d263c8d68931d937c7362fa738048b"
# constants used by data/legit/build_legit.py, checked against the signatures above
assert LOCK == "0x89e52969465b1f1866fc5d46fd62de953962e9cb33552443cd999eba05bd20dc"
assert UNLOCK == "0xd639511b37b3b002cca6cfe6bca0d833945a5af5a045578a0627fc43b79b2630"
assert WITHDREW == "0x21e88e956aa3e086f6388e899965cef814688f99ad8bb29b08d396571016372d"
WETH = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"
CD = rc.RAW / "ronin"
SCAN_STEP = 50000


def decode_receipt(data):
    w = rc.words(data)
    erc = int(w[9], 16)
    return {"receipt_hash": "0x" + w[0], "id": int(w[1], 16), "kind": int(w[2], 16),
            "to": "0x" + w[3][-40:], "token": ("0x" + w[4][-40:]).lower(), "chain_id": int(w[5], 16),
            "ronin_from": "0x" + w[6][-40:], "erc": erc,
            "quantity": int(w[11], 16) if erc == 0 else 1, "token_id": int(w[10], 16)}


def main():
    CD.mkdir(parents=True, exist_ok=True)
    targets = json.loads((rc.ROOT / "data" / "incidents" / "onchain_targets.json").read_text())
    gw = targets["E30_eth"]["custody"][0].lower()
    dep = json.loads((rc.ROOT / "data" / "code" / "axieinfinity_ronin-dpos-contracts" / "deployments" /
                      "ethereum" / "MainchainGatewayV3Proxy.json").read_text())
    assert dep["address"].lower() == gw
    b_deploy = int(dep["receipt"]["blockNumber"])
    tl = rc.rpc([rc.TENDERLY])
    ar = rc.rpc([rc.MEVBLOCKER, rc.TENDERLY])
    head_info = rc.cached(CD / "head.json", lambda: {"head": tl.head(), "fetched_utc": rc.iso(time.time())})
    head = head_info["head"]
    print("deploy block", b_deploy, "head", head, head_info["fetched_utc"])

    # 1. lock / unlock events, Tenderly in 500k-block ranges
    logs = []
    for s in range(b_deploy, head + 1, 500000):
        e = min(s + 499999, head)
        logs += rc.cached(CD / f"lu_{s}_{e}.json", lambda: tl.logs(gw, [[LOCK, UNLOCK]], s, e, step=500000))
    # 1b. independent count from Blockscout
    bs = {}
    for name, t in (("lock", LOCK), ("unlock", UNLOCK)):
        url = (f"https://eth.blockscout.com/api?module=logs&action=getLogs&fromBlock={b_deploy}&toBlock={head}"
               f"&address={gw}&topic0={t}")
        j = rc.cached(CD / f"blockscout_{name}.json", lambda: rc.http_json(url))
        bs[name] = sorted((int(x["blockNumber"], 16), int(x["logIndex"], 16) if x.get("logIndex") not in (None, "0x") else 0)
                          for x in j.get("result", []))
    ten = {"lock": sorted((int(x["blockNumber"], 16), int(x["logIndex"], 16)) for x in logs if x["topics"][0] == LOCK),
           "unlock": sorted((int(x["blockNumber"], 16), int(x["logIndex"], 16)) for x in logs if x["topics"][0] == UNLOCK)}
    agree = {k: [b for b, _ in ten[k]] == [b for b, _ in bs[k]] for k in ten}
    print("tenderly", {k: len(v) for k, v in ten.items()}, "blockscout", {k: len(v) for k, v in bs.items()}, "agree", agree)

    # 2. decode, timestamps, match
    blocks = sorted({int(x["blockNumber"], 16) for x in logs})
    bts = rc.block_ts_cached(ar, blocks, CD / "block_ts.json")
    locks, unlocks = {}, {}
    for x in logs:
        d = decode_receipt(x["data"])
        d.update({"block": int(x["blockNumber"], 16), "ts": bts[int(x["blockNumber"], 16)], "tx": x["transactionHash"]})
        (locks if x["topics"][0] == LOCK else unlocks)[d["id"]] = d
    meta_p = CD / "token_meta.json"
    meta = json.loads(meta_p.read_text()) if meta_p.exists() else {}
    for d in list(locks.values()) + list(unlocks.values()):
        if d["token"] not in meta:
            meta[d["token"]] = list(rc.erc20_meta(ar, d["token"], {}))
    meta_p.write_text(json.dumps(meta, indent=1))

    # 3. limit parameters in force at the block before each lock
    def per_token(fn, tok, blk):
        r = ar.eth_call(gw, rc.sel(fn + "(address)") + rc.topic_addr(tok)[2:], blk)
        return int(r, 16)
    lim_p = CD / "limits_at_lock.json"
    lim = json.loads(lim_p.read_text()) if lim_p.exists() else {}
    for i, d in locks.items():
        k = str(i)
        if k not in lim:
            lim[k] = {fn: per_token(fn, d["token"], d["block"] - 1)
                      for fn in ("lockedThreshold", "highTierThreshold", "dailyWithdrawalLimit", "unlockFeePercentages")}
            lim_p.write_text(json.dumps(lim, indent=1))

    # 4. prices at lock time (DefiLlama)
    rows = []
    for i, d in sorted(locks.items(), key=lambda kv: kv[1]["ts"]):
        sym, dec = meta[d["token"]]
        amt = d["quantity"] / 10 ** dec
        coin = "coingecko:ethereum" if d["token"] == WETH else f"ethereum:{d['token']}"
        px, _ = rc.llama_price(coin, d["ts"], CD / "prices.json")
        u = unlocks.get(i)
        L = lim[str(i)]
        thr = L["lockedThreshold"] / 10 ** dec
        rows.append({
            "lock_utc": rc.iso(d["ts"]), "unlock_utc": rc.iso(u["ts"]) if u else "",
            "latency_s": (u["ts"] - d["ts"]) if u else "", "latency_h": round((u["ts"] - d["ts"]) / 3600, 2) if u else "",
            "asset": "ETH" if d["token"] == WETH else sym, "amount": round(amt, 6),
            "usd_at_lock": round(amt * px, 0) if px else "",
            "locked_threshold": thr, "amount_over_threshold": round(amt / thr, 3) if thr else "",
            "high_tier_threshold": L["highTierThreshold"] / 10 ** dec,
            "daily_limit": L["dailyWithdrawalLimit"] / 10 ** dec,
            "unlock_fee_pct": L["unlockFeePercentages"] / 1e4,
            "same_receipt_hash": (u["receipt_hash"] == d["receipt_hash"]) if u else "",
            "unlock_same_recipient": (u["to"] == d["to"]) if u else "",
            "lock_weekday": datetime.datetime.fromtimestamp(d["ts"], datetime.timezone.utc).strftime("%a"),
            "unlock_weekday": datetime.datetime.fromtimestamp(u["ts"], datetime.timezone.utc).strftime("%a") if u else "",
        })
    for r in rows:
        print(r)
    unmatched_unlocks = [i for i in unlocks if i not in locks]

    # 5. context scan: all gateway logs, counts per topic and per month (compact cache per chunk)
    month_rel = collections.Counter()
    month_dep = collections.Counter()
    topic_tot = collections.Counter()
    rare = []
    rel_by_asset = collections.Counter()
    last_release_ts = None
    for s in range(b_deploy, head + 1, SCAN_STEP):
        e = min(s + SCAN_STEP - 1, head)

        def fetch():
            res = tl.logs(gw, None, s, e, step=SCAN_STEP)
            out = {"topics": collections.Counter(), "rel_month": collections.Counter(),
                   "dep_month": collections.Counter(), "rel_token": collections.Counter(), "rare": [],
                   "last_release_block": None}
            need_ts = sorted({int(x["blockNumber"], 16) for x in res})
            # month from block timestamp: interpolate between chunk ends to avoid a header call per block
            t0, t1 = ar.block_ts(s), ar.block_ts(e)
            for x in res:
                t = x["topics"][0] if x["topics"] else "none"
                out["topics"][t] += 1
                b = int(x["blockNumber"], 16)
                ts = t0 + (t1 - t0) * (b - s) / max(1, e - s)
                mon = rc.iso(ts)[:7]
                if t == WITHDREW:
                    out["rel_month"][mon] += 1
                    out["rel_token"][("0x" + rc.words(x["data"])[4][-40:]).lower()] += 1
                    out["last_release_block"] = max(out["last_release_block"] or 0, b)
                elif t == DEPOSIT_REQ:
                    out["dep_month"][mon] += 1
                else:
                    out["rare"].append({"block": b, "topic0": t, "tx": x["transactionHash"], "data_len": len(x["data"])})
            out["chunk_ts"] = [t0, t1]
            return out
        c = rc.cached(CD / "scan" / f"{s}_{e}.json", fetch)
        topic_tot.update(c["topics"])
        month_rel.update(c["rel_month"])
        month_dep.update(c["dep_month"])
        rel_by_asset.update(c["rel_token"])
        rare += c["rare"]
        if c["last_release_block"]:
            last_release_ts = c["chunk_ts"]
            last_release_block = c["last_release_block"]
    print("topics", dict(topic_tot))
    n_rel = topic_tot.get(WITHDREW, 0)
    last_rel_ts = ar.block_ts(last_release_block)
    print("releases", n_rel, "last release", rc.iso(last_rel_ts))

    # 6. the other hold path: whole-gateway pauses (Paused / Unpaused), durations from block times
    PAUSED, UNPAUSED = rc.k256("Paused(address)"), rc.k256("Unpaused(address)")
    pz = sorted([x for x in rare if x["topic0"] in (PAUSED, UNPAUSED)], key=lambda x: x["block"])
    pts = rc.block_ts_cached(ar, [x["block"] for x in pz], CD / "pause_block_ts.json")
    pauses, open_p = [], None
    for x in pz:
        t = pts[x["block"]] if x["block"] in pts else pts[str(x["block"])]
        if x["topic0"] == PAUSED:
            open_p = t
        elif open_p is not None:
            pauses.append({"paused_utc": rc.iso(open_p), "unpaused_utc": rc.iso(t), "duration_s": t - open_p})
            open_p = None
    labels = {rc.k256(s): s for s in (
        "Upgraded(address)", "AdminChanged(address,address)", "Initialized(uint8)", "Paused(address)",
        "Unpaused(address)", "RoleGranted(bytes32,address,address)", "RoleRevoked(bytes32,address,address)",
        "HighTierThresholdsUpdated(address[],uint256[])", "LockedThresholdsUpdated(address[],uint256[])",
        "DailyWithdrawalLimitsUpdated(address[],uint256[])", "UnlockFeePercentagesUpdated(address[],uint256[])",
        "TokenMapped(address[],address[],uint256[],uint8[])", "TokenMapped(address[],address[],uint8[])",
        "ThresholdUpdated(uint256,uint256,uint256,uint256,uint256)",
        "HighTierVoteWeightThresholdUpdated(uint256,uint256,uint256,uint256,uint256)",
        "ContractUpdated(uint8,address)", "WrappedNativeTokenContractUpdated(address)")}
    print("pauses", len(pauses), [round(p["duration_s"] / 3600, 2) for p in pauses])
    for t in rel_by_asset:
        if t not in meta and t != WETH:
            meta[t] = list(rc.erc20_meta(ar, t, {}))
    meta_p.write_text(json.dumps(meta, indent=1))

    lat = [r["latency_s"] for r in rows if r["latency_s"] != ""]
    summ = {
        "deploy_block": b_deploy, "head_block": head, "head_fetched_utc": head_info["fetched_utc"],
        "n_locked": len(locks), "n_unlocked": len(unlocks), "n_locked_never_unlocked": len([i for i in locks if i not in unlocks]),
        "unlocks_without_lock_event": len(unmatched_unlocks),
        "source_agreement_blocks": agree, "n_blockscout": {k: len(v) for k, v in bs.items()},
        "latency_s": rc.quantiles(lat),
        "rows": rows,
        "n_releases_all": n_rel, "n_deposits_all": topic_tot.get(DEPOSIT_REQ, 0),
        "last_release_utc": rc.iso(last_rel_ts),
        "releases_by_month": dict(sorted(month_rel.items())), "deposits_by_month": dict(sorted(month_dep.items())),
        "other_topics": {labels.get(t, t): n for t, n in topic_tot.items() if t not in (WITHDREW, DEPOSIT_REQ)},
        "pauses": pauses, "pause_duration_s": rc.quantiles([p["duration_s"] for p in pauses]),
        "pause_open_now": open_p is not None,
        "release_tokens": {("ETH" if t == WETH else meta[t][0] or "unknown"): n for t, n in rel_by_asset.most_common()},
        "releases_by_year": {y: sum(n for mo, n in month_rel.items() if mo.startswith(y))
                             for y in sorted({mo[:4] for mo in month_rel})},
        "locks_by_year": dict(collections.Counter(r["lock_utc"][:4] for r in rows)),
    }
    (CD / "summary.json").write_text(json.dumps(summ, indent=1, default=str))
    with open(CD / "rare_logs.json", "w") as f:
        json.dump(rare, f)
    out = rc.RESULTS / "review_latency_ronin.csv"
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print(json.dumps({k: summ[k] for k in ("n_locked", "n_unlocked", "n_locked_never_unlocked", "latency_s",
                                            "n_releases_all", "last_release_utc", "source_agreement_blocks")},
                     indent=1))


if __name__ == "__main__":
    main()
