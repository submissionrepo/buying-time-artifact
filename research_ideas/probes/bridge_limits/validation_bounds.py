"""Bounds the model predicts for two failures that met a limit in force (paper Section 6), 2026-10-16.

The section compares, for each failure that met a rule, what the rule's placement, control and
shape predict with what left.  Two of the predictions are quantities; this script computes them
from the recorded rule state and the recorded releases.

Taiko bridge (E55).  The L1 bridge's QuotaManager gives ETH a quota of 1,000 per 86,400 s with
linear refill: available(t) = min(quota, available(t0) + quota * (t - t0) / period).  A message
processed at 19:03:59 UTC on 2026-06-21 consumed 999 ETH of the quota without moving ETH, so 1 ETH
was left (research batch_L, from a trace of block 25,367,938).  The model's bound on ETH released
from then to time t is 1 + 1000 * (t - t0) / 86,400.  The research notes also read the
QuotaManager at block 25,368,852 (the block before the first release, 12 s earlier): available
128.22 ETH, which the script checks against the formula.  Releases: the ETH entries of _E55_REL
in incidents/curation.py (25 releases, 277.97 ETH).  The bound is checked at every release, not
only the last.

Ronin bridge 2024 (E30).  The gateway state read at the block before the first release
(data/legit/E30_limits_state.json, an extract) gives each asset's lock threshold, daily limit and the
day's withdrawals so far.  A party that keeps each withdrawal below the lock threshold takes at
most the daily limit less the day's withdrawals that day.  Releases: the selected rows of
data/incidents/onchain/E30_eth.json (the gateway counts ether under the WETH entry).

Writes results/validation_bounds.json and prints it.
"""
import datetime as dt
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "incidents"))
import curation  # noqa: E402

UTC = dt.timezone.utc


def ts(s):
    return dt.datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


def taiko():
    quota, period = 1000.0, 86400.0
    t0, left0 = ts("2026-06-21T19:03:59Z"), quota - 999.0
    read_t, read_avail = ts("2026-06-21T22:07:11Z"), 128.22   # block 25,368,852, research batch_L

    def bound(t):
        return min(quota, left0 + quota * (t - t0).total_seconds() / period)

    eth = sorted((ts(t), q) for t, q, a in curation._E55_REL if a == "ETH")
    cum, worst = 0.0, 0.0
    for t, q in eth:
        cum += q
        worst = max(worst, cum / bound(t))
    last_t = eth[-1][0]
    return {
        "quota_eth_per_day": quota,
        "refill_eth_per_hour": quota / 24.0,
        "left_after_t0": left0,
        "check_available_at_read": {"model": round(bound(read_t), 2), "onchain": read_avail},
        "n_eth_releases": len(eth),
        "first_eth_release": {"eth": eth[0][1], "bound": round(bound(eth[0][0]), 2)},
        "released_eth": round(cum, 2),
        "bound_at_last_release": round(bound(last_t), 2),
        "share_of_bound": cum / bound(last_t),
        "max_cumulative_over_bound": worst,
        "held_eth_about": 1285,
    }


def ronin():
    st = json.load(open(os.path.join(HERE, "data", "legit", "E30_limits_state.json"),
                        encoding="utf-8"))["state"]["before_first_release"]
    rows = json.load(open(os.path.join(HERE, "data", "incidents", "onchain", "E30_eth.json"),
                          encoding="utf-8"))["rows"]
    taken = {"WETH": 0.0, "USDC": 0.0}
    for r in rows:
        if not r.get("selected"):
            continue
        sym = "WETH" if r["symbol"] in ("ETH", "WETH") else r["symbol"]
        if sym in taken:
            taken[sym] += r["amount"]
    out = {}
    for tok in st["tokens"].values():
        sym = tok["symbol"]
        if sym not in taken:
            continue
        room = tok["dailyWithdrawalLimit_units"] - tok["lastSyncedWithdrawal_units"]
        out[sym] = {"lock_threshold": tok["lockedThreshold_units"],
                    "daily_limit": tok["dailyWithdrawalLimit_units"],
                    "withdrawn_that_day_before": tok["lastSyncedWithdrawal_units"],
                    "bound": room, "taken": taken[sym], "share_of_bound": taken[sym] / room,
                    "below_lock": taken[sym] < tok["lockedThreshold_units"]}
    return out


def main():
    res = {"E55_taiko": taiko(), "E30_ronin_2024": ronin()}
    tk = res["E55_taiko"]
    assert abs(tk["check_available_at_read"]["model"] - tk["check_available_at_read"]["onchain"]) < 0.01, tk
    assert tk["max_cumulative_over_bound"] <= 1.0, tk
    for v in res["E30_ronin_2024"].values():
        assert v["taken"] <= v["bound"] and v["below_lock"], v
    out = os.path.join(HERE, "results", "validation_bounds.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(res, fh, indent=2)
    print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
