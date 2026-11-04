"""Fetch Transfer-out logs and the contract's own logs for release-point contracts (raw cache).

usage: python -I fetch_logs.py <ID> <target_key> <b0> <b1> [chain]
Writes data/legit/raw/<ID>/<role>_transfers_<b0>_<b1>.json and <role>_ownlogs_<b0>_<b1>.json.
Addresses are read from data/incidents/onchain_targets.json and never printed.
"""
import json
import pathlib
import sys

BL = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BL / "incidents"))
from rpc import Rpc, TRANSFER, topic_addr  # noqa: E402

ID, key, b0, b1 = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
chain = sys.argv[5] if len(sys.argv) > 5 else "ethereum"
t = json.loads((BL / "data/incidents/onchain_targets.json").read_text())[key]
out = BL / "data/legit/raw" / ID
out.mkdir(parents=True, exist_ok=True)
rpc = Rpc(chain)
for i, c in enumerate(t["custody"]):
    role = f"custody{i}"
    f1 = out / f"{role}_transfers_{b0}_{b1}.json"
    if not f1.exists():
        lg = rpc.logs(None, [TRANSFER, topic_addr(c)], b0, b1, step=10000)
        f1.write_text(json.dumps(lg))
    print(role, "transfers", len(json.loads(f1.read_text())), flush=True)
    f2 = out / f"{role}_ownlogs_{b0}_{b1}.json"
    if not f2.exists():
        lg = rpc.logs(c, [], b0, b1, step=10000)
        f2.write_text(json.dumps(lg))
    print(role, "ownlogs", len(json.loads(f2.read_text())), "rpc calls", rpc.calls, flush=True)
