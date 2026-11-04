"""Snapshot of the live Wormhole Governor state from the Wormholescan API.

Usage:
    python -I governor_snapshot.py --out <dir>

Saves each response with its URL and UTC access time to <dir>/governor_snapshot_<UTC>.json.
These endpoints report current state only; there is no history endpoint.
"""
import argparse
import datetime as dt
import json
import sys
import time
from pathlib import Path

import requests

ENDPOINTS = [
    "https://api.wormholescan.io/api/v1/governor/limit",
    "https://api.wormholescan.io/api/v1/governor/config",
    "https://api.wormholescan.io/api/v1/governor/notional/available",
    "https://api.wormholescan.io/api/v1/governor/enqueued_vaas/",
    "https://api.wormholescan.io/v1/governor/token_list",
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    snap = {}
    for url in ENDPOINTS:
        t = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
        try:
            r = requests.get(url, timeout=120)
            body = r.json() if r.headers.get("content-type", "").startswith("application/json") else r.text
            snap[url] = {"accessed_utc": t, "status": r.status_code, "body": body}
        except requests.RequestException as e:
            snap[url] = {"accessed_utc": t, "status": None, "error": repr(e)}
        time.sleep(1.5)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = out / f"governor_snapshot_{stamp}.json"
    path.write_text(json.dumps(snap, indent=1), encoding="utf-8")
    print(path)


if __name__ == "__main__":
    sys.exit(main())
