"""Shadow-run dataset: CCIP token releases between Ethereum and BNB Smart Chain, 2026-09-04T00:00Z .. 2026-10-16T00:00Z.

Pair: chosen by the `pair` step (explorer API counts of token-carrying messages executed successfully in the period,
both directions, for the two candidate pairs closest in volume; see data/ccip_README.md).

Steps (run in order; every RPC response, explorer page and price series is cached under raw/ccip/, so reruns are
cheap):
  pair      explorer API crawl (src/dst selector filters) back to 2026-07-01 for Ethereum<->BSC and Ethereum<->Base;
            token-carrying messages executed in the period per direction -> raw/ccip/pair_choice.json
  targets   routers, OnRamps and OffRamps used in the period (router state at the period ends and the router's
            OnRampSet / OffRampAdded / OffRampRemoved events in between), their versions and linked ramps, lane
            tokens and their pools (documentation and TokenAdminRegistry at the period ends) -> raw/ccip/targets.json
  releases  ccip_decode.new_releases over the period on each destination chain -> raw/ccip/releases_<src>_<dst>.json.gz
  sources   source message of each release: on Ethereum a scan of the OnRamps (period plus 7 days before) indexed
            by messageId; on BSC, where public log queries are throttled, the explorer's send transaction, accepted
            only if its receipt holds the OnRamp's send event with the same messageId; then
            ccip_decode.source_from_log (decode, value check, comparison) on what was found and
            ccip_decode.find_source for the rest -> raw/ccip/sources_<src>_<dst>.json.gz
  build     data/ccip_ethereum-bsc_releases.csv (no addresses, no hashes), pools observed added to targets.json
  coverage  daily release counts against the explorer API, with every difference explained -> raw/ccip/coverage.json
  selftest  find_source on a sample of releases matched by the bulk scan (same answer expected), and new_releases
            through the plain incidents/rpc.Rpc client on a short range (same releases expected)
Run: python -I shadow/ccip_collect.py <step>|all
"""
import bisect
import collections
import csv
import datetime as dt
import decimal
import gzip
import json
import pathlib
import random
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "incidents"))
sys.path.insert(0, str(HERE))
from rpc import Rpc, RangeError, RANGE_ERROR_KEYS  # noqa: E402
import ccip_decode as cd  # noqa: E402

RAW = HERE / "raw" / "ccip"
OUT = HERE / "data"
DOCS = ROOT / "data" / "ccip"
API = "https://api.ccip.chain.link/v2/messages"
UA = {"User-Agent": "research-probe/0.1 (academic study of bridge rate limits)"}

T0 = int(dt.datetime(2026, 9, 4, tzinfo=dt.timezone.utc).timestamp())
T1 = int(dt.datetime(2026, 10, 16, tzinfo=dt.timezone.utc).timestamp())
API_CUTOFF = int(dt.datetime(2026, 7, 1, tzinfo=dt.timezone.utc).timestamp())
LOOKBACK_S = 7 * 86400  # bulk source scan starts this long before the period

PAIR = ("ethereum", "bsc")
PAIR_NAME = "ethereum-bsc"
CANDIDATES = [("ethereum", "bsc"), ("ethereum", "base")]
SELECTOR = {"ethereum": "5009297550715157269", "bsc": "11344663589394136015", "base": "15971525489660198786",
            "arbitrum": "4949039107694359620"}
DOCS_KEY = {"ethereum": "mainnet", "bsc": "bsc-mainnet", "base": "ethereum-mainnet-base-1"}
LLAMA = {"ethereum": "ethereum", "bsc": "bsc"}

# Public endpoints tested 2026-10-16: rpc.mevblocker.io serves archive state, JSON-RPC batches and eth_getLogs over
# 50,000 blocks; the Tenderly gateway the same up to 20,000 blocks; eth.drpc.org answered HTTP 400. On BSC the
# NodeReal demo key (also in incidents/rpc.py) serves archive state, batches and eth_getLogs up to 50,000 blocks but
# answers HTTP 429 at times (the key is shared); api.zan.top serves archive state and batches (its eth_getLogs
# answered 429), so it takes the other calls; publicnode answered 403, bsc-dataseed 'limit exceeded' for logs and no
# archive state, blxrbdn 5,000-block logs without archive state, blastapi, onfinality and drpc HTTP 429 or 400.
URLS = {"ethereum": ["https://rpc.mevblocker.io", "https://mainnet.gateway.tenderly.co"],
        "bsc": ["https://api.zan.top/bsc-mainnet", __import__("os").environ.get("BSC_RPC_URL", "https://bsc-dataseed.bnbchain.org")]}
LOG_URLS = {"ethereum": URLS["ethereum"],
            "bsc": [__import__("os").environ.get("BSC_RPC_URL", "https://bsc-dataseed.bnbchain.org")]}
LOG_CHUNK = {"ethereum": 20_000, "bsc": 50_000}
SEC_PER_BLOCK = {"ethereum": 12.0, "bsc": 0.45}
SAFE_DEPTH = {"ethereum": 96, "bsc": 2_000}  # responses for blocks this far below the head are cached


def utcnow():
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def iso(ts):
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_ts(s):
    return int(dt.datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=dt.timezone.utc).timestamp())


def other(c):
    return PAIR[1] if c == PAIR[0] else PAIR[0]


def save_gz(path, obj):
    tmp = path.with_suffix(path.suffix + ".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8") as f:
        json.dump(obj, f)
    tmp.replace(path)


def load_gz(path):
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return json.load(f)


# ------------------------------------------------------------------------------------------------- RPC with cache
class Cache:
    """Key-value store (sqlite, zlib-compressed JSON) for RPC responses."""

    def __init__(self, path):
        self.db = sqlite3.connect(str(path))
        self.db.execute("CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v BLOB)")
        self.n = 0

    def get(self, k):
        r = self.db.execute("SELECT v FROM kv WHERE k=?", (k,)).fetchone()
        return None if r is None else json.loads(zlib.decompress(r[0]))

    def put(self, k, v):
        self.db.execute("INSERT OR REPLACE INTO kv VALUES (?,?)", (k, zlib.compress(json.dumps(v).encode())))
        self.n += 1
        if self.n % 500 == 0:
            self.db.commit()

    def commit(self):
        self.db.commit()


def slim_receipt(r):
    return {"status": r.get("status"), "blockNumber": r.get("blockNumber"), "transactionHash": r.get("transactionHash"),
            "from": r.get("from"), "to": r.get("to"),
            "logs": [{"address": x["address"], "topics": x["topics"], "data": x["data"], "logIndex": x["logIndex"],
                      "blockNumber": x.get("blockNumber"), "transactionHash": x.get("transactionHash")}
                     for x in r.get("logs", [])]}


