"""E59 (USDC custody bridge on Arbitrum): legitimate releases over the 150 days before the failure (2026-10-16).

Inputs  results/incidents.csv              failure time (first_release_utc)
        raw/E59/targets.json               release-point and token addresses (raw cache; taken from
                                           data/incidents/research/batch_G.json and checked on chain)
Outputs E59.csv                            ts_utc, leg, asset, amount, usd, kind, priced (no addresses, no hashes)
        raw/E59/                           RPC caches (gzip), block timestamps, prices, summary.json

Method
- Window [t_fail - 150 d, t_fail - 1 s]; t_fail = block time of the first unauthorized release.
- Release record. The contract's FinalizedWithdrawal(address indexed user, address destination, uint64 usd,
  uint64 nonce, bytes32 message) has the signature of the same event in Hyperliquid's Bridge2.sol (cached as
  raw/E59/ref_hyperliquid_Bridge2.sol), where finalization transfers `usd` USDC units to `destination` and
  then emits the event. Rows are the USDC Transfer logs with the bridge as sender (kind erc20), each matched
  to a FinalizedWithdrawal in the same transaction (destination, amount).
- Completeness. (a) Every Transfer log with the bridge as sender, for any token, over the window (topic scan
  in 30,000-block steps, the public endpoint's cap for queries without an address); its USDC logs are compared
  with the address-filtered collection, and for a log of any other token the build reads the transaction and the
  bridge's balance of that token before the block (raw/E59/other_token_checks.json), since a token contract can
  emit a Transfer log naming any sender. (b) USDC balance of the bridge at the window ends equals the start
  balance plus logged inflows minus logged outflows. (c) Native ETH: the bridge's balance at every
  1,000,000-block chunk boundary (no trace API for Arbitrum on the public endpoints). (d) Withdrawal requests
  (Bridge2's field layout) against finalizations: requests left unfinalized in the window, finalizations
  without a request. (The comparison and the other-token check in (a), and (d), added 2026-10-16.)
- Prices: DefiLlama /chart hourly (nearest point within 2 h), else daily (36 h), else unpriced.
Run: python -I data/legit/build_e59.py collect|scan|build
"""
import bisect
import collections
import csv
import datetime
import gzip
import json
import pathlib
import sys
import time
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT / "incidents"))
from rpc import Rpc, TRANSFER, topic_addr, addr_from_topic, RangeError, erc20_meta  # noqa: E402

EID = "E59"
RAW = HERE / "raw" / EID
T = json.loads((HERE / "targets" / f"{EID}.json").read_text())
BR = T["bridge"].lower()
USDC = [T["usdc_native"].lower(), T["usdc_bridged"].lower()]
URL = "https://arb1.arbitrum.io/rpc"
STATE_URLS = ["https://arbitrum-one.public.blastapi.io", URL]
LEG = "USDC custody contract (Arbitrum)"
FINALIZED = "0xe5c7fe3a4ffca1590f26d74c8ba8b0db69557f7f4607a2a43f82e93041611978"
FAILED = "0x686cb4bac974cd11b0f8a75fc7c7764ed12cc46faaec53110f807aa802a7acb4"
REQUESTED = "0x98185c1fc2bbe9d84571c908c2db15c64a0bb44a52f665421a610636027f21d9"  # 1 indexed + 5 words
WINDOW_S = 150 * 86400
CHUNK = 1_000_000
SCAN = 30_000
KEEP = ("address", "topics", "data", "blockNumber", "transactionHash", "logIndex")


def iso(ts):
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def to_ts(s):
    return int(datetime.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp())


