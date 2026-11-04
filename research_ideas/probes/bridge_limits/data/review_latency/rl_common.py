"""Shared helpers for the review and hold latency probes (2026-10-16).

No addresses or transaction identifiers are written by this module; callers keep them in raw/.
RPC endpoints (tested 2026-10-16):
- Ethereum logs over long block ranges: mainnet.gateway.tenderly.co answered eth_getLogs with an address
  and topic filter over 500,000-block ranges; rpc.mevblocker.io answers 10,000-block ranges and archive
  eth_call. Both are used, the second as a cross-check of the first.
"""
import datetime
import json
import pathlib
import sys
import time
import urllib.request

from Crypto.Hash import keccak

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent.parent           # probes/bridge_limits
RAW = HERE / "raw"
RESULTS = ROOT / "results"
sys.path.insert(0, str(ROOT / "incidents"))
from rpc import Rpc, RangeError, topic_addr, addr_from_topic, erc20_meta  # noqa: E402,F401

UA = {"User-Agent": "bridge-limits-probe/1.0 (academic study of bridge withdrawal limits)"}
TENDERLY = "https://mainnet.gateway.tenderly.co"
MEVBLOCKER = "https://rpc.mevblocker.io"


def k256(s):
    h = keccak.new(digest_bits=256)
    h.update(s.encode() if isinstance(s, str) else s)
    return "0x" + h.hexdigest()


def sel(sig):
    return k256(sig)[:10]


def iso(ts):
    return datetime.datetime.fromtimestamp(int(ts), datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def to_ts(s):
    s = s.replace("Z", "").split(".")[0]
    return int(datetime.datetime.fromisoformat(s).replace(tzinfo=datetime.timezone.utc).timestamp())


def cached(path, fn):
    path = pathlib.Path(path)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    v = fn()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(v), encoding="utf-8")
    return v


def http_json(url, tries=6, timeout=90, data=None, headers=None):
    last = None
    h = dict(UA)
    if headers:
        h.update(headers)
    for i in range(tries):
        try:
            req = urllib.request.Request(url, data=data, headers=h)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            last = e
            if e.code in (400, 404):
                body = ""
                try:
                    body = e.read().decode()[:300]
                except Exception:
                    pass
                return {"_http_error": e.code, "_body": body}
            time.sleep(2.0 * (i + 1))
        except Exception as e:
            last = e
            time.sleep(2.0 * (i + 1))
    raise RuntimeError(f"{url}: {last}")


def rpc(urls):
    r = Rpc("ethereum")
    r.urls = list(urls)
    return r


def words(hexdata):
    d = hexdata[2:] if hexdata.startswith("0x") else hexdata
    return [d[i:i + 64] for i in range(0, len(d), 64)]


def block_ts_cached(r, blocks, path):
    path = pathlib.Path(path)
    c = {int(k): v for k, v in json.loads(path.read_text()).items()} if path.exists() else {}
    for i, b in enumerate(sorted(set(blocks))):
        if b not in c:
            c[b] = r.block_ts(b)
            if i % 50 == 49:
                path.write_text(json.dumps(c))
    path.write_text(json.dumps(c))
    return c


def quantiles(xs):
    """Order statistics used in the report: n, min, quartiles (numpy linear interpolation), max."""
    import numpy as np
    a = np.array(sorted(xs), dtype=float)
    if len(a) == 0:
        return {"n": 0}
    return {"n": int(len(a)), "min": float(a[0]), "p25": float(np.quantile(a, 0.25)),
            "median": float(np.quantile(a, 0.5)), "p75": float(np.quantile(a, 0.75)),
            "p90": float(np.quantile(a, 0.9)), "max": float(a[-1]), "mean": float(a.mean())}


def fmt_dur(s):
    s = float(s)
    if s < 120:
        return f"{s:.0f} s"
    if s < 2 * 3600:
        return f"{s / 60:.1f} min"
    if s < 3 * 86400:
        return f"{s / 3600:.1f} h"
    return f"{s / 86400:.1f} d"


def llama_price(coin, ts, cache_path, search="6h"):
    """Historical USD price of a DefiLlama coin id at a unix time (nearest point within the search width)."""
    cache_path = pathlib.Path(cache_path)
    c = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    k = f"{coin}@{int(ts)}@{search}"
    if k not in c:
        j = http_json(f"https://coins.llama.fi/prices/historical/{int(ts)}/{coin}?searchWidth={search}")
        p = (j.get("coins", {}) or {}).get(coin) if isinstance(j, dict) else None
        c[k] = {"price": p.get("price") if p else None, "timestamp": p.get("timestamp") if p else None}
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(c, indent=0))
        time.sleep(0.4)
    return c[k]["price"], c[k]["timestamp"]
