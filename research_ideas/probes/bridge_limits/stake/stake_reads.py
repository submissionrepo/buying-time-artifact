"""On-chain reads for the stake-vs-value note (bridge withdrawal limits paper).

All reads are eth_call / eth_getBalance / eth_getCode against one pinned
Ethereum block, via public RPCs (publicnode first, mevblocker fallback).
Every call is logged with RPC, block, calldata and raw return.
Output: data/stake/onchain/eth_reads_<UTC>.json
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ethcall_lib as E  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "stake", "onchain")
os.makedirs(OUT, exist_ok=True)

blk = E.block_info("latest")
BLK = hex(blk["number"])
R = {"block": blk, "reads": {}}


def call(to, sig, types=(), args=(), note=""):
    try:
        return E.eth_call(to, sig, types, args, block=BLK, note=note)
    except Exception as e:  # revert or missing function
        E.LOG.append({"to": to, "sig": sig, "args": [str(a) for a in args],
                      "error": repr(e)[:300], "block": BLK, "note": note})
        return None


def u(to, sig, types=(), args=(), note=""):
    r = call(to, sig, types, args, note)
    if r is None or r in ("0x", ""):
        return None
    return E.as_uint(E.words(r)[0])


def a(to, sig, types=(), args=(), note=""):
    r = call(to, sig, types, args, note)
    if r is None or r in ("0x", ""):
        return None
    return E.as_addr(E.words(r)[0])


def s(to, sig="symbol()"):
    r = call(to, sig)
    if r is None or r in ("0x", ""):
        return None
    try:
        return E.as_string(r)
    except Exception:
        try:  # bytes32 symbol (e.g. MKR)
            return bytes.fromhex(E.words(r)[0]).rstrip(b"\0").decode()
        except Exception:
            return None


def bal(token, holder):
    return u(token, "balanceOf(address)", ["address"], [holder])


def ethbal(addr):
    u_, r = E.rpc("eth_getBalance", [addr, BLK])
    E.LOG.append({"method": "eth_getBalance", "addr": addr, "block": BLK,
                  "result": r, "rpc": u_})
    return int(r, 16)


def code(addr):
    u_, r = E.rpc("eth_getCode", [addr, BLK])
    E.LOG.append({"method": "eth_getCode", "addr": addr, "block": BLK,
                  "len_bytes": (len(r) - 2) // 2, "rpc": u_})
    return r


def ascii32(txt):
    return txt.encode().hex().ljust(64, "0")


TOK = {
    "WETH": "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
    "USDC": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
    "USDT": "0xdAC17F958D2ee523a2206206994597C13D831ec7",
    "DAI": "0x6B175474E89094C44Da98b954EedeAC495271d0F",
    "WBTC": "0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599",
    "LINK": "0x514910771AF9Ca656af840dff83E8264EcF986CA",
    "POL": "0x455e53CBB86018Ac2B8092FdCd39d8444aFFC3F6",
    "MATIC": "0x7D1AfA7B718fb893dB30A3aBc0Cfc608AaCfeBB0",
    "AAVE": "0x7Fc66500c84A76Ad7e9c93437bFc5Ac33E2DDaE9",
    "UNI": "0x1f9840a85d5aF5bf1D1762F925BDADdC4201F984",
    "wstETH": "0x7f39C581F595B53c5cb19bD0b3f8dA6c935E2Ca0",
    "stETH": "0xae7ab96520DE3A18E5e111B5EaAb095312D7fE84",
    "cbBTC": "0xcbB7C0000aB88B473b1f5aFd9ef808440eed33Bf",
    "USDe": "0x4c9EDD5852cd905f086C759E8383e09bff1E68B3",
    "FRAX": "0x853d955aCEf822Db058eb8505911ED77F175b99e",
    "ZRO": "0x6985884C4392D348587B19cb9eAAf157F13271cd",
    "UMA": "0x04Fa0d235C4abf4BcF4787aF4CF447DE572eF828",
    "ACX": "0x44108f0223A3C3028F5Fe7AEC7f9bb2E66beF82F",
    "BAL": "0xba100000625a3754423978a60c9317c58a424e3D",
    "SNX": "0xC011a73ee8576Fb46F5E1c5751cA3B9Fe0af2a6F",
    "CRV": "0xD533a949740bb3306d119CC777fa900bA034cd52",
    "SAND": "0x3845badAde8e6dFF049820680d1F14bD3903a5d0",
    "MANA": "0x0F5D2fB29fb7d3CFeE444a200298f468908cC942",
    "GHST": "0x3F382DbD960E3a9bbCeaE22651E88158d2791550",
    "SHIB": "0x95aD61b0a150d79219dCF64E1E6Cc01f0B64C4cE",
    "APE": "0x4d224452801ACEd8B2F0aebE155379bb5D594381",
    "LDO": "0x5A98FcBEA516Cf06857215779Fd812CA3beF1B32",
    "GRT": "0xc944E90C64B2c07662A292be6244BDf05Cda44a7",
    "PYUSD": "0x6c3ea9036406852006290770BEdFcAbA0e23A0e8",
    "USDS": "0xdC035D45d973E3EC169d2276DDab16f1e407384F",
}
DEC = {}
for k, v in TOK.items():
    DEC[k] = u(v, "decimals()")


def tokbals(holder, names):
    out = {}
    for n in names:
        b = bal(TOK[n], holder)
        if b:
            out[n] = b / 10 ** DEC[n]
    return out


# ---------------- Across HubPool and UMA ----------------
HUB = "0xc186fA914353c44b2E33eBE05f21846F1048bEda"
acr = {}
acr["bondAmount"] = u(HUB, "bondAmount()")
acr["bondToken"] = a(HUB, "bondToken()")
acr["bondToken_symbol"] = s(acr["bondToken"]) if acr["bondToken"] else None
acr["bondToken_name"] = s(acr["bondToken"], "name()") if acr["bondToken"] else None
acr["liveness_s"] = u(HUB, "liveness()")
r = call(HUB, "identifier()")
acr["identifier"] = bytes.fromhex(E.words(r)[0]).rstrip(b"\0").decode() if r else None
acr["finder"] = a(HUB, "finder()")
r = call(HUB, "rootBundleProposal()")
if r:
    w = E.words(r)
    acr["rootBundleProposal_words"] = len(w)
    acr["rootBundleProposal_proposer"] = E.as_addr(w[4]) if len(w) > 4 else None
    acr["rootBundleProposal_challengePeriodEnd"] = E.as_uint(w[-1])
pools = {}
for n in ["WETH", "USDC", "USDT", "DAI", "WBTC", "ACX", "UMA", "BAL", "SNX",
          "LINK", "POL", "MATIC", "USDS", "cbBTC", "wstETH", "USDe"]:
    r = call(HUB, "pooledTokens(address)", ["address"], [TOK[n]])
    if not r:
        continue
    w = E.words(r)
    if len(w) < 6:
        continue
    lp, en = E.as_addr(w[0]), E.as_uint(w[1])
    if lp == "0x" + "0" * 40:
        continue
    d = 10 ** DEC[n]
    pools[n] = {"lpToken": lp, "isEnabled": en,
                "utilizedReserves": E.as_int(w[3]) / d,
                "liquidReserves": E.as_uint(w[4]) / d,
                "undistributedLpFees": E.as_uint(w[5]) / d,
                "hub_balance": (bal(TOK[n], HUB) or 0) / d}
acr["pooledTokens"] = pools
FIND = acr["finder"]
uma = {}
if FIND:
    for nm in ["Oracle", "SkinnyOptimisticOracle", "OptimisticOracleV3", "Store"]:
        uma["impl_" + nm] = a(FIND, "getImplementationAddress(bytes32)",
                              ["bytes32"], ["0x" + ascii32(nm)])
    V = uma.get("impl_Oracle")
    if V:
        uma["voting_cumulativeStake"] = u(V, "cumulativeStake()")
        uma["voting_unstakeCoolDown_s"] = u(V, "unstakeCoolDown()")
        uma["voting_gat"] = u(V, "gat()")
        uma["voting_spat"] = u(V, "spat()")
        uma["voting_votingToken"] = a(V, "votingToken()")
        uma["voting_phaseLength"] = None
        r = call(V, "voteTiming()")
        if r:
            uma["voting_voteTiming_word0"] = E.as_uint(E.words(r)[0])
        uma["UMA_totalSupply"] = u(TOK["UMA"], "totalSupply()")
    ST = uma.get("impl_Store")
    if ST:
        r = call(ST, "computeFinalFee(address)", ["address"], [acr["bondToken"]])
        if r:
            uma["store_finalFee_bondToken"] = E.as_uint(E.words(r)[0])
R["reads"]["across"] = acr
R["reads"]["uma"] = uma

# ---------------- Polygon PoS ----------------
SM = "0x5e3Ef299fDDf15eAa0432E6e66473ace8c13D908"
pol = {}
for f in ["totalStaked()", "currentValidatorSetTotalStake()", "withdrawalDelay()",
          "checkPointBlockInterval()", "validatorThreshold()", "currentEpoch()",
          "checkpointReward()", "dynasty()", "NFTCounter()", "currentValidatorSetSize()",
          "minDeposit()", "proposerBonus()"]:
    pol[f] = u(SM, f)
pol["token()"] = a(SM, "token()")
pol["implementation()"] = a(SM, "implementation()")
if pol["implementation()"]:
    c = code(pol["implementation()"])
    for sig in ["slash(bytes)", "unjail(uint256)", "totalStaked()"]:
        pol["impl_has_selector_" + sig] = E.selector(sig) in c
    pol["impl_code_len"] = (len(c) - 2) // 2
POLY_ESC = {
    "DepositManager": "0x401F6c983eA34274ec46f84D70b31C151321188b",
    "ERC20Predicate": "0x40ec5B33f54e0E8A33A975908C5BA1c14e5BbbDf",
    "esc_0x9923": "0x9923263fA127b3d1484cFD649df8f1831c2A74e4",
    "esc_0x21ad": "0x21ada4D8A799c4b0ADF100eB597a6f1321bCD3E4",
    "EtherPredicate": "0x8484Ef722627bf18ca5Ae6BcF031c23E6e922B30",
    "esc_0xa45b": "0xa45b966996374E9e65ab991C6FE4Bfce3a56DDe8",
}
pe = {}
for k, v in POLY_ESC.items():
    pe[k] = {"ETH": ethbal(v) / 1e18,
             "tokens": tokbals(v, list(TOK.keys()))}
pol["escrows"] = pe
R["reads"]["polygon"] = pol

# ---------------- Chainlink staking v0.2 ----------------
CL = {"community": "0xBc10f2E862ED4502144c7d632a3459F49DFCDB5e",
      "operator": "0xa1d76A7cA72128541E9FCAcafBdA3a92EF94fDc5",
      "alerts": "0x27484BA119d12649BE2a9854E4D3B44cc3FdbaD7"}
cl = {}
for k, v in CL.items():
    d = {"typeAndVersion": s(v, "typeAndVersion()")}
    if k != "alerts":
        d["getTotalPrincipal"] = u(v, "getTotalPrincipal()")
        d["getMaxPoolSize"] = u(v, "getMaxPoolSize()")
        r = call(v, "getUnbondingParams()")
        if r:
            w = E.words(r)
            d["unbondingPeriod_s"] = E.as_uint(w[0])
            d["claimPeriod_s"] = E.as_uint(w[1])
        r = call(v, "getStakerLimits()")
        if r:
            w = E.words(r)
            d["stakerLimits"] = [E.as_uint(x) / 1e18 for x in w[:2]]
        d["LINK_balance"] = (bal(TOK["LINK"], v) or 0) / 1e18
    else:
        r = call(v, "getFeedConfig(address)", ["address"],
                 ["0x5f4eC3Df9cbd43714FE2740f5E3616155c5b8419"])
        d["getFeedConfig_ETHUSD_words"] = [E.as_uint(x) for x in E.words(r)] if r else None
    cl[k] = d
R["reads"]["chainlink_staking"] = cl

# ---------------- Hyperlane: EigenLayer AVS registry ----------------
HSR = "0x272CF0BB70D3B4f79414E0823B426d2EaFd48910"
hl = {}
hl["avs_totalWeight"] = u(HSR, "getLastCheckpointTotalWeight()")
hl["avs_thresholdWeight"] = u(HSR, "getLastCheckpointThresholdWeight()")
hl["avs_minimumWeight"] = u(HSR, "minimumWeight()")
r = call(HSR, "quorum()")
if r:
    w = E.words(r)
    # (offset)(offset to array)(len)(strategy, multiplier)*
    try:
        n = E.as_uint(w[2])
        hl["avs_quorum"] = [[E.as_addr(w[3 + 2 * i]), E.as_uint(w[4 + 2 * i])]
                            for i in range(n)]
    except Exception:
        hl["avs_quorum_raw"] = w
R["reads"]["hyperlane_avs"] = hl

# ---------------- Symbiotic vaults ----------------
VAULTS = {
    "stHYPER (Hyperlane)": "0xE1F23869776c82f691d9Cb34597Ab1830Fb0De58",
    "LINK vault (Lombard/Solv CCIP)": "0xD538A11e421449F2BAFA153F678C81E7a4f411B3",
    "Staked BARD (Lombard CCIP)": "0x34beb65E41F6f0A36275Fe85F4f4574CE9237231",
    "Staked SOLV (Solv CCIP)": "0xe5B076eCA94b542b45E3A082F72bA214AA5Eb61E",
    "rsENA (Ethena LZ DVN)": "0xcC4DE7C3AF8a4eCc2D96bc821bbA3A2D94e3298b",
    "rsUSDe (Ethena LZ DVN)": "0x156BD0377181B6090230B20e4D9070c04467D1BD",
    "Symbiosis SIS": "0x2eE8fe221AFD5Da36a5cfD4fee12BE5dAb562397",
    "Cycle Network": "0x941Ee11c2470755a5281e6B5D8f74fcD6bb1057A",
}
NETS = {"Hyperlane": "0x59cf937ea9fa9d7398223e3aa33d92f7f5f986a2",
        "Lombard CCIP": "0x769f653c1CD9f2abcBACBfeAaE5C9D8Dc2033Fef",
        "Solv CCIP": "0xf02D5A6aDEC0286be3e13886C9C2e782679B6c39",
        "Symbiosis": "0x5112EbA9bc2468Bb5134CBfbEAb9334EdaE7106a",
        "Cycle": "0x759D4335cb712aa188935C2bD3Aa6D205aC61305"}
sv = {}
for name, v in VAULTS.items():
    d = {"address": v, "code_len": (len(code(v)) - 2) // 2}
    col = a(v, "collateral()")
    d["collateral"] = col
    if col:
        d["collateral_symbol"] = s(col)
        cd = u(col, "decimals()") or 18
        d["collateral_decimals"] = cd
        for f in ["totalStake()", "activeStake()"]:
            x = u(v, f)
            d[f] = x / 10 ** cd if x is not None else None
        d["epochDuration_s"] = u(v, "epochDuration()")
        d["currentEpoch"] = u(v, "currentEpoch()")
        d["slasher"] = a(v, "slasher()")
        d["delegator"] = a(v, "delegator()")
        d["burner"] = a(v, "burner()")
        d["isSlasherInitialized"] = u(v, "isSlasherInitialized()")
        d["collateral_balance_of_vault"] = (bal(col, v) or 0) / 10 ** cd
        if d["slasher"] and d["slasher"] != "0x" + "0" * 40:
            d["slasher_TYPE"] = u(d["slasher"], "TYPE()")
            d["slasher_vetoDuration_s"] = u(d["slasher"], "vetoDuration()")
            d["slasher_resolverSetEpochsDelay"] = u(d["slasher"], "resolverSetEpochsDelay()")
            d["slasher_slashRequestsLength"] = u(d["slasher"], "slashRequestsLength()")
        if d["delegator"] and d["delegator"] != "0x" + "0" * 40:
            d["delegator_TYPE"] = u(d["delegator"], "TYPE()")
            nl = {}
            for nn, na in NETS.items():
                sub = "0x" + na[2:].lower() + "0" * 24
                x = u(d["delegator"], "networkLimit(bytes32)", ["bytes32"], [sub])
                mx = u(d["delegator"], "maxNetworkLimit(bytes32)", ["bytes32"], [sub])
                if x or mx:
                    nl[nn] = {"networkLimit": x / 10 ** cd if x else 0,
                              "maxNetworkLimit": mx / 10 ** cd if mx else 0}
            d["network_limits"] = nl
    else:
        # wrapper vault (e.g. Mellow): ERC4626-like reads
        d["symbol"] = s(v)
        d["asset"] = a(v, "asset()")
        if d["asset"]:
            d["asset_symbol"] = s(d["asset"])
            ad = u(d["asset"], "decimals()") or 18
            x = u(v, "totalAssets()")
            d["totalAssets"] = x / 10 ** ad if x is not None else None
        x = u(v, "totalSupply()")
        d["totalSupply_raw"] = x
        d["decimals"] = u(v, "decimals()")
        for f in ["symbioticVault()", "vault()", "symbioticAdapter()"]:
            d[f] = a(v, f)
    sv[name] = d
R["reads"]["symbiotic_vaults"] = sv

# ---------------- EigenLayer core and ZRO strategy ----------------
eg = {}
DM = "0x39053D51B77DC0d36036Fc1fCc8Cb819df8Ef37A"
AM = "0x948a420b8CC1d6BFd0B6087C2E7c344a2CD0bc39"
SF = "0x5e4C39Ad7A3E881585e383dB9827EB4811f6F647"
eg["DelegationManager.minWithdrawalDelayBlocks"] = u(DM, "minWithdrawalDelayBlocks()")
eg["AllocationManager.DEALLOCATION_DELAY"] = u(AM, "DEALLOCATION_DELAY()")
eg["AllocationManager.ALLOCATION_CONFIGURATION_DELAY"] = u(AM, "ALLOCATION_CONFIGURATION_DELAY()")
zs = a(SF, "deployedStrategies(address)", ["address"], [TOK["ZRO"]])
eg["ZRO_strategy"] = zs
if zs and zs != "0x" + "0" * 40:
    eg["ZRO_strategy_balance"] = (bal(TOK["ZRO"], zs) or 0) / 1e18
    eg["ZRO_strategy_totalShares"] = (u(zs, "totalShares()") or 0) / 1e18
R["reads"]["eigenlayer"] = eg

# ---------------- Bridge escrow cross-checks ----------------
esc = {}
esc["wormhole_portal"] = {
    "ETH": ethbal("0x3ee18B2214AAF55c03e8bA69F4dA8B5c3E1B1E21") / 1e18,
    "tokens": tokbals("0x3ee18B2214AAF55c03e8bA69F4dA8B5c3E1B1E21", list(TOK.keys()))}
esc["axelar_gateway"] = {
    "tokens": tokbals("0x4F4495243837681061C4743b74B3eEdf548D56A5", list(TOK.keys()))}
esc["usdt0_oadapter"] = {"tokens": tokbals("0x6C96dE32CEa08842dcc4058c14d3aaAD7Fa41dee", ["USDT"])}
esc["stargate_v2_usdc_pool"] = {"tokens": tokbals("0xc026395860Db2d07ee33e05fE50ed7bD583189C7", ["USDC"])}
esc["stargate_v2_usdt_pool"] = {"tokens": tokbals("0x933597a323Eb81cAe705C5bC29985172fd5A3973", ["USDT"])}
esc["stargate_v2_eth_pool"] = {"ETH": ethbal("0x77b2043768d28E9C9aB44E1aBfC95944bcE57931") / 1e18}
R["reads"]["escrows"] = esc

# ---------------- CCIP lock-release pools on Ethereum ----------------
tok = json.load(open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "ccip", "lanes_current", "tokens.json"),
                     encoding="utf-8"))
cc = []
for sym, chains in tok.items():
    v = chains.get("mainnet")
    if not v or v.get("poolType") == "burnMint":
        continue
    b = bal(v["tokenAddress"], v["poolAddress"])
    cc.append({"symbol": sym, "poolType": v.get("poolType"),
               "typeAndVersion": v.get("typeAndVersion"),
               "token": v["tokenAddress"], "pool": v["poolAddress"],
               "decimals": v.get("decimals"),
               "balance": (b or 0) / 10 ** int(v.get("decimals") or 18)})
R["reads"]["ccip_eth_pools"] = cc

ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
R["finished_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
with open(os.path.join(OUT, f"eth_reads_{ts}.json"), "w", encoding="utf-8") as f:
    json.dump(R, f, indent=1)
E.dump(os.path.join(OUT, f"eth_calllog_{ts}.json"), {"block": blk})
print("block", blk)
print(json.dumps({k: v for k, v in R["reads"].items() if k != "ccip_eth_pools"}, indent=1)[:12000])
print("ccip pools read:", len(cc), "nonzero:", sum(1 for x in cc if x["balance"] > 0))
