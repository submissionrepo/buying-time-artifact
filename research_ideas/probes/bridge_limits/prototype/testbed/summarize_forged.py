"""Summarize the forged-deposit episodes (run_forged.py -> logs/forged_<fid>_d<Bd>_k<k>.json).

For each monitor (value_check False: matches requests to the recorded deposit; True: also requires the
deposit's transaction to have moved the amount into the source escrow) and each limiter (L0: bucket,
no hold; L10: 10-minute hold, then the bucket; T0: tuned, buckets in series): episodes, alarms, the time
from the first forged request to detection and to the pause's block, and the value released before the
pause (or by the end of the episode when there was none). Writes ../../results/testbed_forged.json.
"""
import json
import os
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))


def stats(xs):
    xs = [x for x in xs if x is not None]
    return {"n": len(xs), "min": min(xs), "median": statistics.median(xs), "max": max(xs)} if xs else {"n": 0}


def main(path):
    d = json.load(open(path, encoding="utf-8"))
    out = {"source": os.path.basename(path), "fid": d["fid"], "Bd": d["Bd"], "k": d["k"], "P": d["P"],
           "n_points": len(d["points"]), "monitors": {}}
    for vc in (False, True):
        eps = [e for e in d["episodes"] if e.get("value_check") == vc]
        m = {"episodes": len(eps), "alarms": sum(e["n_alarms"] for e in eps),
             "alarm_reasons": sorted({r for e in eps for r in e["alarm_reasons"]}),
             "episodes_with_alarm": sum(e["n_alarms"] > 0 for e in eps), "limiters": {}}
        for name in ("L0", "L10", "T0"):
            rows = [e["limiters"][name] for e in eps if name in e["limiters"]]
            m["limiters"][name] = {
                "n": len(rows),
                "detect_s": stats([r.get("detect_s") for r in rows]),
                "pause_s": stats([r.get("pause_s") for r in rows]),
                "released_before_pause_usd": stats([r.get("released_before_pause_usd") for r in rows]),
                "released_total_usd": stats([r.get("released_total_usd") for r in rows]),
                "requested_usd": stats([r.get("requested_usd") for r in rows]),
                "n_cancel_legit": sum(r.get("n_cancel_legit", 0) for r in rows)}
        out["monitors"]["value_check" if vc else "record_match"] = m
    dst = os.path.join(ROOT, "results", "testbed_forged.json")
    json.dump(out, open(dst, "w", encoding="utf-8"), indent=1)
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "logs", "forged_E25_d12_k64.json"))
