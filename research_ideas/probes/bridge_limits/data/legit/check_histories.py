"""Check the rebuilt legitimate release histories before they enter replay_perbridge.py, 2026-10-16.

For every data/legit/<ID>.csv whose ID is a timed failure of the bridge set (results/incidents.csv):
rows, legs, assets, first and last timestamp, days covered against the 150-day window that ends one
second before the failure's first release, share of rows and of value priced, rows at or after the
first release (there must be none), largest single release against the failure's amount, and the
legitimate value per day.  Prints one block per history; writes nothing.
"""
import csv
import datetime as dt
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
UTC = dt.timezone.utc


def ts(s):
    s = s.strip().replace("Z", "")
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f"):
        try:
            return dt.datetime.strptime(s, fmt).replace(tzinfo=UTC)
        except ValueError:
            pass
    raise ValueError(s)


def main(ids):
    inc = {r["id"]: r for r in csv.DictReader(open(os.path.join(ROOT, "results", "incidents.csv"), encoding="utf-8"))}
    for i in ids:
        p = os.path.join(HERE, f"{i}.csv")
        r = inc.get(i)
        print(f"== {i} {r['name'][:60] if r else '(not in incidents)'}")
        if not r:
            continue
        print(f"   bridge set {r['in_bridge_set']}, timed {bool(r['response_delay_s'])}, amount {float(r['amount_usd'] or 0) / 1e6:.1f}M, "
              f"class {r['failure_class']}, first release {r['first_release_utc']}")
        rows = list(csv.DictReader(open(p, encoding="utf-8")))
        if not rows:
            print("   EMPTY")
            continue
        cols = list(rows[0].keys())
        t = [ts(x["ts_utc"]) for x in rows]
        first = ts(r["first_release_utc"]) if r["first_release_utc"] else None
        usd = [float(x["usd"]) if x.get("usd") not in (None, "", "nan") else 0.0 for x in rows]
        priced = [str(x.get("priced", "")).strip().lower() in ("true", "1", "yes") for x in rows]
        legs = {}
        for x, u in zip(rows, usd):
            legs.setdefault(x.get("leg", ""), [0, 0.0])
            legs[x.get("leg", "")][0] += 1
            legs[x.get("leg", "")][1] += u
        days = (max(t) - min(t)).total_seconds() / 86400
        start = first - dt.timedelta(days=150) if first else None
        after = sum(1 for x in t if first and x >= first)
        before_window = sum(1 for x in t if start and x < start)
        tot = sum(usd)
        print(f"   columns {cols}")
        print(f"   rows {len(rows):,}; {min(t):%Y-%m-%d %H:%M} to {max(t):%Y-%m-%d %H:%M} ({days:.1f} days); "
              f"window start {start:%Y-%m-%d} " if start else "", end="")
        print(f"rows at/after first release: {after}; before window: {before_window}")
        print(f"   priced rows {100 * sum(priced) / len(rows):.1f}%; value {tot / 1e6:,.1f}M; per day {tot / 150 / 1e6:.2f}M; "
              f"largest release {max(usd) / 1e6:.2f}M; failure / legit-per-day {float(r['amount_usd'] or 0) / max(tot / 150, 1):.1f}")
        for leg, (n, v) in sorted(legs.items(), key=lambda kv: -kv[1][1]):
            print(f"   leg {leg!r}: {n:,} rows, {v / 1e6:,.1f}M")
        kinds = {}
        for x in rows:
            kinds[x.get("kind", "")] = kinds.get(x.get("kind", ""), 0) + 1
        print(f"   kinds {kinds}")
        # gaps longer than 7 days hint at a collection that stopped early
        ts_sorted = sorted(t)
        gaps = sorted(((b - a).total_seconds() / 86400, a) for a, b in zip(ts_sorted, ts_sorted[1:]))[-3:]
        print("   longest gaps (days): " + ", ".join(f"{g:.1f} from {a:%Y-%m-%d}" for g, a in reversed(gaps)))


if __name__ == "__main__":
    main(sys.argv[1:] or ["E01", "E21", "E45", "E49", "E50", "E58", "E60", "E64"])
