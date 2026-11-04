"""E30: limit parameters of the Ethereum gateway read from contract state (2026-10-16).

Reads, by eth_call at fixed blocks, the per-token limit mappings of WithdrawalLimitation
(highTierThreshold, lockedThreshold, dailyWithdrawalLimit, unlockFeePercentages, lastSyncedWithdrawal,
lastDateSynced) and the vote thresholds (getThreshold, getHighTierVoteWeightThreshold, minimumVoteWeight).
Blocks: the block before the first unauthorized release (from data/legit/raw/E30/blocks.json), the block before
the upgrade that took effect 48.6 min earlier (block number from results/incidents.csv notes is not stored, so
it is passed on the command line), and the first block of the 150-day window.
Tokens: those released in the window (data/legit/raw/E30/token_meta.json).
Output: data/legit/raw/E30/limits_state.json (addresses as keys; the README quotes symbols only).
Run: python -I data/legit/read_e30_limits.py <block_before_upgrade>
"""
import json
import pathlib
import sys

from Crypto.Hash import keccak

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT / "incidents"))
from rpc import Rpc, topic_addr  # noqa: E402


def sel(sig):
    h = keccak.new(digest_bits=256)
    h.update(sig.encode())
    return "0x" + h.hexdigest()[:8]


PER_TOKEN = ["highTierThreshold", "lockedThreshold", "dailyWithdrawalLimit", "unlockFeePercentages",
             "lastSyncedWithdrawal", "lastDateSynced"]
GLOBAL = ["getThreshold", "getHighTierVoteWeightThreshold", "minimumVoteWeight", "paused"]


def words(r):
    r = r[2:]
    return [int(r[i:i + 64], 16) for i in range(0, len(r), 64)]


def main():
    cdir = HERE / "raw" / "E30"
    targets = json.loads((ROOT / "data" / "incidents" / "onchain_targets.json").read_text())
    gw = targets["E30_eth"]["custody"][0]
    b0, b1 = json.loads((cdir / "blocks.json").read_text())[:2]
    meta = json.loads((cdir / "token_meta.json").read_text())
    blocks = {"window_start": b0, "before_first_release": b1}
    if len(sys.argv) > 1:
        blocks["before_upgrade"] = int(sys.argv[1])
    rpc = Rpc("ethereum")
    rpc.urls = ["https://rpc.mevblocker.io", "https://mainnet.gateway.tenderly.co"]
    out = {"blocks": blocks, "state": {}}
    for label, b in blocks.items():
        st = {"block_ts": rpc.block_ts(b), "global": {}, "tokens": {}}
        for g in GLOBAL:
            try:
                st["global"][g] = words(rpc.eth_call(gw, sel(g + "()"), b))
            except Exception as e:
                st["global"][g] = f"error: {str(e)[:120]}"
        for tok, (sym, dec) in meta["meta"].items():
            if meta["nft"].get(tok):
                continue
            d = {"symbol": sym, "decimals": dec}
            for f in PER_TOKEN:
                data = sel(f + "(address)") + topic_addr(tok)[2:]
                try:
                    v = words(rpc.eth_call(gw, data, b))[0]
                    d[f] = v
                    if f not in ("unlockFeePercentages", "lastDateSynced"):
                        d[f + "_units"] = v / 10 ** dec
                except Exception as e:
                    d[f] = f"error: {str(e)[:120]}"
            st["tokens"][tok] = d
        out["state"][label] = st
    (cdir / "limits_state.json").write_text(json.dumps(out, indent=1))
    for label, st in out["state"].items():
        print("==", label, blocks[label], st["global"])
        for d in st["tokens"].values():
            print("  ", d["symbol"], {k: d.get(k + "_units", d.get(k)) for k in PER_TOKEN})


if __name__ == "__main__":
    main()
