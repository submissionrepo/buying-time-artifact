"""Per-transfer Token Bridge messages (VAAs) from Wormholescan for selected windows.

Endpoint: GET https://api.wormholescan.io/api/v1/vaas/<chain>/<token bridge emitter>
          ?from=<RFC3339>&to=<RFC3339>&parsedPayload=true&pageSize=100&page=<k>
Pages run newest first; pageSize is capped at 100.  The `from`/`to` filter and the
`timestamp` field are the VAA timestamp (the source-chain time of the message).
Unlike /api/v1/operations, whose records before about 2024 lack USD values and miss
some messages, this endpoint returned every message counted by the hourly series in the
hours tested.  It carries no USD value; value_transfers.py prices each transfer.

Usage:
    python -I download_vaas.py --out <data/wormhole dir> --windows <windows csv>
                               [--manifest vaas_manifest.json] [--table transfers_windows.csv]
                               [--sleep 1.2]
windows csv columns: chain_id, from, to, purpose[, core_from, core_to, ...]

Raw pages are cached under <out>/raw_vaas/<chain>_<from>_<to>/ (resumable; pages are
written atomically, and a window whose single hours were all cached by an earlier run is
assembled from those hours instead of being downloaded again).  The compact table
<out>/<table> has one row per transfer (payload types 1 and 3): window_id, purpose,
chain_id, sequence, ts, payload_type, amount_norm (8-decimal normalized), token_chain,
token_address_hex, to_chain, indexed_at (Wormholescan's indexing time of the signed VAA).
No wallet addresses or transaction hashes.  A call log with URLs and UTC access times goes
to <out>/<manifest>.
"""
import argparse
import csv
import datetime as dt
import json
import os
import sys
import time
from pathlib import Path

import pandas as pd
import requests

BASE = "https://api.wormholescan.io/api/v1/vaas"
# Token Bridge emitters (sdk/mainnet_consts.go, knownTokenbridgeEmitters)
EMITTER = {
    1: "ec7372995d5cc8732397fb0ad35c0121e0eaa90d26f828a534cab54391b3a4f5",
    2: "0000000000000000000000003ee18b2214aff97000d974cf647e7c347e8fa585",
    4: "000000000000000000000000b6f6d86a8f9879a9c87f643768d9efc38c1da6e7",
    5: "0000000000000000000000005a58505a96d1dbf8df91cb21b54419fc36e93fde",
    6: "0000000000000000000000000e082f06ff657d94310cb8ce8b0d9a04541d8052",
    21: "ccceeb29348f71bdd22ffef43a2a19c1f5b5e17c5cca5411529120182672ade5",
    22: "0000000000000000000000000000000000000000000000000000000000000001",
    23: "0000000000000000000000000b2402144bb366a632d14b83f244d2e0e21bd39c",
    30: "0000000000000000000000008d2de8d2f73f1f4cab472ac9a881c9b123c79627",
}
COLS = ["window_id", "purpose", "chain_id", "sequence", "ts", "payload_type", "amount_norm",
        "token_chain", "token_address_hex", "to_chain", "indexed_at"]
H = pd.Timedelta(hours=1)


def fetch(url, params, max_tries=6):
    wait = 5
    for k in range(max_tries):
        try:
            r = requests.get(url, params=params, timeout=180)
            if r.status_code == 200:
                return 200, r.json(), r.url
            if r.status_code == 429 or r.status_code >= 500:
                print(f"  HTTP {r.status_code}; retry {k + 1} after {wait}s", flush=True)
                time.sleep(wait)
                wait = min(wait * 2, 120)
                continue
            return r.status_code, None, r.url
        except requests.RequestException as e:
            print(f"  network error {e!r}; retry {k + 1} after {wait}s", flush=True)
            time.sleep(wait)
            wait = min(wait * 2, 120)
    return -1, None, None


