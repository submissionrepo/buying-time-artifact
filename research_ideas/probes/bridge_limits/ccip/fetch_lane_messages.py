"""Full message history for each selected token-lane (ccip/selection.json), using the CCIP API v2
filters sourceChainSelector, destChainSelector and sourceTokenAddress, back to the first message.
Each lane goes to data/ccip/messages_lane/<src>__<dst>__<token>/ via fetch_messages.py.

Run: python -I fetch_lane_messages.py
"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pandas as pd  # noqa: E402

import ccip_common as cc  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    sel = cc.load_json(os.path.join(HERE, "selection.json"))["lanes"]
    chains = cc.load_json(os.path.join(cc.DATA, "lanes_current", "chains.json"))
    key2sel, _ = cc.selector_maps(chains)
    df = pd.read_csv(os.path.join(cc.DERIVED, "transfers.csv.gz"), compression="gzip", dtype=str)
    for L in sel:
        src, dst, tok = L["src"], L["dst"], L["token"]
        addrs = sorted(set(df[(df.src == src) & (df.dst == dst) & (df.token == tok)].token_addr))
        for addr in addrs:
            tag = f"{src}__{dst}__{tok}".replace("*", "_api")
            if len(addrs) > 1:
                tag += "__" + addr[-6:]
            out = os.path.join(cc.DATA, "messages_lane", tag)
            cmd = [sys.executable, "-I", os.path.join(HERE, "fetch_messages.py"), "--out", out,
                   "--cutoff", "2023-01-01", "--sleep", "1.5",
                   "--source-selector", key2sel[src], "--dest-selector", key2sel[dst], "--token", addr]
            print(" ".join(cmd[3:]), flush=True)
            subprocess.run(cmd, check=True)


if __name__ == "__main__":
    main()
