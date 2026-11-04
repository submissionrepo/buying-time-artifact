"""Prices, extra on-chain reads (Wormhole Portal, Polygon checkpoints) and USD valuation.
Reads the eth_reads JSON written by stake_reads.py.
"""
import glob
import json
import os
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ethcall_lib as E  # noqa: E402

BASE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "stake")
ONC = os.path.join(BASE, "onchain")
API = os.path.join(BASE, "api")
reads_path = sorted(glob.glob(os.path.join(ONC, "eth_reads_*.json")))[-1]
RD = json.load(open(reads_path, encoding="utf-8"))
BLK = hex(RD["block"]["number"])
r = RD["reads"]


def fetch(url, path=None):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=120) as f:
        txt = f.read().decode()
    if path:
        with open(path, "w", encoding="utf-8") as g:
            g.write(txt)
        with open(path.replace(".json", ".accessed_utc.txt"), "w") as g:
            g.write(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    return json.loads(txt)


# ---------- extra reads at the same block ----------
TOK = {
    "WETH": ("0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2", 18),
    "USDC": ("0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48", 6),
    "USDT": ("0xdAC17F958D2ee523a2206206994597C13D831ec7", 6),
    "DAI": ("0x6B175474E89094C44Da98b954EedeAC495271d0F", 18),
    "WBTC": ("0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599", 8),
    "wstETH": ("0x7f39C581F595B53c5cb19bD0b3f8dA6c935E2Ca0", 18),
    "stETH": ("0xae7ab96520DE3A18E5e111B5EaAb095312D7fE84", 18),
    "cbBTC": ("0xcbB7C0000aB88B473b1f5aFd9ef808440eed33Bf", 8),
    "LINK": ("0x514910771AF9Ca656af840dff83E8264EcF986CA", 18),
    "USDe": ("0x4c9EDD5852cd905f086C759E8383e09bff1E68B3", 18),
    "FRAX": ("0x853d955aCEf822Db058eb8505911ED77F175b99e", 18),
    "PYUSD": ("0x6c3ea9036406852006290770BEdFcAbA0e23A0e8", 6),
    "USDS": ("0xdC035D45d973E3EC169d2276DDab16f1e407384F", 18),
    "UNI": ("0x1f9840a85d5aF5bf1D1762F925BDADdC4201F984", 18),
    "AAVE": ("0x7Fc66500c84A76Ad7e9c93437bFc5Ac33E2DDaE9", 18),
    "SHIB": ("0x95aD61b0a150d79219dCF64E1E6Cc01f0B64C4cE", 18),
    "LDO": ("0x5A98FcBEA516Cf06857215779Fd812CA3beF1B32", 18),
    "CRV": ("0xD533a949740bb3306d119CC777fa900bA034cd52", 18),
    "MATIC": ("0x7D1AfA7B718fb893dB30A3aBc0Cfc608AaCfeBB0", 18),
    "POL": ("0x455e53CBB86018Ac2B8092FdCd39d8444aFFC3F6", 18),
}
WH = "0x3ee18B2214AFF97000D974cf647E7C347E8fa585"
extra = {"block": BLK}
c = E.rpc("eth_getCode", [WH, BLK])[1]
extra["wormhole_portal_code_len"] = (len(c) - 2) // 2
wh = {}
for n, (addr, dec) in TOK.items():
    res = E.eth_call(addr, "balanceOf(address)", ["address"], [WH], block=BLK)
    b = E.as_uint(E.words(res)[0])
    if b:
        wh[n] = b / 10 ** dec
extra["wormhole_portal_tokens"] = wh
# Polygon checkpoints: RootChain headerBlocks timing
RC = "0x86E4Dc95c7FBdBf52e33D563BbDB00823894C287"
cur = E.as_uint(E.words(E.eth_call(RC, "currentHeaderBlock()", block=BLK))[0])
interval = 10000
times = []
for i in range(0, 41):
    hid = cur - interval * (i + 1)
    res = E.eth_call(RC, "headerBlocks(uint256)", ["uint256"], [hid], block=BLK)
    w = E.words(res)
    times.append((hid, E.as_uint(w[3])))
extra["polygon_rootchain_currentHeaderBlock"] = cur
extra["polygon_last_checkpoints"] = times[:5]
ts_ = [t for _, t in times if t]
if len(ts_) > 2:
    extra["polygon_mean_checkpoint_interval_s_last40"] = (ts_[0] - ts_[-1]) / (len(ts_) - 1)
E.dump(os.path.join(ONC, "extra_calllog_" + time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + ".json"),
       {"block": BLK})

# ---------- prices ----------
addrs = set(v[0] for v in TOK.values())
for x in r["ccip_eth_pools"]:
    addrs.add(x["token"])
for k in ["HYPER:0x93a2db22b7c736b341c32ff666307f4a9ed910f5",
          "BARD:0xf0db65d17e30a966c2ae6a21f6bba71cea6e9754",
          "SIS:0xd38bb40815d2b0c2d2c866e0c72c5728ffc76dd9",
          "ZRO:0x6985884C4392D348587B19cb9eAAf157F13271cd",
          "UMA:0x04Fa0d235C4abf4BcF4787aF4CF447DE572eF828",
          "ACX:0x44108f0223A3C3028F5Fe7AEC7f9bb2E66beF82F",
          "BAL:0xba100000625a3754423978a60c9317c58a424e3D",
          "SNX:0xC011a73ee8576Fb46F5E1c5751cA3B9Fe0af2a6F",
          "SAND:0x3845badAde8e6dFF049820680d1F14bD3903a5d0",
          "MANA:0x0F5D2fB29fb7d3CFeE444a200298f468908cC942",
          "GHST:0x3F382DbD960E3a9bbCeaE22651E88158d2791550",
          "APE:0x4d224452801ACEd8B2F0aebE155379bb5D594381",
          "GRT:0xc944E90C64B2c07662A292be6244BDf05Cda44a7",
          "ABT:0xee1dc6bcf1ee967a350e9ac6caaaa236109002ea"]:
    addrs.add(k.split(":")[1])
keys = ["ethereum:" + a_.lower() for a_ in sorted(addrs)]
CG = ["axelar", "hyperlane", "layerzero", "uma", "chainlink", "polygon-ecosystem-token",
      "ethereum", "wormhole", "supra", "lombard-protocol", "solv-protocol", "ethena",
      "symbiosis-finance", "eigenlayer", "across-protocol", "bitcoin", "matic-network"]
keys += ["coingecko:" + x for x in CG]
prices = {}
for i in range(0, len(keys), 40):
    chunk = ",".join(keys[i:i + 40])
    d = fetch("https://coins.llama.fi/prices/current/" + chunk + "?searchWidth=4h")
    prices.update(d.get("coins", {}))
with open(os.path.join(API, "llama_prices_refresh.json"), "w", encoding="utf-8") as f:
    json.dump({"accessed_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "coins": prices}, f, indent=1)
cg = fetch("https://api.coingecko.com/api/v3/simple/price?ids=" + ",".join(CG) +
           "&vs_currencies=usd&include_last_updated_at=true",
           os.path.join(API, "coingecko_simple_price_refresh.json"))
llama_protocols = fetch("https://api.llama.fi/protocols", os.path.join(API, "llama_protocols_refresh.json"))


def P(addr):
    x = prices.get("ethereum:" + addr.lower())
    return (x or {}).get("price")


def PG(cgid):
    x = prices.get("coingecko:" + cgid)
    return (x or {}).get("price")


V = {"prices_used": {}}
for cg_ in CG:
    V["prices_used"][cg_] = {"llama": PG(cg_), "coingecko": (cg.get(cg_) or {}).get("usd")}
ETHP = PG("ethereum")


def usd_tokens(tokdict, symmap):
    tot, miss = 0.0, []
    for n, amt in tokdict.items():
        addr = symmap.get(n)
        p = P(addr) if addr else None
        if p is None:
            miss.append(n)
            continue
        tot += amt * p
    return tot, miss


SYMADDR = {k: v[0] for k, v in TOK.items()}
SYMADDR.update({"ACX": "0x44108f0223A3C3028F5Fe7AEC7f9bb2E66beF82F",
                "UMA": "0x04Fa0d235C4abf4BcF4787aF4CF447DE572eF828",
                "BAL": "0xba100000625a3754423978a60c9317c58a424e3D",
                "SNX": "0xC011a73ee8576Fb46F5E1c5751cA3B9Fe0af2a6F",
                "SAND": "0x3845badAde8e6dFF049820680d1F14bD3903a5d0",
                "MANA": "0x0F5D2fB29fb7d3CFeE444a200298f468908cC942",
                "GHST": "0x3F382DbD960E3a9bbCeaE22651E88158d2791550",
                "APE": "0x4d224452801ACEd8B2F0aebE155379bb5D594381",
                "GRT": "0xc944E90C64B2c07662A292be6244BDf05Cda44a7"})

# Across
acr = r["across"]
pool_usd = {}
for n, p_ in acr["pooledTokens"].items():
    pr = P(SYMADDR[n]) if n in SYMADDR else None
    if pr is None:
        continue
    pool_usd[n] = {"liquid_usd": p_["liquidReserves"] * pr,
                   "utilized_usd": max(p_["utilizedReserves"], 0) * pr,
                   "total_usd": (p_["liquidReserves"] + max(p_["utilizedReserves"], 0)) * pr}
V["across"] = {"bond_ABT": acr["bondAmount"] / 1e18, "bond_usd": acr["bondAmount"] / 1e18 * ETHP,
               "liveness_s": acr["liveness_s"], "pools_usd": pool_usd,
               "pools_total_usd": sum(x["total_usd"] for x in pool_usd.values()),
               "pools_total_usd_ex_ACX": sum(x["total_usd"] for k, x in pool_usd.items() if k != "ACX")}
uma = r["uma"]
V["uma"] = {"staked_UMA": uma["voting_cumulativeStake"] / 1e18,
            "staked_usd": uma["voting_cumulativeStake"] / 1e18 * P(SYMADDR["UMA"]),
            "gat_UMA": uma["voting_gat"] / 1e18, "spat": uma["voting_spat"] / 1e18,
            "unstake_cooldown_s": uma["voting_unstakeCoolDown_s"],
            "UMA_price": P(SYMADDR["UMA"]), "UMA_totalSupply": uma["UMA_totalSupply"] / 1e18}
# Polygon
pol = r["polygon"]
polp = PG("polygon-ecosystem-token")
esc_usd, miss_all = 0.0, []
detail = {}
for k, e in pol["escrows"].items():
    tv, miss = usd_tokens(e["tokens"], SYMADDR)
    tv += e["ETH"] * ETHP
    detail[k] = tv
    esc_usd += tv
    miss_all += miss
V["polygon"] = {"validator_set_stake_POL": pol["currentValidatorSetTotalStake()"] / 1e18,
                "validator_set_stake_usd": pol["currentValidatorSetTotalStake()"] / 1e18 * polp,
                "totalStaked_POL": pol["totalStaked()"] / 1e18,
                "withdrawalDelay_checkpoints": pol["withdrawalDelay()"],
                "mean_checkpoint_interval_s": extra.get("polygon_mean_checkpoint_interval_s_last40"),
                "withdrawalDelay_days_est": pol["withdrawalDelay()"] * (extra.get("polygon_mean_checkpoint_interval_s_last40") or 0) / 86400,
                "escrow_usd_by_contract": detail, "escrow_usd_total_partial": esc_usd,
                "escrow_missing_prices": miss_all, "POL_price": polp}
# Chainlink
cl = r["chainlink_staking"]
linkp = P(SYMADDR["LINK"])
V["chainlink"] = {"community_LINK": cl["community"]["getTotalPrincipal"] / 1e18,
                  "operator_LINK": cl["operator"]["getTotalPrincipal"] / 1e18,
                  "operator_usd": cl["operator"]["getTotalPrincipal"] / 1e18 * linkp,
                  "total_usd": (cl["community"]["getTotalPrincipal"] + cl["operator"]["getTotalPrincipal"]) / 1e18 * linkp,
                  "LINK_price": linkp,
                  "alert_config_ETHUSD": cl["alerts"]["getFeedConfig_ETHUSD_words"]}
# CCIP pools
cc_tot, cc_rows, cc_unpriced = 0.0, [], []
for x in r["ccip_eth_pools"]:
    pr = P(x["token"])
    if x["balance"] and pr is None:
        cc_unpriced.append(x["symbol"])
        continue
    v = x["balance"] * (pr or 0)
    cc_tot += v
    cc_rows.append((x["symbol"], x["typeAndVersion"], x["balance"], pr, v))
cc_rows.sort(key=lambda t: -t[4])
V["ccip_eth_lockrelease"] = {"total_usd": cc_tot, "n_pools": len(r["ccip_eth_pools"]),
                             "top": cc_rows[:15], "unpriced_nonzero": cc_unpriced}
# Symbiotic vaults
sym = {}
pmap = {"HYPER": "0x93a2db22b7c736b341c32ff666307f4a9ed910f5",
        "LINK": SYMADDR["LINK"], "BARD": "0xf0db65d17e30a966c2ae6a21f6bba71cea6e9754",
        "SIS": "0xd38bb40815d2b0c2d2c866e0c72c5728ffc76dd9"}
for name, d in r["symbiotic_vaults"].items():
    cs = d.get("collateral_symbol")
    pr = P(pmap[cs]) if cs in pmap else None
    sym[name] = {"collateral": cs, "totalStake": d.get("totalStake()"),
                 "price": pr, "totalStake_usd": (d.get("totalStake()") or 0) * (pr or 0),
                 "epoch_days": (d.get("epochDuration_s") or 0) / 86400,
                 "slasher_type": d.get("slasher_TYPE"),
                 "veto_days": (d.get("slasher_vetoDuration_s") or 0) / 86400,
                 "slash_requests": d.get("slasher_slashRequestsLength")}
V["symbiotic"] = sym
# Hyperlane AVS weight
hl = r["hyperlane_avs"]
mult = [m for _, m in hl.get("avs_quorum", [])]
V["hyperlane_avs"] = {"totalWeight": hl["avs_totalWeight"] / 1e18,
                      "sum_multipliers_bps": sum(mult),
                      "eth_equiv_if_uniform": hl["avs_totalWeight"] / 1e18 / (sum(mult) / len(mult) / 1e4) if mult else None}
V["hyperlane_avs"]["eth_equiv_usd"] = (V["hyperlane_avs"]["eth_equiv_if_uniform"] or 0) * ETHP
# EigenZero proxy
eg = r["eigenlayer"]
V["eigenlayer"] = dict(eg)
V["eigenlayer"]["ZRO_price"] = P("0x6985884C4392D348587B19cb9eAAf157F13271cd")
V["eigenlayer"]["ZRO_strategy_usd"] = (eg.get("ZRO_strategy_balance") or 0) * (V["eigenlayer"]["ZRO_price"] or 0)
# Escrow cross-checks
esc = r["escrows"]
xs = {}
for k, e in esc.items():
    tv, miss = usd_tokens(e.get("tokens", {}), SYMADDR)
    tv += e.get("ETH", 0) * ETHP
    xs[k] = tv
tv, miss = usd_tokens(wh, SYMADDR)
xs["wormhole_portal_ethereum_partial"] = tv
V["escrow_crosschecks_usd"] = xs
V["extra_reads"] = extra
# DefiLlama protocol TVLs
want = ["layerzero-v2", "usdt0", "polygon-bridge", "ccip", "portal", "axelar", "axelar-cross-chain",
        "stargate-v2", "hyperlane", "across", "supra-bridge", "symbiosis", "solvbtc", "lombard-lbtc",
        "eigencloud", "symbiotic", "thorchain-dex", "chainflip-amm"]
lt = {}
for p in llama_protocols:
    if p.get("slug") in want:
        lt[p["slug"]] = {"name": p.get("name"), "category": p.get("category"), "tvl": p.get("tvl"),
                         "eth": (p.get("chainTvls") or {}).get("Ethereum")}
V["llama_tvl"] = lt
V["meta"] = {"reads_file": os.path.basename(reads_path), "block": RD["block"],
             "computed_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
with open(os.path.join(ONC, "valuation_" + time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + ".json"),
          "w", encoding="utf-8") as f:
    json.dump(V, f, indent=1)
print(json.dumps(V, indent=1)[:20000])
