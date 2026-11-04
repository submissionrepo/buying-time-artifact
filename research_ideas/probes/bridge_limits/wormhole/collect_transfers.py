"""Collect every complete cached Token Bridge window into one transfer table.

Usage:
    python -I collect_transfers.py --data <data/wormhole dir> [--table transfers_all.csv]
                                   [--covered covered_hours.csv]

Scans <data>/raw_vaas/<chain>_<from>_<to>/ (written by download_vaas.py and by
verify_subhour.py), keeps the windows whose pages are complete (the last page is short or
repeats earlier messages), and writes
  <data>/<table>    one row per transfer message (payload types 1 and 3), deduplicated on
                    (chain_id, sequence), columns as in download_vaas.COLS
  <data>/<covered>  chain_id, hour_utc of every hour inside a complete window: the hours
                    for which the per-transfer list is complete.
No wallet addresses or transaction hashes.
"""
import argparse
import re
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import download_vaas as dv  # noqa: E402

WID = re.compile(r"^(\d+)_(\d{4}-\d{2}-\d{2}T\d{6}Z)_(\d{4}-\d{2}-\d{2}T\d{6}Z)$")


def parse_t(s):
    return pd.Timestamp(f"{s[:13]}:{s[13:15]}:{s[15:17]}Z")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--table", default="transfers_all.csv")
    ap.add_argument("--covered", default="covered_hours.csv")
    args = ap.parse_args()
    data = Path(args.data)
    recs, cov, n_win, n_skip = [], set(), 0, 0
    for d in sorted((data / "raw_vaas").iterdir()):
        m = WID.match(d.name)
        if not m or not d.is_dir():
            continue
        cid, a, b = int(m.group(1)), parse_t(m.group(2)), parse_t(m.group(3))
        if cid not in dv.EMITTER or not dv.window_complete(d):
            n_skip += 1
            continue
        r, _ = dv.records_from_pages(d, d.name, cid, "")
        recs += r
        for h in pd.date_range(a, b - pd.Timedelta(hours=1), freq="h"):
            cov.add((cid, h))
        n_win += 1
    tr = pd.DataFrame(recs, columns=dv.COLS)
    tr["t"] = pd.to_datetime(tr["ts"], utc=True, format="ISO8601")
    n0 = len(tr)
    tr = tr.sort_values(["chain_id", "sequence", "window_id"]).drop_duplicates(["chain_id", "sequence"])
    # keep only messages inside a covered hour (a window's from/to filter is on the same timestamp)
    tr["hour"] = tr["t"].dt.floor("h")
    inside = [(c, h) in cov for c, h in zip(tr["chain_id"], tr["hour"])]
    tr = tr[inside]
    tr.drop(columns=["t", "hour"]).to_csv(data / args.table, index=False)
    cv = pd.DataFrame(sorted(cov), columns=["chain_id", "hour"])
    cv["hour_utc"] = cv["hour"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    cv[["chain_id", "hour_utc"]].to_csv(data / args.covered, index=False)
    print(f"windows used {n_win}, skipped {n_skip}; messages {n0}, unique transfers {len(tr)}; "
          f"covered chain-hours {len(cv)}")


if __name__ == "__main__":
    sys.exit(main())
