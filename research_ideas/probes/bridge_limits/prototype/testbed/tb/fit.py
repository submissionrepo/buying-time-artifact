"""Bucket parameters fitted to a failed bridge's own release history, with the functions of
replay_perbridge.py (imported read-only): best_bucket_np on the fit window of origin 1
([t_fail - 120 d, t_fail - 30 d)), scaled by the margin."""
from __future__ import annotations

import csv
import math
import os
import sys

import numpy as np

BL = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))  # .../bridge_limits
sys.path.insert(0, BL)
sys.path.insert(0, os.path.join(BL, "ccip"))
sys.dont_write_bytecode = True  # do not write caches next to the imported scripts
import replay_perbridge as rp  # noqa: E402
from rolling_v2 import fifo_delays  # noqa: E402,F401

WAD = 10 ** 18
DAY = 86400.0


def failure_time(fid: str) -> float:
    for r in csv.DictReader(open(os.path.join(BL, "results", "incidents.csv"), encoding="utf-8")):
        if r["id"] == fid:
            return rp.ts(r["first_release_utc"])
    raise KeyError(fid)


def history(fid: str):
    """Priced legitimate releases of the bridge's single leg: (times, usd values), sorted."""
    t_fail = failure_time(fid)
    legs, counts = rp.load_history(os.path.join(BL, "data", "legit", f"{fid}.csv"), t_fail, fid=fid)
    assert len(legs) == 1, legs.keys()
    leg, (t, v) = next(iter(legs.items()))
    return t_fail, leg, t, v, counts


def fit_bucket(t, v, t_fail, D, margin=1.5, fit_win=(120 * DAY, 30 * DAY)):
    m = (t >= t_fail - fit_win[0]) & (t < t_fail - fit_win[1])
    b, r = rp.best_bucket_np(t[m], v[m], D)
    return margin * b, margin * r, int(m.sum())


def to_units(usd: float) -> int:
    """USD value -> test-token base units (18 decimals), rounded to the nearest unit."""
    return int(round(usd * 1e6)) * 10 ** 12


def bucket_units(B_usd, R_usd_per_s):
    """Capacity and refill per second in base units, rounded down (the deployed limit is not looser
    than the fitted one)."""
    return int(math.floor(B_usd * 1e6)) * 10 ** 12, int(math.floor(R_usd_per_s * 1e18))


if __name__ == "__main__":
    for fid in ("E25", "E15"):
        t_fail, leg, t, v, counts = history(fid)
        print(fid, leg, counts, "n", len(t), "value %.2fM" % (v.sum() / 1e6))
        for D in (600, 3600, 6 * 3600, 24 * 3600):
            B, R, n = fit_bucket(t, v, t_fail, D)
            print(f"  D={D/3600:.2f}h  B=${B/1e6:.3f}M  R=${R*3600/1e6:.3f}M/h  B+R*1h=${(B+R*3600)/1e6:.3f}M  B/R={B/R/3600 if R else float('inf'):.2f}h  fit n={n}")