def failure_time():
    with open(ROOT / "results" / "incidents.csv", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["id"] == EID:
                return to_ts(r["first_release_utc"])
    raise KeyError(EID)


STATS = collections.Counter()


def rpc():
    """Rpc object for the public Arbitrum endpoint; errors other than range errors are retried with backoff
    (the endpoint answers HTTP 429 under load) and counted in STATS."""
    r = Rpc("arbitrum")
    r.urls = [URL]

    def call(method, params, retries=12):
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
        last = None
        # historical state (code, balances, eth_call) is not kept by every node behind the official endpoint
        # ("missing trie node"); those calls alternate with a second public endpoint that served it on 2026-10-16
        urls = [URL] if method in ("eth_getLogs", "eth_getBlockByNumber", "eth_blockNumber") else STATE_URLS
        for k in range(retries):
            url = urls[k % len(urls)]
            try:
                req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json",
                                                                      "User-Agent": "bridge-limits-probe/1.0"})
                with urllib.request.urlopen(req, timeout=90) as resp:
                    j = json.loads(resp.read().decode())
                STATS["calls"] += 1
                if "error" in j:
                    msg = str(j["error"])
                    if any(x in msg.lower() for x in ("range", "limit", "too many", "exceed", "spans", "more than")):
                        raise RangeError(msg[:300])
                    last = msg
                    STATS["rpc_error"] += 1
                    time.sleep(2 * (k + 1))
                    continue
                return j["result"]
            except RangeError:
                raise
            except Exception as e:  # noqa: BLE001
                last = e
                STATS["http_429" if "429" in str(e) else "http_other"] += 1
                time.sleep(min(60, 5 * (k + 1)))
        raise RuntimeError(f"{method} failed: {last}")
    r.call = call
    return r


