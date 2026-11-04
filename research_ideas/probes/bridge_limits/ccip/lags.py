"""Send-to-execution lags of successful CCIP token transfers by source chain, 2026-10-16.

A legitimate transfer is executed on the destination only after the source chain's block is final
(CCIP waits for finality), so the lag from Ethereum is a wait that users of a lane already accept.
Reads data/ccip/derived/transfers.csv.gz; writes data/ccip/derived/lags.json with quantiles in
minutes for every source with at least 1,000 transfers.  A handful of lags near zero or negative
(manual re-executions, clock differences between the two chains' timestamps) sit below the 1st
percentile, which is why the paper quotes that percentile rather than the minimum.
"""
import json
import os

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
DER = os.path.join(HERE, "..", "data", "ccip", "derived")


def main():
    d = pd.read_csv(os.path.join(DER, "transfers.csv.gz"), usecols=["src", "status", "send_ts", "receipt_ts"])
    d = d[(d.status == "SUCCESS") & d.receipt_ts.notna()]
    d["lag_min"] = (d.receipt_ts - d.send_ts) / 60.0
    out = {}
    for src, x in d.groupby("src").lag_min:
        if len(x) < 1000:
            continue
        out[src] = {"n": int(len(x)), "p01": float(x.quantile(0.01)), "p10": float(x.quantile(0.10)),
                    "p50": float(x.median()), "p90": float(x.quantile(0.90))}
    json.dump(out, open(os.path.join(DER, "lags.json"), "w", encoding="utf-8"), indent=1)
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
