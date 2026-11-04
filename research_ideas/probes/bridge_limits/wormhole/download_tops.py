"""Download hourly outflow volume by source (emitter) chain from the Wormholescan API.

Endpoint: GET https://api.wormholescan.io/api/v1/x-chain-activity/tops
          ?timespan=1h&from=<RFC3339>&to=<RFC3339>[&appId=<APP>]
Each row: {from, to, emitter_chain, volume, count}; `to` is exclusive, hours with no
transfers are omitted, `volume` is USD x 1e8 (checked against per-operation usdAmount).

Usage:
    python -I download_tops.py --out <dir> --series portal|all [--start 2021-09-01]
                               [--end 2026-10-15T16:00:00Z] [--chunk-days 10]

series=portal -> appId=PORTAL_TOKEN_BRIDGE (the Token Bridge, the only app the
Governor meters); series=all -> no appId filter (every Wormhole app with a USD value);
series=cctp_v2 -> appId=CCTP_V2.  From May 2025 the API counts CCTP v2 transfers relayed
by the Wormhole executor under every appId filter, so the Token Bridge series is
PORTAL_TOKEN_BRIDGE minus CCTP_V2 (checked: September 2026 difference = 90.80M USD and
38,386 messages, equal to /api/v1/application-activity for the Token Bridge).

Raw responses are saved one file per chunk under <out>/raw_tops_<series>/ and are
reused on rerun (resumable).  A manifest with the request URL, UTC access time, HTTP
status and row count of every chunk is written to <out>/tops_<series>_manifest.json,
and the combined table to <out>/tops_<series>_hourly.csv
(hour_utc, emitter_chain, volume_usd, count).
"""
import argparse
import csv
import datetime as dt
import json
import sys
import time
from pathlib import Path

import requests

BASE = "https://api.wormholescan.io/api/v1/x-chain-activity/tops"
UA = {"User-Agent": "research-probe (bridge outflow limits; contact via repository owner)"}


def iso(t):
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def fetch(params, max_tries=6):
    """GET with retries on 429/5xx and network errors; returns (status, json or None, url)."""
    wait = 5
    for k in range(max_tries):
        try:
            r = requests.get(BASE, params=params, headers=UA, timeout=180)
            url = r.url
            if r.status_code == 200:
                return 200, r.json(), url
            if r.status_code == 429 or r.status_code >= 500:
                ra = r.headers.get("Retry-After")
                sleep = float(ra) if ra and ra.replace(".", "").isdigit() else wait
                print(f"  HTTP {r.status_code}; retry {k + 1}/{max_tries} after {sleep:.0f}s", flush=True)
                time.sleep(sleep)
                wait = min(wait * 2, 120)
                continue
            return r.status_code, None, url
        except requests.RequestException as e:
            print(f"  network error {e!r}; retry {k + 1}/{max_tries} after {wait}s", flush=True)
            time.sleep(wait)
            wait = min(wait * 2, 120)
    return -1, None, None


