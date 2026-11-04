import json, os, sys, time, glob
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ethcall_lib as E
ONC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "stake", "onchain")
RD = json.load(open(sorted(glob.glob(os.path.join(ONC, "eth_reads_*.json")))[-1], encoding="utf-8"))
BLK = hex(RD["block"]["number"])
SM = "0x5e3Ef299fDDf15eAa0432E6e66473ace8c13D908"
rows = []
for vid in range(1, 210):
    r = E.eth_call(SM, "validators(uint256)", ["uint256"], [vid], block=BLK)
    w = E.words(r)
    amount, deact, status, delegated = E.as_uint(w[0]), E.as_uint(w[3]), E.as_uint(w[7]), E.as_uint(w[11])
    rows.append({"id": vid, "amount": amount / 1e18, "delegated": delegated / 1e18,
                 "deactivationEpoch": deact, "status": status})
act = [r for r in rows if r["status"] == 1 and r["deactivationEpoch"] == 0]
tot = sum(r["amount"] + r["delegated"] for r in act)
st = sorted([r["amount"] + r["delegated"] for r in act], reverse=True)
cum, k = 0, None
for i, x in enumerate(st):
    cum += x
    if cum > 2 / 3 * tot:
        k = (i + 1, cum)
        break
out = {"block": BLK, "n_active": len(act), "total_stake_POL": tot,
       "self_stake_POL": sum(r["amount"] for r in act),
       "delegated_POL": sum(r["delegated"] for r in act),
       "min_validators_over_2_3": k[0], "min_stake_over_2_3_POL": k[1],
       "top1_share": st[0] / tot, "rows": rows}
E.dump(os.path.join(ONC, "polygon_validators_calllog_" + time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + ".json"), {"block": BLK})
with open(os.path.join(ONC, "polygon_validators_" + time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + ".json"), "w", encoding="utf-8") as f:
    json.dump(out, f, indent=1)
print({k_: v for k_, v in out.items() if k_ != "rows"})
