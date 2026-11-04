"""Second pricing pass for releases the chart series left unpriced (used by build_e11.py and build_e16.py).

The DefiLlama chart endpoint returns sparse points for parts of 2021 (for ETH, one empty 500-hour block and
a few points per week elsewhere), so many releases fall outside the chart tolerance. This pass asks the
batchHistorical endpoint for the price at the middle of each release hour:
  https://coins.llama.fi/batchHistorical?coins={"<coin>":[t1,...]}&searchWidth=2h
and accepts a point only if its own timestamp lies within 2 h of the release. Answers (including misses)
are cached in <cache_dir>/points.json keyed "<coin>|<hour_mid_ts>".
"""
import json
import time
import urllib.parse
import urllib.error
import urllib.request

UA = {"User-Agent": "bridge-limits-probe/1.0"}
BATCH = 60


def _get(url, tries=5):
    last = None
    for k in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=90) as r:
                return json.loads(r.read().decode())
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(3 * (k + 1))
    raise RuntimeError(str(last))


def hour_mid(ts):
    return ts // 3600 * 3600 + 1800


def lookup(pairs, cache_dir):
    """pairs: iterable of (coin, ts). Returns {(coin, hour_mid): (point_ts, price) or None}."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    cp = cache_dir / "points.json"
    cache = json.loads(cp.read_text()) if cp.exists() else {}
    want = {}
    for coin, ts in pairs:
        want.setdefault(coin, set()).add(hour_mid(ts))
    for coin, hs in want.items():
        todo = sorted(h for h in hs if f"{coin}|{h}" not in cache)
        for i in range(0, len(todo), BATCH):
            part = todo[i:i + BATCH]
            q = urllib.parse.urlencode({"coins": json.dumps({coin: part}, separators=(",", ":")),
                                        "searchWidth": "2h"})
            try:
                j = _get("https://coins.llama.fi/batchHistorical?" + q)
            except RuntimeError:
                continue  # left uncached: retried on the next run, unpriced in this one
            pts = [(p["timestamp"], p["price"]) for p in ((j.get("coins") or {}).get(coin) or {}).get("prices", [])]
            for h in part:
                best = min(pts, key=lambda p: abs(p[0] - h), default=None)
                cache[f"{coin}|{h}"] = list(best) if best and abs(best[0] - h) <= 2 * 3600 else None
            cp.write_text(json.dumps(cache))
            time.sleep(0.3)
    out = {}
    for coin, hs in want.items():
        for h in hs:
            v = cache.get(f"{coin}|{h}")
            out[(coin, h)] = tuple(v) if v else None
    return out


def price(table, coin, ts, tol=2 * 3600):
    v = table.get((coin, hour_mid(ts)))
    if v is None or abs(v[0] - ts) > tol:
        return None
    return v[1]


def cg_ids(platform, tokens, cache_dir):
    """Map token contracts to CoinGecko ids (api.coingecko.com /coins/{platform}/contract/{addr}), cached in
    <cache_dir>/cg_ids.json; None when CoinGecko does not list the contract. Used for a third pricing pass
    (DefiLlama coingecko:<id> keys) when DefiLlama has no series under the contract key."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    cp = cache_dir / "cg_ids.json"
    cache = json.loads(cp.read_text()) if cp.exists() else {}
    for t in tokens:
        if t in cache:
            continue
        url = f"https://api.coingecko.com/api/v3/coins/{platform}/contract/{t}"
        for k in range(6):
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
                    cache[t] = json.loads(r.read().decode()).get("id")
                break
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    cache[t] = None
                    break
                time.sleep(20 * (k + 1))  # 429: free tier allows a few calls per minute
            except Exception:  # noqa: BLE001
                time.sleep(10)
        cp.write_text(json.dumps(cache, indent=1))
        time.sleep(7)
    return {t: cache.get(t) for t in tokens}
