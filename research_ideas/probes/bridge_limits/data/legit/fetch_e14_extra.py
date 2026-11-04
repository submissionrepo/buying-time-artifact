"""E14 extra legs: the BUSD manager (Ethereum and BSC) and the bridge multisig's executions.

Addresses are read by role from data/incidents/research/batch_H.json (onchain_refs of E14) and are
never printed. usage: python -I fetch_e14_extra.py <chain> <b0> <b1> [step]
"""
import json
import pathlib
import sys

BL = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BL / "incidents"))
from rpc import Rpc, TRANSFER, topic_addr  # noqa: E402


def refs():
    d = json.loads((BL / "data/incidents/research/batch_H.json").read_text(encoding="utf-8"))

    def walk(x):
        if isinstance(x, dict):
            if x.get("event_id") == "E14" and "onchain_refs" in x:
                yield x
            for v in x.values():
                yield from walk(v)
        elif isinstance(x, list):
            for v in x:
                yield from walk(v)
    out = {}
    for e in walk(d):
        for r in e["onchain_refs"]:
            role = r.get("role", "")
            if role.startswith("BUSD manager"):
                out["busd_manager"] = r["value"].lower()
            elif role.startswith("bridge multisig"):
                out["multisig"] = r["value"].lower()
    return out


if __name__ == "__main__":
    chain, b0, b1 = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
    step = int(sys.argv[4]) if len(sys.argv) > 4 else 5000
    a = refs()
    raw = BL / "data/legit/raw/E14"
    rpc = Rpc(chain)
    tag = "eth" if chain == "ethereum" else chain
    f = raw / f"busd_{tag}_transfers_{b0}_{b1}.json"
    if not f.exists():
        f.write_text(json.dumps(rpc.logs(None, [TRANSFER, topic_addr(a["busd_manager"])], b0, b1, step=step)))
    print("busd transfers", len(json.loads(f.read_text())), flush=True)
    f = raw / f"busd_{tag}_ownlogs_{b0}_{b1}.json"
    if not f.exists():
        f.write_text(json.dumps(rpc.logs(a["busd_manager"], [], b0, b1, step=step)))
    print("busd ownlogs", len(json.loads(f.read_text())), flush=True)
    f = raw / f"multisig_{tag}_ownlogs_{b0}_{b1}.json"
    if not f.exists():
        f.write_text(json.dumps(rpc.logs(a["multisig"], [], b0, b1, step=step)))
    print("multisig ownlogs", len(json.loads(f.read_text())), "calls", rpc.calls, flush=True)
