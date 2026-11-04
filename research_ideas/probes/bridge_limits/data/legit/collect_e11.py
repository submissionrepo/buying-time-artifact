"""E11 (Ethereum escrow leg of the token bridge): releases in the 150 days before the first unauthorized release.

Release paths (ethereum/contracts/bridge/Bridge.sol at wormhole 608c724, January 2022), _completeTransfer:
- tokens native to Ethereum: SafeERC20.safeTransfer(token, recipient or relayer) -> Transfer logs with the
  bridge as sender;
- completeTransferAndUnwrapETH: WETH.withdraw(amount) then a plain ETH transfer -> WETH Withdrawal logs with
  the bridge as src (one per fee leg and one per recipient leg). This is how native ETH outflows are captured;
  the bridge emits no release event of its own in this version.
- wrapped (non-Ethereum) assets are minted, not released from custody: out of scope for the escrow leg.
Raw logs are cached per block chunk under raw/E11/. Run: python -I collect_e11.py
"""
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent / "incidents"))
from rpc import Rpc, TRANSFER, WETH_WITHDRAWAL, topic_addr  # noqa: E402

RAW = HERE / "raw" / "E11"
RAW.mkdir(parents=True, exist_ok=True)
T = json.loads((HERE.parent / "incidents" / "onchain_targets.json").read_text())["E11_eth"]
BRIDGE = T["custody"][0].lower()
WETH = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"
FIRST_BAD = 1643826253  # 2022-02-02T18:24:13Z, results/incidents.csv first_release_utc
T_END = FIRST_BAD - 1
T_START = FIRST_BAD - 150 * 86400
STEP = 5000


def main():
    r = Rpc("ethereum")
    meta_p = RAW / "window.json"
    if meta_p.exists():
        meta = json.loads(meta_p.read_text())
    else:
        b0 = r.block_at(T_START, lo=12_500_000, hi=14_200_000)
        b1 = r.block_at(FIRST_BAD, lo=b0, hi=14_200_000) - 1
        meta = {"t_start": T_START, "t_end": T_END, "b0": b0, "b1": b1,
                "b0_ts": r.block_ts(b0), "b1_ts": r.block_ts(b1), "b1p1_ts": r.block_ts(b1 + 1)}
        meta_p.write_text(json.dumps(meta, indent=1))
    print(meta, flush=True)
    b = meta["b0"]
    while b <= meta["b1"]:
        e = min(b + STEP - 1, meta["b1"])
        f = RAW / f"chunk_{b}_{e}.json"
        if not f.exists():
            tr = r.logs(None, [TRANSFER, topic_addr(BRIDGE)], b, e, step=STEP)
            wd = r.logs(WETH, [WETH_WITHDRAWAL, topic_addr(BRIDGE)], b, e, step=STEP)
            f.write_text(json.dumps({"b0": b, "b1": e, "transfer": tr, "withdrawal": wd}))
            print(b, e, len(tr), len(wd), r.calls, flush=True)
        b = e + 1


if __name__ == "__main__":
    main()
