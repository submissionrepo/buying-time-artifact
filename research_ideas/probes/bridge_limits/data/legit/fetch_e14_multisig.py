"""E14: destinations of bridge-multisig executions that are not unlocks by the three known managers.

Reads the multisig and manager log caches in raw/E14/, calls the multisig's transactions(uint256) view
(current state) for each such execution, and caches destination, value and call selector in
raw/E14/multisig_other_exec_<chain>.json. Addresses stay in the raw cache.
usage: python -I fetch_e14_multisig.py [ethereum|bsc] <b0> <b1> [sample]
(sample: query only a seeded random sample of that many executions; used on BSC, where executions number
in the tens of thousands)
"""
import json
import pathlib
import sys

BL = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BL / "incidents"))
sys.path.insert(0, str(BL / "data/legit"))
from rpc import Rpc  # noqa: E402
from fetch_e14_extra import refs  # noqa: E402

UNLOCKED = "0xb24e65d2501e29a3ce014b0cc2283699c081ad27f10d64f036f96912b6f8943e"
EXECUTION = "0x33e13ecb54c3076d8e8bb8c2881800a4d972b792045ffae98fdf46df365fed75"

chain, b0, b1 = sys.argv[1], sys.argv[2], sys.argv[3]
tag = "eth" if chain == "ethereum" else chain
raw = BL / "data/legit/raw/E14"
mgr_files = [p for p in raw.glob(f"*_ownlogs_{b0}_{b1}.json") if not p.name.startswith("multisig")]
if chain != "ethereum":
    mgr_files = [p for p in raw.glob(f"*_{tag}_ownlogs_{b0}_{b1}.json") if not p.name.startswith("multisig")]
utx = set()
for p in mgr_files:
    for lg in json.loads(p.read_text()):
        if lg["topics"] and lg["topics"][0] == UNLOCKED:
            utx.add(lg["transactionHash"])
ms = json.loads((raw / f"multisig_{tag}_ownlogs_{b0}_{b1}.json").read_text())
ex = [lg for lg in ms if lg["topics"] and lg["topics"][0] == EXECUTION and lg["transactionHash"] not in utx]
if len(sys.argv) > 4:
    import random
    random.Random(14).shuffle(ex)
    ex = sorted(ex[:int(sys.argv[4])], key=lambda lg: int(lg["blockNumber"], 16))
out = raw / f"multisig_other_exec_{tag}.json"
cache = json.loads(out.read_text()) if out.exists() else {}
msig = refs()["multisig"]
rpc = Rpc(chain)
if chain == "bsc":
    import time
    rpc.urls = rpc.urls[:1]
    _call = rpc.call

    def _backoff(method, params, retries=6):
        for k in range(8):
            try:
                return _call(method, params, retries=retries)
            except RuntimeError as e:
                if "429" not in str(e) or k == 7:
                    raise
                time.sleep(20 * (k + 1))
    rpc.call = _backoff
for n, lg in enumerate(ex):
    txid = int(lg["topics"][1], 16) if len(lg["topics"]) > 1 else int(lg["data"], 16)
    if str(txid) in cache:
        continue
    r = rpc.call("eth_call", [{"to": msig, "data": "0x9ace38c2" + f"{txid:064x}"}, "latest"])
    d = r[2:]
    dest = "0x" + d[24:64]
    value = int(d[64:128], 16)
    off = int(d[128:192], 16) * 2
    ln = int(d[off:off + 64], 16)
    sel = d[off + 64:off + 72] if ln >= 4 else ""
    cache[str(txid)] = {"dest": dest, "value": value, "selector": sel, "ts": int(lg["blockTimestamp"], 16),
                        "tx": lg["transactionHash"]}
    if n % 100 == 0:
        out.write_text(json.dumps(cache))
out.write_text(json.dumps(cache))
print("executions without known-manager unlock:", len(ex), "cached:", len(cache), "rpc calls:", rpc.calls)
