"""List every commit touching CCIP mainnet lanes.json since --since (GitHub API, paged), and
optionally download lanes.json at given commits from raw.githubusercontent.com.

  python -I fetch_lanes_commits.py list --since 2024-07-01
  python -I fetch_lanes_commits.py get <sha> [<sha> ...]
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import requests  # noqa: E402

import ccip_common as cc  # noqa: E402
from fetch_lanes_history import REPO, PATH, UA, gh_get, raw_get  # noqa: E402

OUT = os.path.join(cc.DATA, "lanes_history")


def list_commits(since):
    out, page = [], 1
    while True:
        r = gh_get(f"https://api.github.com/repos/{REPO}/commits",
                   {"path": f"{PATH}/lanes.json", "since": f"{since}T00:00:00Z", "per_page": 100, "page": page})
        js = r.json()
        out += [{"sha": c["sha"], "date": c["commit"]["committer"]["date"],
                 "msg": c["commit"]["message"].splitlines()[0][:100]} for c in js]
        print(page, len(js), r.headers.get("X-RateLimit-Remaining"), flush=True)
        if len(js) < 100:
            break
        page += 1
        time.sleep(1.0)
    out.sort(key=lambda c: c["date"])
    json.dump({"accessed_utc": cc.utcnow(), "since": since, "commits": out},
              open(os.path.join(OUT, "commits.json"), "w", encoding="utf-8"), indent=1)
    print(len(out), "commits", out[0]["date"] if out else None, out[-1]["date"] if out else None)


def get(shas):
    for sha in shas:
        d = os.path.join(OUT, "by_sha", sha)
        p = os.path.join(d, "lanes.json")
        if os.path.exists(p):
            continue
        os.makedirs(d, exist_ok=True)
        n = raw_get(sha, "lanes.json", p)
        print(sha[:10], n, flush=True)
        time.sleep(0.5)


if __name__ == "__main__":
    if sys.argv[1] == "list":
        list_commits(sys.argv[sys.argv.index("--since") + 1] if "--since" in sys.argv else "2024-07-01")
    else:
        get(sys.argv[2:])
