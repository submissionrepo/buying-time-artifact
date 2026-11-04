"""Crawl CCIP API v2 message search results (mainnet), newest first.

The API (https://api.ccip.chain.link/v2/messages) has no time-range filter, so
we page backwards with the cursor until the oldest message on a page is older
than --cutoff (or until there are no more pages).  Each raw page is stored as
gzipped JSON; a state file makes the crawl resumable.

Optional filters (passed through to the API and fixed for the whole crawl):
--source-selector, --dest-selector, --token (sourceTokenAddress).

Usage (always run with python -I):
  python -I fetch_messages.py --out <dir> --cutoff 2025-09-01 [--token 0x..]
"""
import argparse
import datetime as dt
import gzip
import json
import os
import sys
import time

import requests

API = "https://api.ccip.chain.link/v2/messages"
UA = {"User-Agent": "research-probe/0.1 (academic study of bridge rate limits)"}


def utcnow():
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_ts(s):
    return dt.datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=dt.timezone.utc)


def get_with_retry(params, log, max_tries=12):
    wait = 5.0
    for attempt in range(1, max_tries + 1):
        try:
            r = requests.get(API, params=params, headers=UA, timeout=180)
        except requests.RequestException as e:
            log(f"network error {type(e).__name__}: {e}; sleep {wait:.0f}s")
            time.sleep(wait)
            wait = min(wait * 2, 300)
            continue
        if r.status_code == 200:
            return r
        if r.status_code in (429, 500, 502, 503, 504):
            ra = r.headers.get("Retry-After")
            pause = float(ra) if ra and ra.replace(".", "", 1).isdigit() else wait
            log(f"HTTP {r.status_code}; sleep {pause:.0f}s (attempt {attempt})")
            time.sleep(pause)
            wait = min(wait * 2, 300)
            continue
        log(f"HTTP {r.status_code}: {r.text[:300]}")
        r.raise_for_status()
    raise RuntimeError("too many retries")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--cutoff", required=True, help="stop once a page reaches sendTimestamp < cutoff (UTC date)")
    ap.add_argument("--limit", type=int, default=1000)
    ap.add_argument("--sleep", type=float, default=1.5)
    ap.add_argument("--source-selector")
    ap.add_argument("--dest-selector")
    ap.add_argument("--token")
    ap.add_argument("--max-pages", type=int, default=100000)
    a = ap.parse_args()

    os.makedirs(a.out, exist_ok=True)
    state_path = os.path.join(a.out, "state.json")
    log_path = os.path.join(a.out, "crawl.log")
    logf = open(log_path, "a", encoding="utf-8")

    def log(msg):
        line = f"{utcnow()} {msg}"
        logf.write(line + "\n")
        logf.flush()
        print(line, flush=True)

    cutoff = dt.datetime.fromisoformat(a.cutoff).replace(tzinfo=dt.timezone.utc)
    filters = {"environment": "mainnet"}
    if a.source_selector:
        filters["sourceChainSelector"] = a.source_selector
    if a.dest_selector:
        filters["destChainSelector"] = a.dest_selector
    if a.token:
        filters["sourceTokenAddress"] = a.token

    if os.path.exists(state_path):
        state = json.load(open(state_path, encoding="utf-8"))
        if state.get("filters") != filters:
            sys.exit(f"state filters {state.get('filters')} differ from {filters}")
        log(f"resume at page {state['pages_done']} oldest {state.get('oldest_ts')}")
    else:
        state = {"filters": filters, "pages_done": 0, "cursor": None, "newest_ts": None,
                 "oldest_ts": None, "started_utc": utcnow(), "done": False, "messages": 0}

    if state.get("done"):
        if (state.get("stop_reason") == "cutoff" and state.get("cursor")
                and parse_ts(state["oldest_ts"]) >= cutoff):
            state["done"] = False
            log(f"extending crawl to new cutoff {a.cutoff}")
        else:
            log("already done")
            return

    while state["pages_done"] < a.max_pages:
        params = {"limit": a.limit}
        if state["cursor"]:
            params["cursor"] = state["cursor"]
        params.update(filters)
        t0 = time.time()
        r = get_with_retry(params, log)
        body = r.json()
        data = body.get("data", [])
        pag = body.get("pagination", {})
        n = state["pages_done"]
        with gzip.open(os.path.join(a.out, f"page_{n:05d}.json.gz"), "wt", encoding="utf-8") as f:
            json.dump({"fetched_utc": utcnow(), "params": params, "body": body}, f)
        state["pages_done"] = n + 1
        state["messages"] += len(data)
        if data:
            if state["newest_ts"] is None:
                state["newest_ts"] = data[0]["sendTimestamp"]
            state["oldest_ts"] = data[-1]["sendTimestamp"]
        state["cursor"] = pag.get("cursor")
        state["last_update_utc"] = utcnow()
        reached = bool(data) and parse_ts(data[-1]["sendTimestamp"]) < cutoff
        if not pag.get("hasNextPage") or not state["cursor"] or reached or not data:
            state["done"] = True
            state["stop_reason"] = "cutoff" if reached else "no more pages"
        json.dump(state, open(state_path, "w", encoding="utf-8"), indent=1)
        log(f"page {n} n={len(data)} oldest={state['oldest_ts']} total={state['messages']} "
            f"{time.time() - t0:.1f}s")
        if state["done"]:
            log(f"done: {state['stop_reason']}")
            break
        time.sleep(a.sleep)


if __name__ == "__main__":
    main()
