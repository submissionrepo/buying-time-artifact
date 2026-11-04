"""Coverage of the failure dataset against three published incident lists (2026-10-16).

Inputs, transcribed from the papers (column our_id: the id of our record, or none; class: why an entry
matches none of our 57 failures):
  wu_table6.csv      Wu et al., arXiv:2410.14493v2, Table 6 (49 attacks, June 2021 to September 2024)
  zhang_table4.csv   Zhang et al., RAID 2024, Table 4 (35 attacks, April 2021 to April 2024)
  lee_examples.csv   Lee et al., arXiv:2210.16209v1, the eight "Real World Example" subsections
Counts the entries matched to our 57 failures (results/incidents.csv, in_bridge_set = yes), to the
records of our universe that we left out, and to neither (with the reason), and our failures dated after
the last of the three lists. Writes ../results/coverage.json and prints it.
"""
import csv
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LISTS = {"wu": "wu_table6.csv", "zhang": "zhang_table4.csv", "lee": "lee_examples.csv"}
LAST_LIST_DATE = "2024-09-30"   # Wu et al.'s list ends in September 2024, the latest of the three


def main():
    inc = {r["id"]: r for r in csv.DictReader(open(os.path.join(ROOT, "results", "incidents.csv"), encoding="utf-8"))}
    ours = {i for i, r in inc.items() if r["in_bridge_set"] == "yes"}
    left = {i for i, r in inc.items() if r["in_bridge_set"] != "yes"}
    out = {"lists": {}, "matched_entries": 0, "left_out_entries": 0, "other_entries": 0, "entries": 0}
    matched_ids, other_reasons = set(), {}
    for name, f in LISTS.items():
        rows = list(csv.DictReader(open(os.path.join(HERE, f), encoding="utf-8")))
        m = [r for r in rows if r["our_id"] in ours]
        lo = [r for r in rows if r["our_id"] in left]
        rest = [r for r in rows if r["our_id"] not in ours and r["our_id"] not in left]
        assert all(r["our_id"] in ("none", "") for r in rest), [r["our_id"] for r in rest]
        for r in rest:
            other_reasons[r["class"]] = other_reasons.get(r["class"], 0) + 1
        matched_ids |= {r["our_id"] for r in m}
        out["lists"][name] = {"entries": len(rows), "in_our_failures": len(m), "in_left_out": len(lo), "other": len(rest)}
        out["entries"] += len(rows)
        out["matched_entries"] += len(m)
        out["left_out_entries"] += len(lo)
        out["other_entries"] += len(rest)
    out["other_reasons"] = other_reasons
    out["our_failures_in_some_list"] = len(matched_ids)
    out["our_failures_after_lists"] = sum(inc[i]["date"] > LAST_LIST_DATE for i in ours)
    json.dump(out, open(os.path.join(ROOT, "results", "coverage.json"), "w", encoding="utf-8"), indent=1)
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