def block_at(r, ts, lo, hi):
    """Smallest block with timestamp >= ts, by interpolation on the (nearly uniform) Arbitrum block times."""
    tlo, thi = r.block_ts(lo), r.block_ts(hi)
    assert tlo < ts <= thi
    while hi - lo > 1:
        guess = lo + int((ts - tlo) * (hi - lo) / max(1, thi - tlo))
        mid = min(hi - 1, max(lo + 1, guess))
        if hi - lo > 64:  # keep the bracket shrinking even when the interpolation lands on an edge
            mid = min(max(mid, lo + (hi - lo) // 64), hi - (hi - lo) // 64)
        tm = r.block_ts(mid)
        if tm < ts:
            lo, tlo = mid, tm
        else:
            hi, thi = mid, tm
    return hi


def slim(logs):
    return [{k: lg.get(k) for k in KEEP} for lg in logs]


def gz_cached(path, fn):
    if path.exists():
        with gzip.open(path, "rt") as fh:
            return json.load(fh)
    v = fn()
    tmp = path.with_suffix(".tmp")
    with gzip.open(tmp, "wt") as fh:
        json.dump(v, fh)
    tmp.replace(path)
    return v


def batch_blocks(blocks, cache_path):
    cache = {int(k): v for k, v in json.loads(cache_path.read_text()).items()} if cache_path.exists() else {}
    todo = sorted(set(b for b in blocks if b not in cache))
    for i in range(0, len(todo), 40):
        part = todo[i:i + 40]
        body = json.dumps([{"jsonrpc": "2.0", "id": b, "method": "eth_getBlockByNumber", "params": [hex(b), False]}
                           for b in part]).encode()
        for attempt in range(10):
            try:
                req = urllib.request.Request(URL, data=body, headers={"Content-Type": "application/json",
                                                                      "User-Agent": "bridge-limits-probe/1.0"})
                with urllib.request.urlopen(req, timeout=90) as r:
                    j = json.loads(r.read().decode())
                for x in j:
                    cache[int(x["id"])] = int(x["result"]["timestamp"], 16)
                break
            except Exception as e:  # noqa: BLE001
                if attempt == 9:
                    raise RuntimeError(f"header batch failed: {e}")
                time.sleep(5 * (attempt + 1))
        if i % 2000 == 0:
            cache_path.write_text(json.dumps(cache))
            print("timestamps", i, len(todo), flush=True)
    cache_path.write_text(json.dumps(cache))
    return cache


def window(r):
    p = RAW / "window.json"
    if p.exists():
        return json.loads(p.read_text())
    t_fail = failure_time()
    t_start = t_fail - WINDOW_S
    fb = T["failure_block"]
    assert r.block_ts(fb) == t_fail, "failure block time differs from incidents.csv"
    b0 = block_at(r, t_start, fb - 70_000_000, fb)
    bf = block_at(r, t_fail, fb - 1000, fb)
    print("window blocks", b0, bf, dict(STATS), flush=True)
    w = {"t_fail": t_fail, "t_start": t_start, "t_end": t_fail - 1, "b0": b0, "b1": bf - 1,
         "ts_b0m1": r.block_ts(b0 - 1), "ts_b0": r.block_ts(b0), "ts_b1": r.block_ts(bf - 1), "ts_bf": r.block_ts(bf)}
    assert w["ts_b0m1"] < t_start <= w["ts_b0"] and w["ts_b1"] < t_fail <= w["ts_bf"], w
    # first block with contract code (binary search on eth_getCode; archive state)
    lo, hi = 1, fb
    if len(r.call("eth_getCode", [BR, hex(b0)])) > 2:
        w["deployed_before_window"] = True
        w["first_code_block"] = None
    else:
        lo = b0
        while lo < hi:
            mid = (lo + hi) // 2
            if len(r.call("eth_getCode", [BR, hex(mid)])) > 2:
                hi = mid
            else:
                lo = mid + 1
        w["deployed_before_window"] = False
        w["first_code_block"] = lo
        w["first_code_ts"] = r.block_ts(lo)
    p.write_text(json.dumps(w, indent=1))
    return w


def collect():
    r = rpc()
    w = window(r)
    print(json.dumps(w), flush=True)
    start = w["b0"] if w["deployed_before_window"] else w["first_code_block"]
    b = start
    while b <= w["b1"]:
        e = min(b + CHUNK - 1, w["b1"])
        f = RAW / f"chunk_{b}_{e}.json.gz"

        def fetch(b=b, e=e):
            br = slim(r.logs(BR, [], b, e, step=CHUNK))
            xo = slim(r.logs(USDC, [TRANSFER, topic_addr(BR)], b, e, step=CHUNK))
            xi = slim(r.logs(USDC, [TRANSFER, None, topic_addr(BR)], b, e, step=CHUNK))
            bal_eth = int(r.call("eth_getBalance", [BR, hex(e)]), 16)
            return {"b0": b, "b1": e, "bridge": br, "usdc_out": xo, "usdc_in": xi, "eth_balance_at_b1": bal_eth}
        c = gz_cached(f, fetch)
        print(b, e, len(c["bridge"]), len(c["usdc_out"]), len(c["usdc_in"]), c["eth_balance_at_b1"], dict(STATS), flush=True)
        b = e + 1
    # balances at the window ends (USDC: balanceOf; ETH: getBalance)
    p = RAW / "balances.json"
    if not p.exists():
        out = {}
        for blk in (start - 1, w["b1"]):
            out[str(blk)] = {"eth": int(r.call("eth_getBalance", [BR, hex(blk)]), 16)}
            for tok in USDC:
                res = r.call("eth_call", [{"to": tok, "data": "0x70a08231" + "0" * 24 + BR[2:]}, hex(blk)])
                out[str(blk)][tok] = int(res, 16)
        p.write_text(json.dumps(out, indent=1))
    print(json.loads(p.read_text()))


def scan():
    """Transfer logs with the bridge as sender, any token contract (topic filter only, 30,000-block steps)."""
    r = rpc()
    w = window(r)
    start = w["b0"] if w["deployed_before_window"] else w["first_code_block"]
    sdir = RAW / "scan"
    sdir.mkdir(exist_ok=True)
    b = start
    while b <= w["b1"]:
        e = min(b + 300 * SCAN - 1, w["b1"])   # one cache file per 9M blocks, queried in 30k steps
        f = sdir / f"scan_{b}_{e}.json.gz"
        if not f.exists():
            got, s = [], b
            while s <= e:
                t = min(s + SCAN - 1, e)
                got += slim(r.call("eth_getLogs", [{"fromBlock": hex(s), "toBlock": hex(t),
                                                    "topics": [TRANSFER, topic_addr(BR)]}]))
                s = t + 1
            gz_cached(f, lambda: {"b0": b, "b1": e, "logs": got})
            print("scan", b, e, len(got), r.calls, flush=True)
        b = e + 1


class Prices:
    """DefiLlama /chart: hourly series (2 h tolerance), daily series (36 h tolerance); cached under raw/E59/px."""

    def __init__(self, t0, t1):
        self.t0, self.t1 = t0, t1
        self.dir = RAW / "px"
        self.dir.mkdir(exist_ok=True)
        self.series = {}

    @staticmethod
    def _get(url):
        last = None
        for k in range(6):
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "bridge-limits-probe/1.0"}),
                                            timeout=60) as r:
                    return json.loads(r.read().decode())
            except Exception as e:  # noqa: BLE001
                last = e
                time.sleep(2 * (k + 1))
        raise RuntimeError(f"{url}: {last}")

    def _cached(self, name, url):
        p = self.dir / name
        if p.exists():
            return json.loads(p.read_text())
        j = self._get(url)
        p.write_text(json.dumps(j))
        time.sleep(0.3)
        return j

    def load(self, cid):
        if cid in self.series:
            return self.series[cid]
        safe = cid.replace(":", "_")
        hourly = []
        t = self.t0 - 3 * 3600
        while t < self.t1 + 3600:
            j = self._cached(f"1h_{safe}_{t}.json", f"https://coins.llama.fi/chart/{cid}?start={t}&span=500&period=1h")
            pts = [(q["timestamp"], q["price"]) for q in (j.get("coins", {}).get(cid, {}).get("prices") or [])]
            if len(pts) < 450:
                j2 = self._cached(f"1h_{safe}_{t}_sw1800.json",
                                  f"https://coins.llama.fi/chart/{cid}?start={t}&span=500&period=1h&searchWidth=1800")
                pts += [(q["timestamp"], q["price"]) for q in (j2.get("coins", {}).get(cid, {}).get("prices") or [])]
            hourly += pts
            t += 500 * 3600
        j = self._cached(f"1d_{safe}_{self.t0}.json",
                         f"https://coins.llama.fi/chart/{cid}?start={self.t0 - 2 * 86400}&span=160&period=1d")
        daily = [(q["timestamp"], q["price"]) for q in (j.get("coins", {}).get(cid, {}).get("prices") or [])]
        self.series[cid] = (sorted(set(hourly)), sorted(set(daily)))
        return self.series[cid]

    @staticmethod
    def near(series, ts, tol):
        if not series:
            return None
        xs = [s[0] for s in series]
        i = bisect.bisect_left(xs, ts)
        best = None
        for j in (i - 1, i):
            if 0 <= j < len(series):
                d = abs(series[j][0] - ts)
                if d <= tol and (best is None or d < best[0]):
                    best = (d, series[j][1])
        return None if best is None else best[1]

    def price(self, cid, ts):
        h, d = self.load(cid)
        p = self.near(h, ts, 2 * 3600)
        if p is not None:
            return p, "defillama chart 1h"
        p = self.near(d, ts, 36 * 3600)
        if p is not None:
            return p, "defillama chart 1d"
        return None, ""