class CachedRpc(Rpc):
    """incidents/rpc.Rpc with this task's endpoints, longer backoff, JSON-RPC batches, and a persistent cache of
    logs (per aligned block chunk), receipts, block timestamps and archive eth_call results."""

    def __init__(self, chain, cache):
        super().__init__(chain)
        self.urls = URLS[chain]
        self.cache = cache
        self.chunk = LOG_CHUNK[chain]
        self.stats = collections.Counter()
        self._head = None
        self.timeout = 90

    # --- transport
    def _post(self, url, payload):
        body = json.dumps(payload).encode()
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json",
                                                               "User-Agent": "bridge-limits-probe/1.0"})
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return json.loads(resp.read().decode())

    def call(self, method, params, retries=40):
        """Retries patiently: the public BSC endpoints answer HTTP 429 for minutes at a time."""
        last = None
        urls = LOG_URLS[self.chain] if method == "eth_getLogs" else self.urls
        for attempt in range(retries):
            url = urls[self.i % len(urls)]
            try:
                j = self._post(url, {"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
                self.calls += 1
                self.stats[method] += 1
                if "error" in j:
                    msg = str(j["error"])
                    low = msg.lower()
                    if any(k in low for k in ("rate limit", "too many requests", "429", "capacity", "try again")):
                        last = msg
                        self.stats["rate_limited"] += 1
                        time.sleep(min(60, 3 * (attempt + 1)))
                        continue
                    if any(k in low for k in RANGE_ERROR_KEYS):
                        raise RangeError(f"{url}: {msg[:200]}")
                    if "revert" in msg.lower():
                        raise RuntimeError(f"revert: {msg[:200]}")
                    last = msg
                    self.stats["rpc_error"] += 1
                    self.i += 1
                    time.sleep(min(30, 1.5 * (attempt + 1)))
                    continue
                return j["result"]
            except RangeError:
                raise
            except RuntimeError:
                raise
            except Exception as e:  # noqa: BLE001  HTTP 429/5xx, timeouts
                last = e
                self.stats["http_error"] += 1
                self.i += 1
                time.sleep(min(90, 5 * (attempt + 1)))
        raise RuntimeError(f"{self.chain} {method} failed: {last}")

    def batch(self, method, params_list, size=25):
        """Results in input order; a failed batch falls back to single calls."""
        out = [None] * len(params_list)
        for s in range(0, len(params_list), size):
            part = params_list[s:s + size]
            payload = [{"jsonrpc": "2.0", "id": s + k, "method": method, "params": p} for k, p in enumerate(part)]
            res = None
            for attempt in range(6):
                try:
                    res = self._post(self.urls[self.i % len(self.urls)], payload)
                    self.calls += 1
                    self.stats[method + "_batch"] += 1
                    if not isinstance(res, list):
                        raise RuntimeError(str(res)[:200])
                    break
                except Exception:  # noqa: BLE001
                    res = None
                    self.i += 1
                    time.sleep(min(60, 3 * (attempt + 1)))
            got = {x.get("id"): x for x in res} if res else {}
            for k, p in enumerate(part):
                x = got.get(s + k)
                if x is not None and "result" in x and x["result"] is not None:
                    out[s + k] = x["result"]
                else:
                    out[s + k] = self.call(method, p)
        return out

    # --- cached reads
    def head(self):
        if self._head is None:
            self._head = int(self.call("eth_blockNumber", []), 16)
        return self._head

    def _safe(self, b):
        return b <= self.head() - SAFE_DEPTH[self.chain]

    def block_ts(self, n):
        return self.block_ts_many([n])[n]

    def block_ts_many(self, blocks):
        out, todo = {}, []
        for b in blocks:
            v = self.cache.get(f"ts|{self.chain}|{b}")
            if v is None:
                todo.append(b)
            else:
                out[b] = v
        if todo:
            res = self.batch("eth_getBlockByNumber", [[hex(b), False] for b in todo])
            for b, r in zip(todo, res):
                out[b] = int(r["timestamp"], 16)
                if self._safe(b):
                    self.cache.put(f"ts|{self.chain}|{b}", out[b])
        return out

    def block_at(self, ts, lo=None, hi=None):
        """Smallest block with timestamp >= ts (cached)."""
        k = f"at|{self.chain}|{ts}"
        v = self.cache.get(k)
        if v is not None:
            return v
        top = self.head()
        if self.block_ts(top) < ts:
            return top + 1
        spb = SEC_PER_BLOCK[self.chain]
        guess = top - int((self.block_ts(top) - ts) / spb)
        w = max(100, int(3600 / spb))
        lo = max(1, min(guess, top) - w)
        while lo > 1 and self.block_ts(lo) >= ts:
            lo = max(1, lo - w)
            w *= 4
        w = max(100, int(3600 / spb))
        hi = min(top, max(guess, lo + 1) + w)
        while self.block_ts(hi) < ts:
            hi = min(top, hi + w)
            w *= 4
        tlo, thi = self.block_ts(lo), self.block_ts(hi)
        while hi - lo > 1:  # interpolation on the (nearly uniform) block times, kept shrinking at the edges
            mid = lo + int((ts - tlo) * (hi - lo) / max(1, thi - tlo))
            if hi - lo > 64:
                mid = min(max(mid, lo + (hi - lo) // 64), hi - (hi - lo) // 64)
            mid = min(hi - 1, max(lo + 1, mid))
            tm = self.block_ts(mid)
            if tm >= ts:
                hi, thi = mid, tm
            else:
                lo, tlo = mid, tm
        self.cache.put(k, hi)
        return hi

    def eth_call(self, to, data, block="latest"):
        if not isinstance(block, int):
            return super().eth_call(to, data, block)
        k = f"call|{self.chain}|{to.lower()}|{data}|{block}"
        v = self.cache.get(k)
        if v is not None:
            return v
        try:
            v = self.call("eth_call", [{"to": to, "data": data}, hex(block)])
        except RuntimeError as e:
            if not str(e).startswith("revert"):
                raise
            v = "0x"
        if self._safe(block):
            self.cache.put(k, v)
        return v

    def _logs_range(self, address, topics, b0, b1):
        try:
            return self.call("eth_getLogs", [{"address": address, "topics": topics,
                                              "fromBlock": hex(b0), "toBlock": hex(b1)}])
        except RangeError:
            if b1 - b0 < 50:
                raise
            mid = (b0 + b1) // 2
            return self._logs_range(address, topics, b0, mid) + self._logs_range(address, topics, mid + 1, b1)

    def logs(self, address, topics, b0, b1, step=None):
        if isinstance(address, list):
            address = sorted(a.lower() for a in address)
        else:
            address = address.lower()
        out = []
        for k in range(b0 // self.chunk, b1 // self.chunk + 1):
            lo, hi = max(b0, k * self.chunk), min(b1, (k + 1) * self.chunk - 1)
            if lo > hi:
                continue
            key = f"logs|{self.chain}|{json.dumps(address)}|{json.dumps(topics)}|{lo}|{hi}"
            v = self.cache.get(key)
            if v is None:
                v = [{x: lg.get(x) for x in ("address", "topics", "data", "blockNumber", "transactionHash",
                                             "logIndex")} for lg in self._logs_range(address, topics, lo, hi)]
                if self._safe(hi):
                    self.cache.put(key, v)
            out += v
        return out

    def receipt(self, txh):
        return self.receipts([txh])[txh]

    def receipts(self, hashes):
        out, todo = {}, []
        for h in dict.fromkeys(hashes):
            v = self.cache.get(f"rc|{self.chain}|{h}")
            if v is None:
                todo.append(h)
            else:
                out[h] = v
        if todo:
            res = self.batch("eth_getTransactionReceipt", [[h] for h in todo], size=20)
            for h, r in zip(todo, res):
                out[h] = slim_receipt(r)
                if self._safe(int(r["blockNumber"], 16)):
                    self.cache.put(f"rc|{self.chain}|{h}", out[h])
        return out


_CACHE = None


def rpcs():
    global _CACHE
    if _CACHE is None:
        RAW.mkdir(parents=True, exist_ok=True)
        _CACHE = Cache(RAW / "rpc_cache.sqlite")
    return {c: CachedRpc(c, _CACHE) for c in PAIR}


def commit():
    if _CACHE is not None:
        _CACHE.commit()


# ------------------------------------------------------------------------------------------------- explorer API
def http_json(url, params=None, tries=12):
    wait = 5.0
    full = url + ("?" + urllib.parse.urlencode(params) if params else "")
    for _ in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(full, headers=UA), timeout=180) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if e.code in (429, 500, 502, 503, 504):
                time.sleep(wait)
                wait = min(wait * 2, 300)
                continue
            raise
        except Exception:  # noqa: BLE001
            time.sleep(wait)
            wait = min(wait * 2, 300)
    raise RuntimeError(f"retries exhausted {full}")


def api_crawl(src, dst, cutoff=API_CUTOFF, limit=1000, sleep=1.5):
    """All explorer messages src -> dst sent after `cutoff`, newest first; pages cached under raw/ccip/api/."""
    d = RAW / "api" / f"{src}__{dst}"
    d.mkdir(parents=True, exist_ok=True)
    st_path = d / "state.json"
    filters = {"environment": "mainnet", "sourceChainSelector": SELECTOR[src], "destChainSelector": SELECTOR[dst]}
    st = json.loads(st_path.read_text()) if st_path.exists() else {"filters": filters, "pages": 0, "cursor": None,
                                                                    "done": False, "started_utc": utcnow()}
    if st.get("done") and st.get("cutoff", cutoff) > cutoff and st.get("cursor"):
        st["done"] = False  # extend to an earlier cutoff
    while not st["done"]:
        params = {"limit": limit, **filters}
        if st["cursor"]:
            params["cursor"] = st["cursor"]
        body = http_json(API, params)
        data = body.get("data", [])
        with gzip.open(d / f"page_{st['pages']:05d}.json.gz", "wt", encoding="utf-8") as f:
            json.dump({"fetched_utc": utcnow(), "params": params, "body": body}, f)
        st["pages"] += 1
        pag = body.get("pagination", {})
        st["cursor"] = pag.get("cursor")
        oldest = parse_ts(data[-1]["sendTimestamp"]) if data else None
        if not data or not pag.get("hasNextPage") or not st["cursor"] or (oldest is not None and oldest < cutoff):
            st["done"], st["cutoff"], st["finished_utc"] = True, cutoff, utcnow()
        st_path.write_text(json.dumps(st, indent=1))
        print(f"api {src}->{dst} page {st['pages'] - 1} n={len(data)} "
              f"oldest={data[-1]['sendTimestamp'] if data else None}", flush=True)
        if not st["done"]:
            time.sleep(sleep)
    return api_messages(src, dst)


def api_messages(src, dst):
    d = RAW / "api" / f"{src}__{dst}"
    out, seen = [], set()
    for p in sorted(d.glob("page_*.json.gz")):
        for m in load_gz(p)["body"].get("data", []):
            if m["messageId"] not in seen:
                seen.add(m["messageId"])
                out.append(m)
    return out


def api_detail(mid):
    """Explorer detail for one message (cached)."""
    d = RAW / "api" / "detail"
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{mid}.json"
    if p.exists():
        return json.loads(p.read_text())
    j = http_json(f"{API}/{mid}")
    p.write_text(json.dumps(j))
    time.sleep(0.5)
    return j


def step_pair():
    res = {"built_utc": utcnow(), "period_utc": [iso(T0), iso(T1)],
           "basis": "explorer API v2 /messages with source and destination selector filters, crawled back to "
                    "2026-07-01; a message counts when sourceTokenAmount is set and receiptTimestamp is in the period",
           "pairs": {}}
    for a, b in CANDIDATES:
        tot = {}
        for s, d in ((a, b), (b, a)):
            ms = api_crawl(s, d)
            inp = [m for m in ms if m.get("receiptTimestamp") and T0 <= parse_ts(m["receiptTimestamp"]) < T1]
            tok = [m for m in inp if m.get("sourceTokenAmount")]
            sent = [m for m in ms if T0 <= parse_ts(m["sendTimestamp"]) < T1 and m.get("sourceTokenAmount")]
            tot[f"{s}->{d}"] = {"messages_crawled": len(ms), "executed_in_period": len(inp),
                                "token_messages_executed_in_period": len(tok),
                                "token_messages_success": sum(m["status"] == "SUCCESS" for m in tok),
                                "token_messages_sent_in_period": len(sent),
                                "status_of_token_messages": dict(collections.Counter(m["status"] for m in tok))}
        tot["both_success"] = sum(v["token_messages_success"] for k, v in tot.items() if "->" in k)
        res["pairs"][f"{a}-{b}"] = tot
    # wider screen from the earlier global crawl (data/ccip/derived/transfers.csv.gz, ends 2026-10-15 ~17:15 UTC)
    try:
        import pandas as pd
        df = pd.read_csv(DOCS / "derived" / "transfers.csv.gz")
        df = df[(df.receipt_ts >= T0) & (df.receipt_ts < T1) & (df.status == "SUCCESS")].drop_duplicates("message_id")
        nonevm = ("solana", "aptos", "sui", "ton", "tron")
        df = df[~df.src.str.startswith(nonevm) & ~df.dst.str.startswith(nonevm)]
        df["pair"] = [" | ".join(sorted(x)) for x in zip(df.src, df.dst)]
        g = df.groupby("pair").size().sort_values(ascending=False)
        res["global_crawl_top_evm_pairs"] = {k: int(v) for k, v in g.head(12).items()}
        eth = g[[("mainnet" in k.split(" | ")) for k in g.index]]
        res["global_crawl_top_ethereum_pairs"] = {k: int(v) for k, v in eth.head(8).items()}
    except Exception as e:  # noqa: BLE001
        res["global_crawl_error"] = repr(e)
    (RAW / "pair_choice.json").write_text(json.dumps(res, indent=1))
    print(json.dumps(res, indent=1))


# ------------------------------------------------------------------------------------------------------- targets
def lane_tokens():
    """Tokens documented on both chains of the pair and supported on the lane in either direction, from the
    documentation snapshots (current, 2026-09-01, 2026-10-01): symbol -> chain -> entry."""
    out = {}
    snaps = [DOCS / "lanes_current", DOCS / "lanes_history" / "2026-09-01", DOCS / "lanes_history" / "2026-10-01"]
    a, b = DOCS_KEY[PAIR[0]], DOCS_KEY[PAIR[1]]
    for s in snaps:
        if not (s / "tokens.json").exists():
            continue
        toks = json.loads((s / "tokens.json").read_text(encoding="utf-8"))
        lanes = json.loads((s / "lanes.json").read_text(encoding="utf-8"))
        sup = set(((lanes.get(a) or {}).get(b) or {}).get("supportedTokens") or {}) | set(
            ((lanes.get(b) or {}).get(a) or {}).get("supportedTokens") or {})
        for sym, per in toks.items():
            if sym in sup and a in per and b in per:
                for c in PAIR:
                    e = per[DOCS_KEY[c]]
                    out.setdefault(sym, {}).setdefault(c, {
                        "token": (e.get("tokenAddress") or "").lower(), "decimals": e.get("decimals"),
                        "pool": (e.get("poolAddress") or "").lower(), "pool_type": e.get("poolType"),
                        "pool_type_and_version": e.get("typeAndVersion"), "doc_snapshot": s.name})
    return out


def step_targets():
    rp = rpcs()
    chains_doc = json.loads((DOCS / "lanes_current" / "chains.json").read_text(encoding="utf-8"))
    cfg = {"built_utc": utcnow(), "period_utc": [iso(T0), iso(T1)],
           "pair": {"name": PAIR_NAME, "chains": list(PAIR)}, "chains": {}, "tokens": {}, "token_index": {},
           "pools": {}, "notes": []}
    for c in PAIR:
        doc = chains_doc[DOCS_KEY[c]]
        r = rp[c]
        b0, b1 = r.block_at(T0), r.block_at(T1)
        cfg["chains"][c] = {"selector": SELECTOR[c], "docs_key": DOCS_KEY[c],
                            "router": doc["router"]["address"].lower(),
                            "token_admin_registry": doc["tokenAdminRegistry"]["address"].lower(),
                            "period_blocks": [b0, b1], "period_block_ts": [r.block_ts(b0), r.block_ts(b1 - 1)],
                            "onramps": [], "offramps": [], "router_events": []}
    cd._CFG.clear()
    for c in PAIR:
        r = rp[c]
        ch = cfg["chains"][c]
        b0, b1 = ch["period_blocks"]
        osel = int(SELECTOR[other(c)])
        cd.discover_ramps(r, c, b0, cfg)
        evs = r.logs(ch["router"], [[cd.TOPIC["onramp_set"], cd.TOPIC["offramp_added"], cd.TOPIC["offramp_removed"]],
                                    "0x" + format(osel, "064x")], b0, b1 - 1)
        name = {cd.TOPIC["onramp_set"]: "OnRampSet", cd.TOPIC["offramp_added"]: "OffRampAdded",
                cd.TOPIC["offramp_removed"]: "OffRampRemoved"}
        for lg in evs:
            blk = int(lg["blockNumber"], 16)
            ch["router_events"].append({"event": name[lg["topics"][0]], "block": blk, "ts": r.block_ts(blk),
                                        "ramp": "0x" + lg["data"][-40:]})
            cd.discover_ramps(r, c, blk, cfg)
        cd.discover_ramps(r, c, b1 - 1, cfg)
        # active intervals of the OnRamp toward the other chain inside the period
        sets = sorted([(e["block"], e["ramp"]) for e in ch["router_events"] if e["event"] == "OnRampSet"])
        first_on = cd._taddr(r.eth_call(ch["router"], cd.FN["getOnRamp"] + format(osel, "064x"), b0))
        seq = [(b0, first_on)] + sets
        for o in ch["onramps"]:
            spans = []
            for k, (blk, a) in enumerate(seq):
                if a == o["address"]:
                    spans.append([blk, (seq[k + 1][0] - 1) if k + 1 < len(seq) else b1 - 1])
            o["router_active_blocks"] = spans
        # OffRamps registered for the other chain at the start, end and router events
        reg0 = [a for s, a in cd.abi_decode(["(uint64,address)[]"], r.eth_call(ch["router"], cd.FN["getOffRamps"], b0))[0]
                if s == osel]
        reg1 = [a for s, a in cd.abi_decode(["(uint64,address)[]"],
                                            r.eth_call(ch["router"], cd.FN["getOffRamps"], b1 - 1))[0] if s == osel]
        for o in ch["offramps"]:
            o["registered_at_period_start"] = o["address"] in [x.lower() for x in reg0]
            o["registered_at_period_end"] = o["address"] in [x.lower() for x in reg1]
            o["router_events"] = [(e["event"], e["block"]) for e in ch["router_events"] if e["ramp"] == o["address"]]
        commit()
    # tokens and pools
    toks = lane_tokens()
    cfg["tokens"] = toks
    for c in PAIR:
        r = rp[c]
        ch = cfg["chains"][c]
        b0, b1 = ch["period_blocks"]
        idx = {}
        pools = set()
        for sym, per in toks.items():
            e = per.get(c)
            if not e or not e["token"]:
                continue
            idx[e["token"]] = {"symbol": sym, "decimals": e["decimals"]}
            if e["pool"]:
                pools.add(e["pool"])
            regs = []
            for blk in (b0, b1 - 1):
                p = cd._taddr(r.eth_call(ch["token_admin_registry"], cd.FN["getPool"] + "0" * 24 + e["token"][2:],
                                         blk))
                regs.append(p)
                if p != cd.ZERO:
                    pools.add(p)
            e["registry_pool_at_period_start"], e["registry_pool_at_period_end"] = regs
        cfg["token_index"][c] = idx
        cfg["pools"][c] = sorted(pools)
        commit()
    for c in PAIR:
        for kind in ("onramps", "offramps"):
            for o in cfg["chains"][c][kind]:
                o.pop("discovered_at_block", None)
    RAW.mkdir(parents=True, exist_ok=True)
    cd.TARGETS.write_text(json.dumps(cfg, indent=1))
    cd._CFG.clear()
    for c in PAIR:
        ch = cfg["chains"][c]
        print(c, "period blocks", ch["period_blocks"])
        for o in ch["onramps"]:
            print("  onramp", o["type_and_version"], o.get("router_active_blocks"))
        for o in ch["offramps"]:
            print("  offramp", o["type_and_version"], o["registered_at_period_start"], o["registered_at_period_end"],
                  o["router_events"], "linked", len(o.get("linked_onramps") or []))
        print("  router events", [(e["event"], e["block"]) for e in ch["router_events"]])
        print("  tokens", len(cfg["token_index"][c]), "pools", len(cfg["pools"][c]))


# ------------------------------------------------------------------------------------------------------ releases
def step_releases():
    rp = rpcs()
    cfg = cd.load_targets()
    for dst in PAIR:
        src = other(dst)
        r = rp[dst]
        b0, b1 = cfg["chains"][dst]["period_blocks"]
        step = int(2 * 86400 / SEC_PER_BLOCK[dst])
        rel, diag = [], {}
        for lo in range(b0, b1, step):
            hi = min(b1 - 1, lo + step - 1)
            got = cd.new_releases(r, dst, lo, hi, diag=diag)
            rel += got
            commit()
            print(f"{src}->{dst} blocks {lo}-{hi} releases {len(got)} total {len(rel)} calls {r.calls}", flush=True)
        save_gz(RAW / f"releases_{src}_{dst}.json.gz", {"built_utc": utcnow(), "releases": rel, "diag": diag,
                                                         "rpc_stats": dict(r.stats)})
        st = collections.Counter(cd.STATE[e["state"]] for e in diag.get("executions", []))
        print(f"{src}->{dst}: {len(rel)} releases from {len({x['message_id'] for x in rel})} messages; executions "
              f"{dict(st)}; success without release {len(diag.get('success_without_release', []))}; problems "
              f"{len(diag.get('no_pool_event', []))}", flush=True)


# ------------------------------------------------------------------------------------------------------- sources
def send_topics(fam, dest_sel):
    if fam == "1.5":
        return [cd.TOPIC["sent15"]]
    if fam == "1.6":
        return [cd.TOPIC["sent16"], "0x" + format(dest_sel, "064x")]
    return [cd.TOPIC["sent20"], "0x" + format(dest_sel, "064x")]


def bulk_send_index(r, src, dst, cfg):
    """messageId -> send log for every send toward dst by the OnRamps on src in [T0 - LOOKBACK, end of period]."""
    dest_sel = int(SELECTOR[dst])
    onr = {o["address"]: o["family"] for o in cfg["chains"][src]["onramps"]}
    for o in cfg["chains"][dst]["offramps"]:
        for a in o.get("linked_onramps") or []:
            onr.setdefault(a, o["family"])
    lo = r.block_at(T0 - LOOKBACK_S)
    hi = cfg["chains"][src]["period_blocks"][1] - 1
    idx, per = {}, collections.Counter()
    for a, fam in onr.items():
        for lg in r.logs(a, send_topics(fam, dest_sel), lo, hi):
            m = cd.decode_send_log(lg)
            if m is None:
                continue
            if fam == "1.5" and m["source_selector"] != int(SELECTOR[src]):
                continue
            idx[m["message_id"]] = lg
            per[(a, fam)] += 1
        commit()
    return idx, {"scan_blocks": [lo, hi], "per_onramp": {f"{fam}:{k}": v for (k, fam), v in per.items()}}


def send_onramps(src, dst, cfg):
    onr = {o["address"] for o in cfg["chains"][src]["onramps"]}
    for o in cfg["chains"][dst]["offramps"]:
        onr |= set(o.get("linked_onramps") or [])
    return onr


def hint_send_index(r, src, dst, cfg, mids):
    """messageId -> send log, located through the explorer's send transaction and checked on chain: the
    transaction's receipt must hold a send event with this messageId emitted by one of src's OnRamps toward dst."""
    api = {m["messageId"].lower(): m for m in api_crawl(src, dst)}
    onr = send_onramps(src, dst, cfg)
    want = {mid: api[mid]["sendTransactionHash"].lower() for mid in mids
            if mid in api and api[mid].get("sendTransactionHash")}
    txs = sorted(set(want.values()))
    recs = {}
    for k in range(0, len(txs), 200):
        recs.update(r.receipts(txs[k:k + 200]))
        commit()
        print(f"  hinted receipts {min(k + 200, len(txs))}/{len(txs)}", flush=True)
    idx = {}
    for mid, tx in want.items():
        for lg in recs[tx]["logs"]:
            if lg["topics"] and lg["topics"][0] in cd.SENT_TOPICS and lg["address"].lower() in onr:
                m = cd.decode_send_log(lg)
                if m and m["message_id"] == mid and m["dest_selector"] in (None, int(SELECTOR[dst])):
                    idx[mid] = lg
    return idx, recs, {"explorer_listed": len(want), "verified_on_chain": len(idx)}


# BSC log queries are throttled on every public endpoint tested (see URLS), so BSC source messages are located from
# the explorer's send transaction and checked on chain; Ethereum's OnRamps are scanned in full.
BULK_SCAN = {"ethereum": True, "bsc": False}


def step_sources():
    for src in PAIR:
        sources_for(src)


def sources_for(src):
    rp = rpcs()
    cfg = cd.load_targets()
    dst = other(src)
    r = rp[src]
    relf = load_gz(RAW / f"releases_{src}_{dst}.json.gz")
    rel = relf["releases"]
    if BULK_SCAN[src]:
        idx, scan = bulk_send_index(r, src, dst, cfg)
        method = "bulk_scan"
        print(f"{src}->{dst}: bulk index {len(idx)} sends; {scan['per_onramp']}", flush=True)
        txs = sorted({idx[x["message_id"]]["transactionHash"].lower() for x in rel if x["message_id"] in idx})
        recs = {}
        for k in range(0, len(txs), 400):
            recs.update(r.receipts(txs[k:k + 400]))
            commit()
            print(f"  receipts {min(k + 400, len(txs))}/{len(txs)}", flush=True)
    else:
        idx, recs, scan = hint_send_index(r, src, dst, cfg, {x["message_id"] for x in rel})
        method = "explorer_hint"
        print(f"{src}->{dst}: explorer-located sends {scan}", flush=True)
    blocks = sorted({int(idx[x["message_id"]]["blockNumber"], 16) for x in rel if x["message_id"] in idx})
    for k in range(0, len(blocks), 500):  # block timestamps in batches before the per-release loop
        r.block_ts_many(blocks[k:k + 500])
        commit()
    out, how = {}, collections.Counter()
    for n, x in enumerate(rel):
        key = f"{x['message_id']}|{x['token_index']}"
        lg = idx.get(x["message_id"])
        if lg is not None:
            s = cd.source_from_log(r, src, lg, x, receipt=recs[lg["transactionHash"].lower()])
            s["located_by"] = method
        else:
            s = cd.find_source(r, src, x)
            if s is not None:
                s["located_by"] = "find_source"
        how[(s or {}).get("located_by", "not_found")] += 1
        out[key] = s
        if n % 500 == 0:
            commit()
            print(f"  {n}/{len(rel)} {dict(how)} calls {r.calls}", flush=True)
    # executed successfully without a release although the send carried tokens (cross-check): the send event
    # where the bulk scan has it, else the explorer's token amount
    api = {m["messageId"].lower(): m for m in api_crawl(src, dst)}
    swr = []
    for e in relf["diag"].get("success_without_release", []):
        lg = idx.get(e["message_id"])
        m = cd.decode_send_log(lg) if lg else None
        if (m and m["tokens"]) or (m is None and (api.get(e["message_id"]) or {}).get("sourceTokenAmount")):
            swr.append({"message_id": e["message_id"], "tokens": len(m["tokens"]) if m else None,
                        "dst_tx": e["tx"], "evidence": "send event" if m else "explorer token amount"})
    save_gz(RAW / f"sources_{src}_{dst}.json.gz", {"built_utc": utcnow(), "sources": out, "scan": scan,
                                                    "located_by": dict(how),
                                                    "token_sends_executed_without_release": swr,
                                                    "rpc_stats": dict(r.stats)})
    commit()
    print(f"{src}->{dst}: sources {dict(how)}; token sends executed without a release: {len(swr)}", flush=True)


# --------------------------------------------------------------------------------------------------------- prices
class Prices:
    """DefiLlama /chart: hourly series (2 h tolerance), daily series (36 h tolerance), as data/legit/build_e59.py;
    cached under raw/ccip/px/."""

    def __init__(self, t0, t1):
        self.t0, self.t1 = t0, t1
        self.dir = RAW / "px"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.series = {}

    def _cached(self, name, url):
        p = self.dir / name
        if p.exists():
            return json.loads(p.read_text())
        j = http_json(url)
        p.write_text(json.dumps(j))
        time.sleep(0.4)
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
        span = int((self.t1 - self.t0) / 86400) + 6
        j = self._cached(f"1d_{safe}_{self.t0}.json",
                         f"https://coins.llama.fi/chart/{cid}?start={self.t0 - 2 * 86400}&span={span}&period=1d")
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

    def price(self, cids, ts):
        for cid in cids:
            h, d = self.load(cid)
            p = self.near(h, ts, 2 * 3600)
            if p is not None:
                return p, f"defillama 1h {cid.split(':')[0]}"
        for cid in cids:
            h, d = self.load(cid)
            p = self.near(d, ts, 36 * 3600)
            if p is not None:
                return p, f"defillama 1d {cid.split(':')[0]}"
        return None, ""


# --------------------------------------------------------------------------------------------------------- build
def fmt_amount(raw, dec):
    if dec is None:
        return ""
    q = decimal.Decimal(raw).scaleb(-int(dec))
    s = format(q.normalize(), "f")
    return s


def step_build():
    cfg = cd.load_targets()
    rows, pools_obs, extra = [], collections.defaultdict(dict), {}
    px = Prices(T0, T1)
    for src in PAIR:
        dst = other(src)
        rel = load_gz(RAW / f"releases_{src}_{dst}.json.gz")["releases"]
        srcs = load_gz(RAW / f"sources_{src}_{dst}.json.gz")["sources"]
        for x in rel:
            s = srcs.get(f"{x['message_id']}|{x['token_index']}")
            note = [f"ramp {x['offramp_family']}"]
            if x.get("note"):
                note.append(x["note"])
            pools_obs[dst].setdefault(x["pool"], {"role": "release", "events": collections.Counter()})
            pools_obs[dst][x["pool"]]["events"][x["pool_event"]] += 1
            # coin ids for the price: the token on Ethereum first, then on BSC
            sym = x["symbol"]
            cids = []
            per = cfg["tokens"].get(sym) or {}
            for c in ("ethereum", "bsc"):
                if per.get(c, {}).get("token"):
                    cids.append(f"{LLAMA[c]}:{per[c]['token']}")
            if f"{LLAMA[dst]}:{x['token']}" not in cids:
                cids.append(f"{LLAMA[dst]}:{x['token']}")
            p, how = px.price(cids, x["ts"])
            usd = round(p * x["amount_raw"] / 10 ** x["decimals"], 2) if (p is not None and x["decimals"] is not None) \
                else None
            if usd is None:
                note.append("unpriced")
            if s is None:
                matched, src_ts, src_block, age, vm, vd, agree = "no", "", "", "", "na", "none", "no"
                note.append("no send event with this messageId on the source chain")
            else:
                matched = "yes"
                src_ts, src_block = iso(s["ts"]), s["block"]
                age = x["ts"] - s["ts"]
                tok_i = x["token_index"]
                v = s["value"][tok_i] if tok_i < len(s["value"]) else None
                vm = "yes" if (v and v["detail"] != "none") else "no"
                vd = v["detail"] if v else "none"
                cmp_ = s.get("compare") or {}
                agree = "yes" if cmp_.get("agrees") else "no"
                if not cmp_.get("agrees"):
                    bad = [k for k in ("token", "amount", "recipient") if not cmp_.get(k)]
                    note.append("disagrees: " + ",".join(bad))
                if s.get("id_check") is False:
                    note.append("message id differs from keccak of the encoded message")
                if s["seq"] != x["seq"]:
                    note.append("sequence number differs")
                if s["ts"] < T0:
                    note.append("sent before the period")
                if s.get("located_by") == "find_source":
                    note.append("source located by sequence search")
                if v and v["source_pool"]:
                    pools_obs[src].setdefault(v["source_pool"], {"role": "lock_or_burn", "events": collections.Counter()})
                    pools_obs[src][v["source_pool"]]["events"][v["pool_event"] or "none"] += 1
                if v and v.get("moved_on_from_pool"):
                    note.append("locked amount moved on from the pool to a custody contract")
            rows.append({"_mid": x["message_id"], "pair": f"{src}->{dst}", "release_ts_utc": iso(x["ts"]),
                         "release_block": x["block"],
                         "token": sym, "amount": fmt_amount(x["amount_raw"], x["decimals"]),
                         "usd": "" if usd is None else f"{usd:.2f}", "kind": x["kind"], "matched": matched,
                         "src_ts_utc": src_ts, "src_block": src_block, "deposit_age_s": age, "value_moved": vm,
                         "value_detail": vd, "amount_agrees": agree, "note": "; ".join(note),
                         "_sort": (x["ts"], x["block"], x["exec_log_index"], x["token_index"]),
                         "_price_src": how})
    rows.sort(key=lambda r: r["_sort"])
    cols = ["pair", "release_ts_utc", "release_block", "token", "amount", "usd", "kind", "matched", "src_ts_utc",
            "src_block", "deposit_age_s", "value_moved", "value_detail", "amount_agrees", "note"]
    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / f"ccip_{PAIR_NAME}_releases.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)
    # pools observed (raw targets file only)
    rp = rpcs()
    tv = {}
    for c in PAIR:
        for a in pools_obs[c]:
            try:
                tv[(c, a)] = cd._call_str(rp[c], a, cfg["chains"][c]["period_blocks"][1] - 1)
            except Exception:  # noqa: BLE001
                tv[(c, a)] = None
    raw_cfg = json.loads(cd.TARGETS.read_text())
    raw_cfg["pools_observed"] = {c: {a: {"role": v["role"], "type_and_version": tv[(c, a)],
                                         "events": dict(v["events"])} for a, v in pools_obs[c].items()} for c in PAIR}
    cd.TARGETS.write_text(json.dumps(raw_cfg, indent=1))
    cd._CFG.clear()
    commit()
    summary = summarize(rows)
    (RAW / "build_summary.json").write_text(json.dumps(summary, indent=1))
    print(json.dumps(summary, indent=1))


def summarize(rows):
    import numpy as np
    out = {"rows": len(rows), "by_direction": {}}
    for d in sorted({r["pair"] for r in rows}):
        rr = [r for r in rows if r["pair"] == d]
        ages = np.array([r["deposit_age_s"] for r in rr if r["deposit_age_s"] != ""], dtype=float)
        q = {}
        if len(ages):
            for p in (0, 1, 5, 10, 25, 50, 75, 90, 95, 99, 100):
                q[f"p{p}"] = float(np.percentile(ages, p))
        out["by_direction"][d] = {
            "releases": len(rr), "messages": len({r["_mid"] for r in rr}),
            "usd": round(sum(float(r["usd"]) for r in rr if r["usd"] != ""), 2),
            "unpriced": sum(r["usd"] == "" for r in rr),
            "matched": sum(r["matched"] == "yes" for r in rr),
            "value_moved": sum(r["value_moved"] == "yes" for r in rr),
            "amount_agrees": sum(r["amount_agrees"] == "yes" for r in rr),
            "kind": dict(collections.Counter(r["kind"] for r in rr)),
            "value_detail": dict(collections.Counter(r["value_detail"] for r in rr)),
            "deposit_age_s_quantiles": q,
            "sent_before_period": sum("sent before the period" in r["note"] for r in rr),
            "tokens": dict(collections.Counter(r["token"] for r in rr).most_common()),
            "ramp": dict(collections.Counter(r["note"].split(";")[0] for r in rr)),
            "price_source": dict(collections.Counter(r["_price_src"].split(" ")[1] if r["_price_src"] else "none"
                                                     for r in rr)),
        }
    return out


# ------------------------------------------------------------------------------------------------------ coverage
ERROR_SIGS = ["ReceiverError(bytes)", "TokenHandlingError(bytes)", "TokenHandlingError(address,bytes)",
              "ExecutionError(bytes)", "ExecutionError(bytes32,bytes)", "NoStateProgressMade(bytes32,bytes)",
              "ReleaseOrMintBalanceMismatch(uint256,uint256,uint256)",
              "TokenMaxCapacityExceeded(uint256,uint256,address)", "TokenRateLimitReached(uint256,uint256,address)",
              "AggregateValueMaxCapacityExceeded(uint256,uint256)", "AggregateValueRateLimitReached(uint256,uint256)",
              "NotACompatiblePool(address)", "InvalidDataLength(uint256,uint256)", "CursedByRMN(uint64)",
              "InsufficientGasToCompleteTx(bytes4)", "Error(string)", "Panic(uint256)",
              "ERC20InsufficientBalance(address,uint256,uint256)", "ERC20InsufficientAllowance(address,uint256,uint256)",
              "SenderNotAllowed(address)", "RateLimitMustBeLessThanCapacity((bool,uint128,uint128))",
              "InvalidSourcePoolAddress(bytes)", "ChainNotAllowed(uint64)", "OutOfGas()"]
ERROR_SEL = {cd.keccak_hex(s.encode())[:10]: s for s in ERROR_SIGS}


def explain_revert(ret):
    """Outer and inner error names of an execution's revert data (inner = the wrapped bytes argument)."""
    if not ret or ret == "0x":
        return "empty", None
    sel = ret[:10]
    name = ERROR_SEL.get(sel, sel)
    inner = None
    try:
        if name in ("ReceiverError(bytes)", "TokenHandlingError(bytes)", "ExecutionError(bytes)"):
            inner = cd.abi_decode(["bytes"], "0x" + ret[10:])[0]
        elif name in ("TokenHandlingError(address,bytes)", "ExecutionError(bytes32,bytes)",
                      "NoStateProgressMade(bytes32,bytes)"):
            inner = cd.abi_decode(["bytes32" if "bytes32" in name else "address", "bytes"], "0x" + ret[10:])[1]
        elif name == "Error(string)":
            return name, cd.abi_decode(["string"], "0x" + ret[10:])[0][:80]
    except Exception:  # noqa: BLE001  (revert data is truncated to 260 bytes in the decoded event)
        return name, "undecoded"
    if inner is None:
        return name, None
    if inner == "0x":
        return name, "empty"
    s = inner[:10]
    n2 = ERROR_SEL.get(s, s)
    if n2 == "Error(string)":
        try:
            return name, "Error: " + cd.abi_decode(["string"], "0x" + inner[10:])[0][:80]
        except Exception:  # noqa: BLE001
            return name, n2
    return name, n2


def failures(src, dst):
    """Executions that ended in failure in the period, by revert reason, and whether the message succeeded later
    in the period."""
    rel = load_gz(RAW / f"releases_{src}_{dst}.json.gz")
    ex = rel["diag"]["executions"]
    ok_ids = {e["message_id"] for e in ex if e["state"] == 2}
    released = {x["message_id"] for x in rel["releases"]}
    fails = [e for e in ex if e["state"] == 3]
    out = collections.Counter()
    later = collections.Counter()
    for e in fails:
        o, i = explain_revert(e.get("return_data"))
        out[f"{o} / {i}"] += 1
        later["succeeded later in the period" if e["message_id"] in ok_ids else "no success in the period"] += 1
    return {"failed_executions": len(fails), "messages": len({e["message_id"] for e in fails}),
            "with_tokens_released_later": len({e["message_id"] for e in fails} & released),
            "reasons": dict(out.most_common()), "outcome": dict(later)}


def step_coverage():
    res = {"built_utc": utcnow(), "directions": {}}
    for src in PAIR:
        dst = other(src)
        rel = load_gz(RAW / f"releases_{src}_{dst}.json.gz")
        srcs = load_gz(RAW / f"sources_{src}_{dst}.json.gz")["sources"]
        api = {m["messageId"].lower(): m for m in api_crawl(src, dst)}
        chain_msgs = {}
        for x in rel["releases"]:
            chain_msgs.setdefault(x["message_id"], x)
        execs = {e["message_id"]: e for e in rel["diag"]["executions"] if e["state"] == 2}
        all_exec = collections.defaultdict(list)
        for e in rel["diag"]["executions"]:
            all_exec[e["message_id"]].append(e)
        api_tok = {k: m for k, m in api.items() if m.get("sourceTokenAmount") and m["status"] == "SUCCESS"
                   and m.get("receiptTimestamp") and T0 <= parse_ts(m["receiptTimestamp"]) < T1}
        day = lambda ts: iso(ts)[:10]  # noqa: E731
        days = sorted({day(t) for t in range(T0, T1, 86400)})
        on_day = collections.Counter(day(x["ts"]) for x in chain_msgs.values())
        api_day = collections.Counter(iso(parse_ts(m["receiptTimestamp"]))[:10] for m in api_tok.values())
        diffs = []
        for mid, x in chain_msgs.items():
            m = api.get(mid)
            if mid in api_tok:
                d_api = iso(parse_ts(api_tok[mid]["receiptTimestamp"]))[:10]
                if d_api != day(x["ts"]):
                    diffs.append({"message_id": mid, "side": "both", "reason": "different day",
                                  "chain_ts": x["ts"], "api_receipt": api_tok[mid]["receiptTimestamp"]})
                continue
            if m is None:
                det = api_detail(mid)
                s = srcs.get(f"{mid}|0") or {}
                diffs.append({"message_id": mid, "side": "chain_only",
                              "reason": "not in the explorer crawl" + (" (sent before the crawl cutoff)"
                                                                       if s and s.get("ts", T0) < API_CUTOFF else ""),
                              "detail_found": bool(det), "detail_status": (det or {}).get("status"),
                              "detail_receipt": (det or {}).get("receiptTimestamp"),
                              "detail_token": bool((det or {}).get("tokenAmounts") or (det or {}).get(
                                  "sourceTokenAmount"))})
            elif not m.get("sourceTokenAmount"):
                diffs.append({"message_id": mid, "side": "chain_only", "reason": "explorer lists no token amount",
                              "api_status": m["status"]})
            elif m["status"] != "SUCCESS":
                diffs.append({"message_id": mid, "side": "chain_only", "reason": f"explorer status {m['status']}",
                              "api_receipt": m.get("receiptTimestamp"), "chain_ts": x["ts"],
                              "chain_attempts": [cd.STATE[e["state"]] for e in all_exec[mid]]})
            else:
                diffs.append({"message_id": mid, "side": "chain_only", "reason": "explorer receipt time outside the "
                              "period", "api_receipt": m.get("receiptTimestamp"), "chain_ts": x["ts"]})
        for mid, m in api_tok.items():
            if mid in chain_msgs:
                continue
            e = execs.get(mid)
            rec = {"message_id": mid, "side": "api_only", "api_receipt": m["receiptTimestamp"],
                   "chain_attempts": [cd.STATE[q["state"]] for q in all_exec.get(mid, [])]}
            if e is not None:
                rec["reason"] = "executed successfully on chain without a pool release in the span"
            elif mid in all_exec:
                rec["reason"] = "on-chain execution not successful in the period"
            else:
                rec["reason"] = "no execution event in the period on the configured OffRamps"
            diffs.append(rec)
        daily = [{"day": d_, "onchain": on_day.get(d_, 0), "api": api_day.get(d_, 0)} for d_ in days]
        api_status = collections.Counter(m["status"] for m in api.values() if m.get("sourceTokenAmount")
                                         and m.get("receiptTimestamp") and T0 <= parse_ts(m["receiptTimestamp"]) < T1)
        res["directions"][f"{src}->{dst}"] = {
            "onchain_messages": len(chain_msgs), "onchain_releases": len(rel["releases"]),
            "api_messages": len(api_tok), "api_token_messages_by_status": dict(api_status),
            "both": len(set(chain_msgs) & set(api_tok)), "daily": daily,
            "days_equal": sum(r["onchain"] == r["api"] for r in daily),
            "differences": diffs,
            "difference_reasons": dict(collections.Counter(f"{q['side']}: {q['reason']}" for q in diffs)),
            "failed_executions": failures(src, dst)}
        print(f"{src}->{dst}: onchain {len(chain_msgs)} api {len(api_tok)} both "
              f"{len(set(chain_msgs) & set(api_tok))}; days equal {res['directions'][f'{src}->{dst}']['days_equal']}"
              f"/{len(days)}; {res['directions'][f'{src}->{dst}']['difference_reasons']}", flush=True)
    (RAW / "coverage.json").write_text(json.dumps(res, indent=1))


# ------------------------------------------------------------------------------------------------------ selftest
def step_selftest(n_sample=40, seed=7):
    """find_source (sequence search) against the bulk path on a random sample of releases; new_releases through
    the plain incidents/rpc.Rpc client on a short range against the cached run."""
    rp = rpcs()
    cfg = cd.load_targets()
    rng = random.Random(seed)
    out = {"built_utc": utcnow(), "find_source": {}, "plain_rpc_new_releases": {}}
    for src in PAIR:
        dst = other(src)
        rel = load_gz(RAW / f"releases_{src}_{dst}.json.gz")["releases"]
        srcs = load_gz(RAW / f"sources_{src}_{dst}.json.gz")["sources"]
        bulk = [x for x in rel if (srcs.get(f"{x['message_id']}|{x['token_index']}") or {}).get("located_by")
                in ("bulk_scan", "explorer_hint")]
        sample = rng.sample(bulk, min(n_sample, len(bulk)))
        same, diff = 0, []
        for x in sample:
            a = srcs[f"{x['message_id']}|{x['token_index']}"]
            b = cd.find_source(rp[src], src, x)
            keys = ("message_id", "block", "tx", "seq", "value_moved", "value_detail")
            if b is not None and all(a[k] == b[k] for k in keys) and a["compare"] == b["compare"]:
                same += 1
            else:
                diff.append(x["message_id"])
        out["find_source"][f"{src}->{dst}"] = {"sample": len(sample), "same": same, "different": diff}
        commit()
        print(f"selftest find_source {src}->{dst}: {same}/{len(sample)} same", flush=True)
    # plain client, the last hours of the period on each destination (six on Ethereum, two on BSC, where the
    # plain client's 5,000-block log steps and single calls meet the endpoint's rate limit)
    for dst in PAIR:
        src = other(dst)
        b1 = cfg["chains"][dst]["period_blocks"][1] - 1
        lo = b1 - int({"ethereum": 6, "bsc": 2}[dst] * 3600 / SEC_PER_BLOCK[dst])
        plain = Rpc(dst)
        plain.urls = LOG_URLS[dst] + [u for u in URLS[dst] if u not in LOG_URLS[dst]]
        got, err = None, None
        for attempt in range(6):  # the plain client gives up after six quick retries; HTTP 429 windows are longer
            try:
                got = cd.new_releases(plain, dst, lo, b1)
                break
            except RuntimeError as e:
                err = str(e)[:200]
                time.sleep(120)
        if got is None:
            out["plain_rpc_new_releases"][f"{src}->{dst}"] = {"blocks": [lo, b1], "error": err}
            continue
        cached = [x for x in load_gz(RAW / f"releases_{src}_{dst}.json.gz")["releases"] if lo <= x["block"] <= b1]
        k = lambda x: (x["message_id"], x["token_index"], x["amount_raw"], x["recipient"], x["kind"])  # noqa: E731
        out["plain_rpc_new_releases"][f"{src}->{dst}"] = {
            "blocks": [lo, b1], "plain": len(got), "cached_run": len(cached),
            "same": sorted(map(k, got)) == sorted(map(k, cached)), "plain_calls": plain.calls}
        print(f"selftest plain new_releases {src}->{dst}: {len(got)} vs {len(cached)}", flush=True)
    (RAW / "selftest.json").write_text(json.dumps(out, indent=1))


STEPS = {"pair": step_pair, "targets": step_targets, "releases": step_releases, "sources": step_sources,
         "build": step_build, "coverage": step_coverage, "selftest": step_selftest}

if __name__ == "__main__":
    which = sys.argv[1:] or ["all"]
    if which == ["all"]:
        which = ["pair", "targets", "releases", "sources", "build", "coverage", "selftest"]
    for s in which:
        t = time.time()
        STEPS[s]()
        commit()
        print(f"== step {s} done in {time.time() - t:.0f}s", flush=True)
