"""Axelar stake reads via public LCD (cosmos REST) and Axelarscan TVL.
Output: data/stake/api/axelar_reads_<UTC>.json plus raw files.
"""
import base64
import json
import os
import time
import urllib.request

API = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "stake", "api")
LCDS = ["https://axelar-rest.publicnode.com", "https://axelar-api.polkachu.com"]
SR = "axelar1rpj2jjrv3vpugx9ake9kgk3s2kgwt0y60wtkmcgfml5m3et0mrls6nct9m"
CHAINS = ['flow', 'sui', 'stellar', 'xrpl-evm', 'plume', 'hedera', 'berachain',
          'hyperliquid', 'monad', 'solana']
LOG = []


def get(path, data=None, base=None):
    last = None
    for b in ([base] if base else LCDS):
        url = b + path
        try:
            req = urllib.request.Request(url, data=data, headers={
                "User-Agent": "Mozilla/5.0", "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=90) as r:
                txt = r.read().decode()
            LOG.append({"utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                        "url": url, "bytes": len(txt)})
            return json.loads(txt)
        except Exception as e:
            last = (url, repr(e)[:200])
    raise RuntimeError(last)


def wasm(q):
    b64 = base64.b64encode(json.dumps(q).encode()).decode()
    return get(f"/cosmwasm/wasm/v1/contract/{SR}/smart/{b64}")


out = {"accessed_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
out["latest_block"] = get("/cosmos/base/tendermint/v1beta1/blocks/latest")["block"]["header"]
out["latest_block"] = {k: out["latest_block"][k] for k in ("chain_id", "height", "time")}
out["pool"] = get("/cosmos/staking/v1beta1/pool")
out["staking_params"] = get("/cosmos/staking/v1beta1/params")
out["slashing_params"] = get("/cosmos/slashing/v1beta1/params")
out["supply_uaxl"] = get("/cosmos/bank/v1beta1/supply/by_denom?denom=uaxl")
vals = get("/cosmos/staking/v1beta1/validators?status=BOND_STATUS_BONDED&pagination.limit=300")
toks = sorted([int(v["tokens"]) for v in vals["validators"]], reverse=True)
tot = sum(toks)
cum, k60, k35 = 0, None, None
for i, t in enumerate(toks):
    cum += t
    if k60 is None and cum > 0.6 * tot:
        k60 = (i + 1, cum)
out["validators"] = {"n_bonded": len(toks), "sum_tokens_uaxl": tot,
                     "top1_share": toks[0] / tot, "top5_share": sum(toks[:5]) / tot,
                     "min_validators_over_60pct": k60[0],
                     "min_stake_over_60pct_uaxl": k60[1],
                     "smallest_bonded_uaxl": toks[-1]}
# Amplifier service registry
out["amplifier_service"] = wasm({"service": {"service_name": "amplifier"}})
bonds = {}
per_chain = {}
for ch in CHAINS:
    try:
        r = wasm({"active_verifiers": {"service_name": "amplifier", "chain_name": ch}})
    except Exception as e:
        per_chain[ch] = repr(e)[:200]
        continue
    data = r.get("data", [])
    per_chain[ch] = len(data)
    for item in data:
        vi = item.get("verifier_info", item)
        addr = vi.get("address")
        bs = vi.get("bonding_state", {})
        amt = None
        for key in ("Bonded", "bonded", "RequestedUnbonding", "requested_unbonding"):
            if key in bs:
                amt = int(bs[key]["amount"])
        bonds[addr] = {"amount_uaxl": amt, "auth": vi.get("authorization_state"),
                       "weight": item.get("weight")}
out["amplifier_active_verifiers_per_chain"] = per_chain
out["amplifier_unique_verifiers"] = len(bonds)
out["amplifier_sum_bond_uaxl"] = sum(v["amount_uaxl"] or 0 for v in bonds.values())
out["amplifier_bonds"] = bonds
# Axelarscan TVL
tvl = get("/api/getTVL", data=b"{}", base="https://api.axelarscan.io")
with open(os.path.join(API, "axelarscan_getTVL_refresh.json"), "w", encoding="utf-8") as f:
    json.dump(tvl, f)
tot_v, by_type, by_part = 0, {}, {"evm_gateway_or_its": 0, "cosmos_escrow": 0, "amplifier": 0}
for x in tvl["data"]:
    v = x.get("value") or 0
    tot_v += v
    by_type[x.get("assetType")] = by_type.get(x.get("assetType"), 0) + v
    p = x.get("price") or 0
    by_part["evm_gateway_or_its"] += (x.get("total_on_evm") or 0) * p
    by_part["cosmos_escrow"] += (x.get("total_on_cosmos") or 0) * p
    by_part["amplifier"] += (x.get("total_on_amplifier") or 0) * p
out["axelarscan"] = {"updated_at_ms": tvl.get("updated_at"), "n_assets": len(tvl["data"]),
                     "sum_value_usd": tot_v, "by_assetType_usd": by_type,
                     "by_location_usd_price_x_amount": by_part}
out["log"] = LOG
ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
with open(os.path.join(API, f"axelar_reads_{ts}.json"), "w", encoding="utf-8") as f:
    json.dump(out, f, indent=1)
print(json.dumps({k: v for k, v in out.items() if k not in ("amplifier_bonds", "log")}, indent=1))
