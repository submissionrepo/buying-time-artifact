"""E14: fetch raw logs for further escrow managers that the bridge multisig called with an unlock function.

Reads raw/E14/multisig_other_exec_<tag>.json (fetch_e14_multisig.py), keeps destinations whose executed call
is an unlock (unlockToken / unlockEth variants, not mint or NFT calls) and that are not already covered,
fetches Transfer-out logs and the manager's own logs, and records the managers in raw/E14/other_managers.json
(addresses stay in the raw cache). usage: python -I fetch_e14_other.py <ethereum|bsc> <b0> <b1> [step]
"""
import json
import pathlib
import sys
from collections import Counter

BL = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BL / "incidents"))
sys.path.insert(0, str(BL / "data/legit"))
from rpc import Rpc, TRANSFER, topic_addr, erc20_meta  # noqa: E402
from fetch_e14_extra import refs  # noqa: E402

UNLOCK_SELECTORS = {"5ed74114": "unlockToken(uint256,address,bytes32)",
                    "fe7f61ea": "unlockToken(address,uint256,address,bytes32)",
                    "973ff2e0": "unlockEth(uint256,address,bytes32)",
                    "1486abd6": "unlockOne(uint256,address,bytes32)"}
RAW = BL / "data/legit/raw/E14"

chain, b0, b1 = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
step = int(sys.argv[4]) if len(sys.argv) > 4 else 10000
tag = "eth" if chain == "ethereum" else chain
t = json.loads((BL / "data/incidents/onchain_targets.json").read_text())["E14_eth"]
r = refs()
known = {r["busd_manager"], r["multisig"]} | ({a.lower() for a in t["custody"]} if chain == "ethereum" else set())
ex = json.loads((RAW / f"multisig_other_exec_{tag}.json").read_text())
sel = Counter((v["dest"], v["selector"]) for v in ex.values())
print({(k[1], n) for k, n in sel.items()})
dests = sorted({d for (d, s) in sel if s in UNLOCK_SELECTORS and d not in known})
of = RAW / "other_managers.json"
others = json.loads(of.read_text()) if of.exists() else []
rpc = Rpc(chain)
if chain == "bsc":
    rpc.urls = rpc.urls[:1]
for k, d in enumerate(dests):
    pre = f"other_{tag}_{k}"
    f1 = RAW / f"{pre}_transfers_{b0}_{b1}.json"
    if not f1.exists():
        f1.write_text(json.dumps(rpc.logs(None, [TRANSFER, topic_addr(d)], b0, b1, step=step)))
    f2 = RAW / f"{pre}_ownlogs_{b0}_{b1}.json"
    if not f2.exists():
        f2.write_text(json.dumps(rpc.logs(d, [], b0, b1, step=step)))
    tr = json.loads(f1.read_text())
    toks = Counter(x["address"].lower() for x in tr)
    syms = [erc20_meta(rpc, tk, {})[0] for tk, _ in toks.most_common(3)]
    sels = sorted({UNLOCK_SELECTORS[s] for (dd, s) in sel if dd == d and s in UNLOCK_SELECTORS})
    native = any("Eth" in s or "One" in s for s in sels)
    label = (f"{'native-coin' if native else '/'.join(syms) or 'token'} manager (escrow"
             f"{', BSC' if chain == 'bsc' else ''}; not in the failure's targets)")
    others = [o for o in others if o["pre"] != pre] + [{"pre": pre, "chain": chain, "addr": d, "label": label,
                                                         "selectors": sels}]
    print(pre, label, "transfers", len(tr), "ownlogs", len(json.loads(f2.read_text())))
of.write_text(json.dumps(others, indent=1))
