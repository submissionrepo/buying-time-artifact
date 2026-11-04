"""DefiLlama price series for release valuation (shared by build_e16.py and build_e11.py).

Source: https://coins.llama.fi/chart/{coin}?start=..&span=..&period=1h|1d (at most 500 points per request).
Each response is cached under raw/<ID>/prices/. A release is priced from the nearest point of the
series within a tolerance (hourly series: 2 h; daily series: 36 h); otherwise it stays unpriced.
"""
import json
import time
import urllib.request

UA = {"User-Agent": "bridge-limits-probe/1.0"}


def _get(url, tries=5):
    last = None
    for k in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
                return json.loads(r.read().decode())
        except Exception as e:  # HTTP 429/5xx, network
            last = e
            time.sleep(2 * (k + 1))
    raise RuntimeError(f"{url}: {last}")


def chart(coin, t0, t1, period, cache_dir, search_width=600):
    """Return sorted list of (ts, price, confidence) covering [t0, t1].

    search_width (s) is passed to DefiLlama; the default 600 s returns sparse series for 2021 dates, a wider
    window (1800 s hourly, 43200 s daily) returns dense ones. Cache names carry it when not the default."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    step = 3600 if period == "1h" else 86400
    pts = []
    s = t0 - step
    while s <= t1 + step:
        span = min(500, (t1 + step - s) // step + 1)
        name = coin.replace(":", "_") + f"_{period}_{s}_{span}" + ("" if search_width == 600 else f"_sw{search_width}") + ".json"
        f = cache_dir / name
        if f.exists():
            j = json.loads(f.read_text())
        else:
            url = f"https://coins.llama.fi/chart/{coin}?start={s}&span={span}&period={period}&searchWidth={search_width}"
            try:
                j = _get(url)
            except RuntimeError as e:
                j = {"error": str(e)}
            f.write_text(json.dumps(j))
            time.sleep(0.3)
        c = (j.get("coins") or {}).get(coin)
        if c:
            conf = c.get("confidence")
            pts += [(p["timestamp"], p["price"], conf) for p in c.get("prices", [])]
        s += span * step
    pts = sorted(set(pts))
    return pts


def nearest(pts, ts, tol):
    """Price at the series point nearest to ts if within tol seconds, else None."""
    if not pts:
        return None
    import bisect
    keys = [p[0] for p in pts]
    i = bisect.bisect_left(keys, ts)
    best = None
    for j in (i - 1, i):
        if 0 <= j < len(pts):
            d = abs(pts[j][0] - ts)
            if d <= tol and (best is None or d < best[0]):
                best = (d, pts[j][1])
    return None if best is None else best[1]
