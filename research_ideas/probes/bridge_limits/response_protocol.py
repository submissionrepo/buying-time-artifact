"""How the first response was measured, and whether it varies with the time of the failure, 2026-10-16.

The paper takes each failure's first response as the earlier of the operator's first public
acknowledgment and the pause (results/incidents.csv, bridge set).  To show how much rests on
acknowledgments, this script reports, over the bridge-set failures with a recorded response:
- the basis of the first response (acknowledgment or pause), and where both are recorded, how
  often the pause came first and by how much;
- how many pauses are timed from the chain (pause_basis == 'onchain') and how many from a
  statement;
- the response time by the weekday and the UTC hour of the first release (weekend versus
  weekday, and the four six-hour blocks), with medians and a two-sided Mann-Whitney test for
  weekend versus weekday.
Writes results/response_protocol.json and prints it.
"""
import csv
import datetime as dt
import json
import os
import statistics

from scipy.stats import kruskal, mannwhitneyu

HERE = os.path.dirname(os.path.abspath(__file__))


def ts(s):
    return dt.datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc) if s else None


def main():
    rows = [r for r in csv.DictReader(open(os.path.join(HERE, "results", "incidents.csv"), encoding="utf-8"))
            if str(r["in_bridge_set"]).strip().lower() in ("true", "1", "yes")]
    timed = [r for r in rows if r["response_delay_s"]]
    out = {"n_bridge_set": len(rows), "n_timed": len(timed)}
    basis = {}
    for r in timed:
        basis[r["response_basis"]] = basis.get(r["response_basis"], 0) + 1
    out["response_basis"] = basis

    # from the lags of Table 2 (detection_lag_s, pause_lag_s), not the timestamps, so that the
    # counts reconcile with it: one pause (E47) is recorded as a lag stated by the operator, without a
    # timestamp; a pause known only as a bound from a third party's report (E32, pause_lag_bound_s)
    # is not a recorded pause
    both = []
    for r in timed:
        if r["detection_lag_s"] and r["pause_lag_s"]:
            a, p = float(r["detection_lag_s"]), float(r["pause_lag_s"])
            both.append({"id": r["id"], "pause_first": p <= a, "gap_h": (a - p) / 3600,
                         "pause_basis": r["pause_basis"]})
    out["n_pause_report_first"] = sum(r["response_basis"] == "pause report" for r in timed)
    out["n_pause_without_ack"] = sum(bool(r["pause_lag_s"]) and not r["detection_lag_s"] for r in timed)
    out["n_both_ack_and_pause"] = len(both)
    out["n_pause_before_ack"] = sum(b["pause_first"] for b in both)
    pf = [b["gap_h"] for b in both if b["pause_first"]]
    out["median_ack_after_pause_h"] = statistics.median(pf) if pf else None
    out["pause_basis_counts"] = {}
    for r in rows:
        if r["pause_utc"]:
            k = r["pause_basis"] or "unknown"
            out["pause_basis_counts"][k] = out["pause_basis_counts"].get(k, 0) + 1

    D = {r["id"]: float(r["response_delay_s"]) / 3600 for r in timed}
    first = {r["id"]: ts(r["first_release_utc"]) for r in timed if r["first_release_utc"]}
    wk = [D[i] for i in first if first[i].weekday() >= 5]
    wd = [D[i] for i in first if first[i].weekday() < 5]
    out["weekend"] = {"n": len(wk), "median_h": statistics.median(wk) if wk else None}
    out["weekday"] = {"n": len(wd), "median_h": statistics.median(wd) if wd else None}
    if wk and wd:
        out["weekend_vs_weekday_mannwhitney_p"] = float(mannwhitneyu(wk, wd, alternative="two-sided").pvalue)
    blocks = {}
    for i, t in first.items():
        b = f"{6 * (t.hour // 6):02d}-{6 * (t.hour // 6) + 6:02d} UTC"
        blocks.setdefault(b, []).append(D[i])
    out["by_hour_block"] = {b: {"n": len(v), "median_h": statistics.median(v)} for b, v in sorted(blocks.items())}
    out["hour_blocks_kruskal_p"] = float(kruskal(*[v for _, v in sorted(blocks.items())]).pvalue)
    json.dump(out, open(os.path.join(HERE, "results", "response_protocol.json"), "w", encoding="utf-8"), indent=1)
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
