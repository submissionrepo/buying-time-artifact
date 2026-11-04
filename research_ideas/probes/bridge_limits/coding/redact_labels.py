"""Remove every mention of an earlier class coding from coding/blind_input.csv (2026-10-16).

The blind input keeps the mechanism descriptions and sources but must not carry the earlier labels.
A scan found sentences that state an earlier recoding or alternative class readings (E06, E45, E49,
E69); they are removed here, and the scan is repeated so that nothing of the kind is left.
"""
import csv
import pathlib
import re

HERE = pathlib.Path(__file__).resolve().parent
p = HERE / "blind_input.csv"
rows = list(csv.DictReader(p.open(encoding="utf-8")))
cols = list(rows[0].keys())
PATTERNS = [
    re.compile(r"\s*Class re-coded from [SVDO] in the notes to [SVDO]:[^.]*\.(\s*\([^)]*\))?"),
    re.compile(r"\s*\((alternative readings|alternative) [SVDO][^)]*\)"),
    re.compile(r"\s*Alternative classes? [SVDO][^;.]*[;.]"),
    re.compile(r"\s*\(alternative [SVDO] if [^)]*\)\.?"),
]
CHECK = re.compile(r"(re-?coded|\bclass(es)? [SVDO]\b|\breadings? [SVDO]\b|\balternative [SVDO]\b|\bfrom [SVDO] in\b)", re.I)
changed = 0
for r in rows:
    for k in cols:
        v = r[k] or ""
        new = v
        for pat in PATTERNS:
            new = pat.sub("", new)
        new = re.sub(r"\s{2,}", " ", new).strip()
        if new != v:
            changed += 1
            r[k] = new
left = [(r["id"], k, r[k]) for r in rows for k in cols if CHECK.search(r[k] or "")]
with p.open("w", encoding="utf-8", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=cols)
    w.writeheader()
    w.writerows(rows)
print("fields changed:", changed)
for x in left:
    print("LEFT", x[0], x[1], x[2][:300])
