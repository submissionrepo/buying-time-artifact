"""CCIP: today's buckets against each lane's own traffic, inbound and outbound (2026-10-16).

For every studied lane and direction with a bucket today: the bucket's release within D
(b + r D, from the most permissive state) divided by E^(D), the smallest release within D of a
bucket that delays none of the lane's transfers (least concave majorant of the envelope,
min_r B(r) + r D over the whole history; analysis_core.best_bucket_exact).  Inbound uses
execution (receipt) times at the destination pool, the release point; outbound uses send
times.  Amounts in token units, so prices cancel.  Same inputs as rolling_v2.py.
Output: data/ccip/derived/inbound_mismatch.json.
"""
from __future__ import annotations

import json
import os
import sys

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
import analysis_core as ac  # noqa: E402

DS = {"1 h": 3600.0, "6 h": 21600.0}


def main():
    fr = json.load(open(os.path.join(ROOT, "data", "ccip", "derived", "flows_results.json"), encoding="utf-8"))
    tr = pd.read_csv(os.path.join(ROOT, "data", "ccip", "derived", "transfers.csv.gz"),
                     usecols=["message_id", "src", "dst", "token", "amount", "send_ts", "receipt_ts"]).drop_duplicates("message_id")
    out = []
    for lane in fr["results"]:
        sub = tr[(tr.src == lane["src"]) & (tr.dst == lane["dst"]) & (tr.token == lane["token"])]
        rec = {"lane": (lane.get("lane") or f"{lane['token']} {lane['src']} -> {lane['dst']}")}
        for direction, col in (("in", "receipt_ts"), ("out", "send_ts")):
            cur = (lane.get("current_bucket") or {}).get(direction) or {}
            s = sub.dropna(subset=[col]).sort_values(col)
            if not cur.get("enabled") or len(s) < 2:
                rec[direction] = None
                continue
            times = s[col].astype(float).tolist()
            vals = s.amount.astype(float).tolist()
            r = {}
            for k, D in DS.items():
                _, _, ehat = ac.best_bucket_exact(times, vals, D)
                r[k] = (cur["b"] + cur["r"] * D) / ehat if ehat > 0 else None
            rec[direction] = r
        out.append(rec)
    json.dump(out, open(os.path.join(ROOT, "data", "ccip", "derived", "inbound_mismatch.json"), "w", encoding="utf-8"), indent=1)
    for rec in out:
        print(rec["lane"], {d: ({k: round(v, 3) for k, v in rec[d].items()} if rec[d] else None) for d in ("in", "out")})


if __name__ == "__main__":
    main()
