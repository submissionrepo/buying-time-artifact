"""Download monthly snapshots of CCIP lanes.json / tokens.json from the
smartcontractkit/documentation repository.

For each snapshot date D (first day of each month) we ask the GitHub API for the
last commit touching lanes.json before D (commits?path=...&until=D&per_page=1)
and download lanes.json and tokens.json at that commit from
raw.githubusercontent.com.  The current files on main are stored as "current".

Usage (run with python -I):
  python -I fetch_lanes_history.py --out <dir> --first 2024-10-01 --last 2026-10-01
"""
import argparse
import datetime as dt
import json
import os
import time

import requests

REPO = "smartcontractkit/documentation"
PATH = "src/config/data/ccip/v1_2_0/mainnet"
UA = {"User-Agent": "research-probe/0.1 (academic study of bridge rate limits)",
      "Accept": "application/vnd.github+json"}


def utcnow():
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def gh_get(url, params):
    for _ in range(6):
        r = requests.get(url, params=params, headers=UA, timeout=60)
        if r.status_code == 200:
            return r
        if r.status_code in (403, 429) and r.headers.get("X-RateLimit-Remaining") == "0":
            reset = int(r.headers.get("X-RateLimit-Reset", time.time() + 60))
            pause = max(5, reset - time.time() + 5)
            print(f"rate limited; sleeping {pause:.0f}s", flush=True)
            time.sleep(pause)
            continue
        if r.status_code >= 500:
            time.sleep(10)
            continue
        r.raise_for_status()
    raise RuntimeError(url)


def raw_get(sha, name, dest):
    url = f"https://raw.githubusercontent.com/{REPO}/{sha}/{PATH}/{name}"
    for _ in range(6):
        r = requests.get(url, headers={"User-Agent": UA["User-Agent"]}, timeout=120)
        if r.status_code == 200:
            open(dest, "wb").write(r.content)
            return len(r.content)
        if r.status_code == 404:
            return None
        time.sleep(10)
    raise RuntimeError(url)


def month_starts(first, last):
    y, m = first.year, first.month
    while (y, m) <= (last.year, last.month):
        yield dt.date(y, m, 1)
        m += 1
        if m == 13:
            y, m = y + 1, 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--first", default="2024-10-01")
    ap.add_argument("--last", default="2026-10-01")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    man_path = os.path.join(a.out, "manifest.json")
    manifest = json.load(open(man_path, encoding="utf-8")) if os.path.exists(man_path) else {}

    dates = [d.isoformat() for d in month_starts(dt.date.fromisoformat(a.first), dt.date.fromisoformat(a.last))]
    for d in dates + ["current"]:
        if d in manifest and manifest[d].get("lanes_bytes"):
            continue
        params = {"path": f"{PATH}/lanes.json", "per_page": 1}
        if d != "current":
            params["until"] = f"{d}T00:00:00Z"
        r = gh_get(f"https://api.github.com/repos/{REPO}/commits", params)
        js = r.json()
        if not js:
            manifest[d] = {"sha": None, "note": "no commit before date"}
            print(d, "no commit", flush=True)
            continue
        sha = js[0]["sha"]
        cdate = js[0]["commit"]["committer"]["date"]
        msg = js[0]["commit"]["message"].splitlines()[0][:120]
        sub = os.path.join(a.out, d)
        os.makedirs(sub, exist_ok=True)
        nl = raw_get(sha, "lanes.json", os.path.join(sub, "lanes.json"))
        nt = raw_get(sha, "tokens.json", os.path.join(sub, "tokens.json"))
        manifest[d] = {"sha": sha, "commit_date": cdate, "commit_msg": msg, "lanes_bytes": nl,
                       "tokens_bytes": nt, "accessed_utc": utcnow(),
                       "rate_remaining": r.headers.get("X-RateLimit-Remaining")}
        json.dump(manifest, open(man_path, "w", encoding="utf-8"), indent=1)
        print(d, sha[:10], cdate, nl, nt, r.headers.get("X-RateLimit-Remaining"), flush=True)
        time.sleep(1.0)


if __name__ == "__main__":
    main()