def build():
    import numpy as np
    w = json.loads((RAW / "window.json").read_text())
    start = w["b0"] if w["deployed_before_window"] else w["first_code_block"]
    chunks = sorted(RAW.glob("chunk_*.json.gz"), key=lambda p: int(p.name.split("_")[1]))
    cov, brl, xo, xi, ethbal = [], [], [], [], []
    for p in chunks:
        with gzip.open(p, "rt") as fh:
            c = json.load(fh)
        cov.append((c["b0"], c["b1"]))
        brl += c["bridge"]
        xo += c["usdc_out"]
        xi += c["usdc_in"]
        ethbal.append((c["b1"], c["eth_balance_at_b1"]))
    gaps, expect = [], start
    for a, b in cov:
        if a != expect:
            gaps.append([expect, a - 1])
        expect = b + 1
    if expect <= w["b1"]:
        gaps.append([expect, w["b1"]])
    topics = collections.Counter(lg["topics"][0] for lg in brl if lg["topics"])

    fin = []
    for lg in brl:
        if lg["topics"] and lg["topics"][0] == FINALIZED:
            d = lg["data"][2:]
            ws = [d[i:i + 64] for i in range(0, len(d), 64)]
            fin.append({"tx": lg["transactionHash"], "block": int(lg["blockNumber"], 16),
                        "logIndex": int(lg["logIndex"], 16), "user": addr_from_topic(lg["topics"][1]).lower(),
                        "dest": ("0x" + ws[0][-40:]).lower(), "raw": int(ws[1], 16), "nonce": int(ws[2], 16),
                        "message": ws[3]})
    req = [lg for lg in brl if lg["topics"] and lg["topics"][0] == REQUESTED]
    failed = collections.Counter()
    for lg in brl:
        if lg["topics"] and lg["topics"][0] == FAILED:
            failed[int(lg["data"][2 + 64:2 + 128], 16)] += 1

    # match Transfer logs (bridge -> destination) to FinalizedWithdrawal events in the same transaction
    by_tx = collections.defaultdict(list)
    for e in fin:
        by_tx[e["tx"]].append(e)
    used = set()
    rows_src, unmatched_out = [], []
    for x in sorted(xo, key=lambda x: (int(x["blockNumber"], 16), int(x["logIndex"], 16))):
        to = addr_from_topic(x["topics"][2]).lower()
        raw = int(x["data"], 16)
        cand = [e for e in by_tx.get(x["transactionHash"], []) if id(e) not in used and e["dest"] == to and e["raw"] == raw]
        if cand:
            e = min(cand, key=lambda e: abs(e["logIndex"] - int(x["logIndex"], 16)))
            used.add(id(e))
            rows_src.append({"block": int(x["blockNumber"], 16), "token": x["address"].lower(), "raw": raw, "to": to,
                             "user": e["user"], "tx": x["transactionHash"]})
        else:
            unmatched_out.append({"block": int(x["blockNumber"], 16), "token": x["address"].lower(), "raw": raw, "to": to,
                                  "tx": x["transactionHash"]})
    events_without_transfer = [e for e in fin if id(e) not in used]

    # any-token scan (step `scan`), if present: transfers out of the bridge by tokens other than USDC
    scan_files = sorted((RAW / "scan").glob("scan_*.json.gz")) if (RAW / "scan").exists() else []
    scan_cov, scan_logs = [], []
    for p in scan_files:
        with gzip.open(p, "rt") as fh:
            c = json.load(fh)
        scan_cov.append((c["b0"], c["b1"]))
        scan_logs += c["logs"]
    scan_cov.sort()
    scan_complete = bool(scan_cov) and scan_cov[0][0] == start and scan_cov[-1][1] == w["b1"] and all(
        a[1] + 1 == b[0] for a, b in zip(scan_cov, scan_cov[1:]))
    scan_other = collections.Counter(lg["address"].lower() for lg in scan_logs if lg["address"].lower() not in USDC)
    scan_usdc = sum(1 for lg in scan_logs if lg["address"].lower() in USDC)
    # USDC logs of the scan against the address-filtered collection (same logs, same amounts)
    scan_usdc_keys = {(lg["transactionHash"], int(lg["logIndex"], 16)) for lg in scan_logs if lg["address"].lower() in USDC}
    xo_keys = {(x["transactionHash"], int(x["logIndex"], 16)) for x in xo}
    scan_vs_collect = {"in_scan_only": len(scan_usdc_keys - xo_keys), "in_collect_only": len(xo_keys - scan_usdc_keys)}

    # Transfer logs of other tokens with the bridge as sender: did the bridge hold the token, and did the bridge
    # take part in the transaction?  (A token contract can emit a Transfer log naming any sender.)
    def other_checks():
        r = rpc()
        out = []
        for lg in scan_logs:
            tok = lg["address"].lower()
            if tok in USDC:
                continue
            blk = int(lg["blockNumber"], 16)
            tx = r.call("eth_getTransactionByHash", [lg["transactionHash"]])
            rc = r.call("eth_getTransactionReceipt", [lg["transactionHash"]])
            before = int(r.call("eth_call", [{"to": tok, "data": "0x70a08231" + "0" * 24 + BR[2:]}, hex(blk - 1)]), 16)
            sym, dec = erc20_meta(r, tok, {})
            out.append({"token": tok, "symbol": sym, "decimals": dec, "block": blk, "amount": int(lg["data"], 16) / 10 ** dec,
                        "tx_to_is_token": (tx["to"] or "").lower() == tok, "tx_to_is_bridge": (tx["to"] or "").lower() == BR,
                        "tx_from_is_bridge": tx["from"].lower() == BR, "bridge_token_balance_before": before,
                        "logs_in_tx": len(rc["logs"]),
                        "bridge_logs_in_tx": sum(1 for x in rc["logs"] if x["address"].lower() == BR),
                        "usdc_logs_in_tx": sum(1 for x in rc["logs"] if x["address"].lower() in USDC)})
        return out
    p_oc = RAW / "other_token_checks.json"
    if not p_oc.exists():
        p_oc.write_text(json.dumps(other_checks(), indent=1))
    other_tok = json.loads(p_oc.read_text())

    # withdrawal requests against finalizations (the request event has Bridge2's field layout: user indexed;
    # destination, usd, nonce, message, requestedTime)
    reqs = []
    for lg in brl:
        if lg["topics"] and lg["topics"][0] == REQUESTED:
            d = lg["data"][2:]
            ws = [d[i:i + 64] for i in range(0, len(d), 64)]
            reqs.append({"block": int(lg["blockNumber"], 16), "dest": ("0x" + ws[0][-40:]).lower(), "raw": int(ws[1], 16),
                         "message": ws[3]})
    fin_msgs = {e["message"] for e in fin}
    req_msgs = {q["message"] for q in reqs}
    pending = [q for q in reqs if q["message"] not in fin_msgs]
    fin_without_req = [e for e in fin if e["message"] not in req_msgs]

    fail_to = {T.get("failure_recipient", "").lower()}
    excluded = collections.Counter()
    blocks = sorted({r["block"] for r in rows_src})
    tsc = batch_blocks(blocks, RAW / "block_ts.json")
    prices = Prices(w["ts_b0"], w["ts_b1"])
    cid = {USDC[0]: "arbitrum:" + USDC[0], USDC[1]: "arbitrum:" + USDC[1]}
    rows = []
    for s in rows_src:
        if s["to"] in fail_to or s["user"] in fail_to:
            excluded["to or from the failure's recipient"] += 1
            continue
        if s["to"] == BR:
            excluded["to the bridge itself"] += 1
            continue
        ts = tsc[s["block"]]
        assert w["t_start"] <= ts <= w["t_end"], (ts, s["block"])
        amt = s["raw"] / 1e6
        p, src = prices.price(cid[s["token"]], ts)
        rows.append({"ts": ts, "ts_utc": iso(ts), "leg": LEG, "asset": "USDC" if s["token"] == USDC[0] else "USDC.e",
                     "amount": amt, "usd": None if p is None else amt * p, "kind": "erc20",
                     "priced": "yes" if p is not None else "no", "src": src, "to": s["to"]})
    rows.sort(key=lambda r: r["ts"])
    with open(HERE / f"{EID}.csv", "w", newline="", encoding="utf-8") as f:
        wr = csv.writer(f)
        wr.writerow(["ts_utc", "leg", "asset", "amount", "usd", "kind", "priced"])
        for r in rows:
            wr.writerow([r["ts_utc"], r["leg"], r["asset"], repr(r["amount"]), "" if r["usd"] is None else f"{r['usd']:.2f}",
                         r["kind"], r["priced"]])

    # balance reconciliation (USDC) over [start, b1]
    bal = json.loads((RAW / "balances.json").read_text())
    rec = {}
    for tok in USDC:
        inflow = sum(int(x["data"], 16) for x in xi if x["address"].lower() == tok)
        outflow = sum(int(x["data"], 16) for x in xo if x["address"].lower() == tok)
        b_start, b_end = bal[str(start - 1)][tok], bal[str(w["b1"])][tok]
        rec[tok] = {"start": b_start / 1e6, "end": b_end / 1e6, "in": inflow / 1e6, "out": outflow / 1e6,
                    "residual": (b_start + inflow - outflow - b_end) / 1e6,
                    "n_in": sum(1 for x in xi if x["address"].lower() == tok),
                    "n_out": sum(1 for x in xo if x["address"].lower() == tok)}

    # summary
    pr = [r for r in rows if r["usd"] is not None]
    hour, day, hour_n, day_n = collections.defaultdict(float), collections.defaultdict(float), collections.Counter(), collections.Counter()
    for r in pr:
        hour[r["ts"] // 3600 * 3600] += r["usd"]
        day[r["ts"] // 86400 * 86400] += r["usd"]
    for r in rows:
        hour_n[r["ts"] // 3600 * 3600] += 1
        day_n[r["ts"] // 86400 * 86400] += 1
    d0 = w["t_start"] // 86400 * 86400
    days_all = list(range(d0, w["t_end"] // 86400 * 86400 + 1, 86400))
    day_vals = [day.get(d, 0.0) for d in days_all]
    ts_sorted = sorted(r["ts"] for r in rows)
    gaps_t = []
    for a, b in zip([w["t_start"]] + ts_sorted, ts_sorted + [w["t_end"]]):
        if b - a > 6 * 3600:
            gaps_t.append([iso(a), iso(b), round((b - a) / 3600, 1)])
    big = sorted(pr, key=lambda r: -r["usd"])[:5]
    recip = collections.Counter()
    for r in rows:
        recip[r["to"]] += r["usd"] or 0.0
    top_recip = recip.most_common(10)
    usd_arr = np.array([r["usd"] for r in pr]) if pr else np.array([0.0])
    s = {
        "id": EID, "window_utc": [iso(w["t_start"]), iso(w["t_end"])], "blocks": [start, w["b1"]],
        "block_times": [iso(w["ts_b0"]), iso(w["ts_b1"])], "deployed_before_window": w["deployed_before_window"],
        "first_code_block": w.get("first_code_block"), "first_code_utc": iso(w["first_code_ts"]) if w.get("first_code_ts") else None,
        "chunks": len(cov), "block_gaps": gaps, "bridge_log_topics": dict(topics),
        "n_finalized_events": len(fin), "n_requested_events": len(req), "failed_withdrawal_codes": dict(failed),
        "n_usdc_transfers_out": len(xo), "n_usdc_transfers_in": len(xi),
        "matched_rows": len(rows_src), "unmatched_transfers_out": len(unmatched_out),
        "unmatched_transfers_out_detail": [{"block": u["block"], "amount": u["raw"] / 1e6} for u in unmatched_out][:50],
        "events_without_transfer": len(events_without_transfer),
        "scan_files": len(scan_files), "scan_complete": scan_complete, "scan_usdc_logs": scan_usdc,
        "scan_usdc_vs_collect": scan_vs_collect,
        "scan_other_tokens": dict(scan_other),
        "scan_other_token_checks": [{k: v for k, v in c.items() if k != "token"} for c in other_tok],
        "requests_not_finalized": [{"block": q["block"], "amount": q["raw"] / 1e6,
                                    "is_failure_request": q["block"] == T["failure_request_block"],
                                    "to_failure_recipient": q["dest"] == T.get("failure_recipient", "").lower()} for q in pending],
        "finalized_without_request": len(fin_without_req),
        "eth_balance_points": len(ethbal), "eth_balance_nonzero_points": sum(1 for _, v in ethbal if v),
        "eth_balance_max_wei": max((v for _, v in ethbal), default=0),
        "balance_check": rec, "excluded": dict(excluded),
        "n_rows": len(rows), "n_priced": len(pr), "share_priced": len(pr) / len(rows) if rows else None,
        "usd_total": float(sum(r["usd"] for r in pr)), "amount_total": float(sum(r["amount"] for r in rows)),
        "price_sources": dict(collections.Counter(r["src"] for r in pr)),
        "first_release": iso(ts_sorted[0]) if ts_sorted else None, "last_release": iso(ts_sorted[-1]) if ts_sorted else None,
        "days_with_release": len({r["ts"] // 86400 for r in rows}), "n_days_window": len(days_all),
        "largest": [{"ts_utc": r["ts_utc"], "amount": r["amount"], "usd": r["usd"]} for r in big],
        "usd_quantiles": {q: float(np.quantile(usd_arr, q)) for q in (0.5, 0.9, 0.99, 0.999)},
        "busiest_hour_usd": (lambda h: {"hour_utc": iso(h), "usd": hour[h], "n": hour_n[h]})(max(hour, key=hour.get)) if hour else None,
        "busiest_hour_count": (lambda h: {"hour_utc": iso(h), "n": hour_n[h], "usd": hour.get(h, 0.0)})(max(hour_n, key=hour_n.get)) if hour_n else None,
        "busiest_day_usd": (lambda d: {"day_utc": iso(d)[:10], "usd": day[d], "n": day_n[d]})(max(day, key=day.get)) if day else None,
        "busiest_day_count": (lambda d: {"day_utc": iso(d)[:10], "n": day_n[d], "usd": day.get(d, 0.0)})(max(day_n, key=day_n.get)) if day_n else None,
        "daily_usd_quantiles": {q: float(np.quantile(day_vals, q)) for q in (0.5, 0.9, 0.99, 1.0)},
        "daily_usd_mean_150d": float(sum(r["usd"] for r in pr) / 150.0),
        "gaps_over_6h": gaps_t,
        "top_recipient_shares": [round(v / max(1e-9, sum(recip.values())), 4) for _, v in top_recip],
        "n_recipients": len(recip),
    }
    (RAW / "summary.json").write_text(json.dumps(s, indent=1, default=str))
    # recipient detail stays in the raw cache (addresses)
    (RAW / "top_recipients.json").write_text(json.dumps(top_recip, indent=1))
    print(json.dumps({k: s[k] for k in ("n_rows", "n_priced", "usd_total", "matched_rows", "unmatched_transfers_out",
                                        "events_without_transfer", "balance_check", "excluded", "largest",
                                        "busiest_hour_usd", "busiest_day_usd", "scan_complete", "scan_other_tokens",
                                        "eth_balance_nonzero_points", "first_release", "block_gaps")}, indent=1, default=str))


if __name__ == "__main__":
    {"collect": collect, "scan": scan, "build": build}[sys.argv[1]]()
