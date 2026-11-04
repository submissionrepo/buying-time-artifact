"""Typical Ethereum gas price over the 30 days before the stake-reading block (2026-10-16).

The paper converts the prototype's gas overhead to dollars.  This script samples
eth_feeHistory (1,024 blocks per call, 50th-percentile priority fee) at 30 points, one per
day, ending at block 26,201,369 (the block at which stakes were read), and records the median
base fee and the median priority fee over all sampled blocks.  The ETH price is the
DefiLlama price used for the stake valuation (data/stake/onchain/valuation_*.json).
Output: prototype/snapshots/gas_price.json.  Run with the Python environment of requirements.txt.
"""
import json
import pathlib
import statistics
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "incidents"))
from rpc import Rpc  # noqa: E402

END_BLOCK = 26_201_369
BLOCKS_PER_DAY = 7_200


def main():
    rpc = Rpc("ethereum")
    base, tip = [], []
    for k in range(30):
        newest = END_BLOCK - k * BLOCKS_PER_DAY
        fh = rpc.call("eth_feeHistory", [hex(1024), hex(newest), [50]])
        base += [int(x, 16) for x in fh["baseFeePerGas"][:-1]]
        tip += [int(r[0], 16) for r in fh["reward"]]
    val = sorted((ROOT / "data" / "stake" / "onchain").glob("valuation_*.json"))[-1]
    eth = json.loads(val.read_text(encoding="utf-8"))["prices_used"]["ethereum"]["llama"]
    out = {"end_block": END_BLOCK, "n_blocks": len(base),
           "base_fee_gwei_median": statistics.median(base) / 1e9,
           "base_fee_gwei_p90": sorted(base)[int(0.9 * len(base))] / 1e9,
           "priority_fee_gwei_median": statistics.median(tip) / 1e9,
           "eth_usd": eth, "eth_price_source": val.name}
    (HERE / "snapshots" / "gas_price.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    print(out)


if __name__ == "__main__":
    main()
