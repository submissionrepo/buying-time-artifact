"""E11: native ETH sent by the token bridge (trace_filter, fromAddress = bridge) over the 150-day window.

Used to check the WETH Withdrawal capture in build_e11.py: every ETH payout of completeTransferAndUnwrapETH
is a plain call with value from the bridge; WETH deposits (bridge -> WETH) and dust refunds inside
wrapAndTransferETH also appear and are separated in build_e11.py.
Keeps only calls (callType "call") with value > 0, trimmed, gzip per chunk under raw/E11/traces/.
Run: python -I collect_e11_traces.py
"""
import gzip
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent / "incidents"))
from rpc import Rpc  # noqa: E402

RAW = HERE / "raw" / "E11"
OUT = RAW / "traces"
OUT.mkdir(parents=True, exist_ok=True)
T = json.loads((HERE.parent / "incidents" / "onchain_targets.json").read_text())["E11_eth"]
BRIDGE = T["custody"][0].lower()
STEP = 10000


def main():
    meta = json.loads((RAW / "window.json").read_text())
    rt = Rpc("ethereum_trace")
    b = meta["b0"]
    while b <= meta["b1"]:
        e = min(b + STEP - 1, meta["b1"])
        f = OUT / f"traces_{b}_{e}.json.gz"
        if not f.exists():
            xs = rt.trace_filter([BRIDGE], b, e, step=STEP)
            keep = []
            for x in xs:
                a = x.get("action", {})
                if x.get("type") != "call" or a.get("callType") != "call":
                    continue
                v = int(a.get("value", "0x0"), 16)
                if v == 0:
                    continue
                keep.append({"from": a.get("from"), "to": a.get("to"), "value": str(v), "block": x["blockNumber"],
                             "tx": x["transactionHash"], "trace": x.get("traceAddress"),
                             "input4": (a.get("input") or "")[:10], "error": x.get("error")})
            with gzip.open(f.with_suffix(".tmp"), "wt") as fh:
                json.dump({"b0": b, "b1": e, "n_all": len(xs), "calls": keep}, fh)
            f.with_suffix(".tmp").replace(f)
            print(b, e, len(xs), len(keep), rt.calls, flush=True)
        b = e + 1


if __name__ == "__main__":
    main()