def read_json(p, tries=5):
    """Read a cached page; tolerate a concurrent writer by retrying on a partial file."""
    for k in range(tries):
        try:
            return json.loads(Path(p).read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            if k == tries - 1:
                raise
            time.sleep(2)


def replace_retry(tmp, p, tries=20):
    """os.replace that waits out a transient Windows lock (a scanner or reader holding p)."""
    for k in range(tries):
        try:
            os.replace(tmp, p)
            return
        except PermissionError:
            if k == tries - 1:
                raise
            time.sleep(1.5)


def write_json_atomic(p, obj):
    p = Path(p)
    tmp = p.with_name(p.name + f".tmp{os.getpid()}")
    tmp.write_text(json.dumps(obj), encoding="utf-8")
    replace_retry(tmp, p)


def window_id(cid, a, b):
    return f"{cid}_{a.replace(':', '')}_{b.replace(':', '')}"


def fmt(t):
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def window_complete(wdir):
    """True if the cached pages of a window end with a short page (or a page of repeats)."""
    wdir = Path(wdir)
    if not wdir.is_dir():
        return False
    pages = sorted(wdir.glob("page_*.json"))
    if not pages:
        return False
    try:
        last = read_json(pages[-1])
    except (json.JSONDecodeError, OSError):
        return False
    if len(last) < 100:
        return True
    seen = set()
    for p in pages[:-1]:
        seen.update(v["id"] for v in read_json(p))
    return all(v["id"] in seen for v in last)


def records_from_pages(wdir, wid, cid, purpose):
    seen, recs = set(), []
    for p in sorted(Path(wdir).glob("page_*.json")):
        for v in read_json(p):
            if v["id"] in seen:
                continue
            seen.add(v["id"])
            recs.append(_record(v, wid, cid, purpose))
    return [r for r in recs if r is not None], len(seen)


def _record(v, wid, cid, purpose):
    pl = v.get("payload") or {}
    if pl.get("payloadType") not in (1, 3):
        return None
    return {"window_id": wid, "purpose": purpose, "chain_id": cid, "sequence": v.get("sequence"),
            "ts": v.get("timestamp"), "payload_type": pl.get("payloadType"),
            "amount_norm": pl.get("amount"), "token_chain": pl.get("tokenChain"),
            "token_address_hex": pl.get("tokenAddress"), "to_chain": pl.get("toChain"),
            "indexed_at": v.get("indexedAt")}


def fetch_window(cid, a, b, raw_root, manifest, purpose="", sleep=1.2, max_pages=400):
    """All transfer messages of chain cid with VAA timestamp in [a, b) (RFC3339 strings)."""
    wid = window_id(cid, a, b)
    wdir = Path(raw_root) / wid
    wdir.mkdir(parents=True, exist_ok=True)
    url = f"{BASE}/{cid}/{EMITTER[cid]}"
    seen, page, recs = set(), 0, []
    while page < max_pages:
        p = wdir / f"page_{page:04d}.json"
        if p.exists():
            vaas = read_json(p)
        else:
            params = {"from": a, "to": b, "parsedPayload": "true", "pageSize": 100, "page": page}
            t0 = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
            status, data, full = fetch(url, params)
            time.sleep(sleep)
            manifest.append({"window": wid, "page": page, "status": status, "url": full, "accessed_utc": t0})
            if status != 200:
                print(f"  window {wid} page {page} failed with {status}", flush=True)
                raise RuntimeError(f"download failed for {wid} page {page}")
            vaas = data.get("data", []) if isinstance(data, dict) else data
            write_json_atomic(p, vaas)
            manifest[-1]["n"] = len(vaas)
        new = 0
        for v in vaas:
            if v["id"] in seen:
                continue
            seen.add(v["id"])
            new += 1
            r = _record(v, wid, cid, purpose)
            if r is not None:
                recs.append(r)
        if len(vaas) < 100 or new == 0:
            break
        page += 1
    return recs, len(seen)


def fetch_window_reusing(cid, a, b, raw_root, manifest, purpose="", sleep=1.2):
    """Like fetch_window, but a window already cached whole, or hours already cached as
    complete single-hour windows, are read from the cache; only the rest is requested."""
    raw_root = Path(raw_root)
    wid = window_id(cid, a, b)
    if window_complete(raw_root / wid):
        return records_from_pages(raw_root / wid, wid, cid, purpose)
    hours = pd.date_range(pd.Timestamp(a), pd.Timestamp(b) - H, freq="h")
    cached = [window_complete(raw_root / window_id(cid, fmt(h), fmt(h + H))) for h in hours]
    if len(hours) <= 1 or not any(cached):
        return fetch_window(cid, a, b, raw_root, manifest, purpose, sleep)
    recs, n = [], 0
    i = 0
    while i < len(hours):
        if cached[i]:
            h = hours[i]
            hid = window_id(cid, fmt(h), fmt(h + H))
            r, m = records_from_pages(raw_root / hid, hid, cid, purpose)
            recs += r
            n += m
            i += 1
            continue
        j = i
        while j < len(hours) and not cached[j]:
            j += 1
        r, m = fetch_window(cid, fmt(hours[i]), fmt(hours[j - 1] + H), raw_root, manifest, purpose, sleep)
        recs += r
        n += m
        i = j
    return recs, n


def load_manifest(out, name="vaas_manifest.json"):
    mpath = Path(out) / name
    return json.loads(mpath.read_text(encoding="utf-8"))["calls"] if mpath.exists() else []


def save_manifest(out, manifest, name="vaas_manifest.json"):
    p = Path(out) / name
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps({"endpoint": BASE + "/<chain>/<emitter>", "calls": manifest}, indent=1),
                   encoding="utf-8")
    replace_retry(tmp, p)


def write_table(path, records):
    tmp = Path(str(path) + ".tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        wr = csv.DictWriter(f, fieldnames=COLS)
        wr.writeheader()
        wr.writerows(records)
    replace_retry(tmp, path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--windows", required=True)
    ap.add_argument("--sleep", type=float, default=1.2)
    ap.add_argument("--manifest", default="vaas_manifest.json")
    ap.add_argument("--table", default="transfers_windows.csv")
    ap.add_argument("--checkpoint", type=int, default=100, help="rewrite table and manifest every N windows")
    args = ap.parse_args()
    out = Path(args.out)
    windows = list(csv.DictReader(open(args.windows, encoding="utf-8")))
    manifest = load_manifest(out, args.manifest)
    records = []
    t_start = time.time()
    for wi, w in enumerate(windows):
        recs, n = fetch_window_reusing(int(w["chain_id"]), w["from"], w["to"], out / "raw_vaas", manifest,
                                       w.get("purpose", ""), args.sleep)
        records += recs
        el = time.time() - t_start
        print(f"[{wi + 1}/{len(windows)}] {window_id(int(w['chain_id']), w['from'], w['to'])}: {n} messages "
              f"({el / 60:.1f} min)", flush=True)
        if (wi + 1) % args.checkpoint == 0:
            write_table(out / args.table, records)
            save_manifest(out, manifest, args.manifest)
    write_table(out / args.table, records)
    save_manifest(out, manifest, args.manifest)
    print("transfers", len(records))


if __name__ == "__main__":
    sys.exit(main())
