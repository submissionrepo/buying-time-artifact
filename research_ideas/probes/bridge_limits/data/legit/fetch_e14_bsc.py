"""E14 BSC leg: raw logs for the BUSD manager (same address as on Ethereum) and the bridge multisig's
Execution events, over the BSC blocks of the 150-day window. Cached per 20,000-block chunk in
raw/E14/bsc_chunks/ and merged into busd_bsc_transfers_*, busd_bsc_ownlogs_*, multisig_bsc_ownlogs_*.
NodeReal only (the fallback endpoint caps logs at 50 blocks and has a small daily quota); HTTP 429 backs off.
usage: python -I fetch_e14_bsc.py
"""
import json
import pathlib
import sys
import time

BL = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BL / "incidents"))
sys.path.insert(0, str(BL / "data/legit"))
from rpc import Rpc, TRANSFER, topic_addr  # noqa: E402
from fetch_e14_extra import refs  # noqa: E402

B0, B1 = 14643287, 18937748
STEP = 20000
EXECUTION = "0x33e13ecb54c3076d8e8bb8c2881800a4d972b792045ffae98fdf46df365fed75"
RAW = BL / "data/legit/raw/E14"
CH = RAW / "bsc_chunks"
CH.mkdir(parents=True, exist_ok=True)


def main():
    a = refs()
    r = Rpc("bsc")
    r.urls = r.urls[:1]
    _call = r.call

    def call(method, params, retries=8):
        for k in range(8):
            try:
                return _call(method, params, retries=retries)
            except RuntimeError as e:
                if "429" not in str(e) or k == 7:
                    raise
                time.sleep(20 * (k + 1))
    r.call = call
    b = B0
    while b <= B1:
        e = min(b + STEP - 1, B1)
        f = CH / f"{b}_{e}.json"
        if not f.exists():
            d = {"tr": r.logs(None, [TRANSFER, topic_addr(a["busd_manager"])], b, e, step=STEP),
                 "own": r.logs(a["busd_manager"], [], b, e, step=STEP),
                 "ms": r.logs(a["multisig"], [EXECUTION], b, e, step=STEP)}
            f.write_text(json.dumps(d))
        b = e + 1
    tr, own, ms = [], [], []
    for f in sorted(CH.glob("*.json"), key=lambda p: int(p.stem.split("_")[0])):
        d = json.loads(f.read_text())
        tr += d["tr"]
        own += d["own"]
        ms += d["ms"]
    (RAW / f"busd_bsc_transfers_{B0}_{B1}.json").write_text(json.dumps(tr))
    (RAW / f"busd_bsc_ownlogs_{B0}_{B1}.json").write_text(json.dumps(own))
    (RAW / f"multisig_bsc_ownlogs_{B0}_{B1}.json").write_text(json.dumps(ms))
    print("bsc busd transfers", len(tr), "ownlogs", len(own), "multisig executions", len(ms), "calls", r.calls)


if __name__ == "__main__":
    main()