def get_chunk(a, b, app, rawdir, log, sleep_s, min_hours=24):
    """Fetch [a, b); on persistent failure split in halves (down to min_hours)."""
    path = rawdir / f"{iso(a).replace(':', '')}_{iso(b).replace(':', '')}.json"
    if path.exists():
        rows = json.loads(path.read_text(encoding="utf-8"))
        log.append({"from": iso(a), "to": iso(b), "status": "cached", "rows": len(rows), "file": path.name})
        return rows
    params = {"timespan": "1h", "from": iso(a), "to": iso(b)}
    if app:
        params["appId"] = app
    t0 = dt.datetime.now(dt.timezone.utc)
    status, data, url = fetch(params)
    time.sleep(sleep_s)
    if status == 200 and isinstance(data, list):
        path.write_text(json.dumps(data), encoding="utf-8")
        log.append({"from": iso(a), "to": iso(b), "url": url, "accessed_utc": t0.isoformat(timespec="seconds"),
                    "status": status, "rows": len(data), "file": path.name})
        return data
    hours = (b - a).total_seconds() / 3600
    if hours / 2 >= min_hours:
        mid = a + (b - a) / 2
        mid = mid.replace(minute=0, second=0, microsecond=0)
        print(f"  splitting {iso(a)}..{iso(b)} after status {status}", flush=True)
        return (get_chunk(a, mid, app, rawdir, log, sleep_s, min_hours)
                + get_chunk(mid, b, app, rawdir, log, sleep_s, min_hours))
    log.append({"from": iso(a), "to": iso(b), "url": url, "accessed_utc": t0.isoformat(timespec="seconds"),
                "status": status, "rows": None, "file": None, "error": "failed"})
    print(f"  FAILED {iso(a)}..{iso(b)} status {status}", flush=True)
    return []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--series", choices=["portal", "all", "cctp_v2"], required=True)
    ap.add_argument("--start", default="2021-09-01T00:00:00Z")
    ap.add_argument("--end", default=None, help="exclusive; default = start of the current UTC hour")
    ap.add_argument("--chunk-days", type=float, default=10)
    ap.add_argument("--sleep", type=float, default=1.5)
    args = ap.parse_args()

    out = Path(args.out)
    rawdir = out / f"raw_tops_{args.series}"
    rawdir.mkdir(parents=True, exist_ok=True)
    app = {"portal": "PORTAL_TOKEN_BRIDGE", "all": None, "cctp_v2": "CCTP_V2"}[args.series]
    start = dt.datetime.fromisoformat(args.start.replace("Z", "+00:00"))
    if args.end:
        end = dt.datetime.fromisoformat(args.end.replace("Z", "+00:00"))
    else:
        end = dt.datetime.now(dt.timezone.utc).replace(minute=0, second=0, microsecond=0)

    log, rows = [], []
    a = start
    step = dt.timedelta(days=args.chunk_days)
    n = 0
    while a < end:
        b = min(a + step, end)
        got = get_chunk(a, b, app, rawdir, log, args.sleep)
        rows += got
        n += 1
        if n % 10 == 0:
            print(f"{args.series}: through {iso(b)}, {len(rows)} rows", flush=True)
        a = b

    # combine, check duplicates and bucket alignment
    seen, dup, misaligned = {}, 0, 0
    for r in rows:
        key = (r["from"], r["emitter_chain"])
        t_from = dt.datetime.fromisoformat(r["from"].replace("Z", "+00:00"))
        t_to = dt.datetime.fromisoformat(r["to"].replace("Z", "+00:00"))
        if t_to - t_from != dt.timedelta(hours=1) or t_from.minute or t_from.second:
            misaligned += 1
        if key in seen:
            dup += 1
            if seen[key] != (r["volume"], r["count"]):
                print(f"  conflicting duplicate {key}: {seen[key]} vs {(r['volume'], r['count'])}")
            continue
        seen[key] = (r["volume"], r["count"])
    with open(out / f"tops_{args.series}_hourly.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["hour_utc", "emitter_chain", "volume_usd", "count"])
        for (h, c), (v, k) in sorted(seen.items(), key=lambda kv: (kv[0][0], int(kv[0][1]))):
            w.writerow([h, c, f"{v / 1e8:.8f}", k])
    manifest = {
        "endpoint": BASE,
        "params": {"timespan": "1h", "appId": app},
        "start": iso(start), "end_exclusive": iso(end), "chunk_days": args.chunk_days,
        "n_chunks_logged": len(log), "n_rows": len(seen), "duplicates": dup, "misaligned": misaligned,
        "failed_chunks": [c for c in log if c.get("error")],
        "volume_units": "API volume field is USD x 1e8; CSV volume_usd = volume / 1e8",
        "chunks": log,
    }
    (out / f"tops_{args.series}_manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in manifest.items() if k != "chunks"}, indent=1))


if __name__ == "__main__":
    sys.exit(main())
