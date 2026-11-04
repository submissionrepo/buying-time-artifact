"""E16 (BSC Token Hub): collect releases from the hub in the 150 days before the first unauthorized release.

Releases (TokenHub.sol at bsc-genesis-contract a745ecc, the version in force in 2022):
- BNB credits: transferInSuccess(address bep20Addr, address refundAddr, uint256 amount) with bep20Addr = 0
  (the second word is the recipient), and refundSuccess(address,address,uint256,uint32) with bep20Addr = 0
  (refunds of failed outbound transfers). Both are emitted only after the BNB call succeeded.
- BEP20 releases: Transfer logs with the hub as sender (transferIn and refunds of bound BEP20 tokens).
- Excluded: rewardTo (relayer fee payouts through the RelayerIncentivize system contract) and
  withdrawStakingBNB (hub to staking system contract, no event); both are system-internal.
Raw logs are cached per block chunk under raw/E16/ (gzip, log fields trimmed to address, topics, data,
block, timestamp, transaction, log index). Run: python -I collect_e16.py [shard nshards]
"""
import gzip
import json
import pathlib
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent / "incidents"))
from rpc import Rpc, TRANSFER, topic_addr  # noqa: E402

RAW = HERE / "raw" / "E16"
RAW.mkdir(parents=True, exist_ok=True)
T = json.loads((HERE.parent / "incidents" / "onchain_targets.json").read_text())["E16_bsc"]
HUB = T["hub"].lower()
FIRST_BAD = 1665080806  # 2022-10-06T18:26:46Z, results/incidents.csv first_release_utc
T_END = FIRST_BAD - 1
T_START = FIRST_BAD - 150 * 86400
STEP = 20000


KEEP = ("address", "topics", "data", "blockNumber", "blockTimestamp", "transactionHash", "logIndex")


def slim(logs):
    return [{k: lg.get(k) for k in KEEP} for lg in logs]


def main():
    shard, nsh = (int(sys.argv[1]), int(sys.argv[2])) if len(sys.argv) > 2 else (0, 1)
    r = Rpc("bsc")
    r.urls = r.urls[:1]  # NodeReal only: the fallback endpoint caps logs at 50 blocks and a daily quota
    _call = r.call

    def call(method, params, retries=12):
        for k in range(8):
            try:
                return _call(method, params, retries=retries)
            except RuntimeError as e:
                if "429" not in str(e) or k == 7:
                    raise
                time.sleep(30 * (k + 1))
    r.call = call
    meta_p = RAW / "window.json"
    if meta_p.exists():
        meta = json.loads(meta_p.read_text())
    else:
        b0 = r.block_at(T_START, lo=17_000_000, hi=T["block_from"])
        b1 = r.block_at(FIRST_BAD, lo=b0, hi=T["block_to"]) - 1
        meta = {"t_start": T_START, "t_end": T_END, "b0": b0, "b1": b1,
                "b0_ts": r.block_ts(b0), "b1_ts": r.block_ts(b1), "b1p1_ts": r.block_ts(b1 + 1)}
        meta_p.write_text(json.dumps(meta, indent=1))
    print(meta, flush=True)
    b = meta["b0"]
    k = 0
    while b <= meta["b1"]:
        e = min(b + STEP - 1, meta["b1"])
        f = RAW / f"chunk_{b}_{e}.json.gz"
        if k % nsh == shard and not f.exists():
            hub_logs = slim(r.logs(HUB, [], b, e, step=STEP))
            tr_logs = slim(r.logs(None, [TRANSFER, topic_addr(HUB)], b, e, step=STEP))
            tmp = f.with_suffix(".tmp")
            with gzip.open(tmp, "wt") as fh:
                json.dump({"b0": b, "b1": e, "hub": hub_logs, "transfer": tr_logs}, fh)
            tmp.replace(f)
            print(b, e, len(hub_logs), len(tr_logs), r.calls, flush=True)
        b = e + 1
        k += 1


if __name__ == "__main__":
    main()
