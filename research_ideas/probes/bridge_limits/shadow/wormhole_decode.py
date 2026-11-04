"""Wormhole token bridge: releases on a destination chain and their source messages (shadow run, 2026-10-16).

The collector (shadow/wormhole_collect.py) and the live monitor both use this module, so the dataset and the
monitor decode releases and source messages with the same code.

Contracts and their roles (addresses live only in raw/wormhole/targets.json, never in this file):
- core contract, one per chain: every message goes through it; it emits
  LogMessagePublished(address indexed sender, uint64 sequence, uint32 nonce, bytes payload, uint8 consistencyLevel).
  Sequences count up by one per sender.
- token bridge, one per chain, the sender of transfer messages. On the source chain it takes a token native to
  that chain into custody (the gas coin is wrapped first) or burns a wrapped token it issued, then publishes a
  transfer message. On the destination chain it completes a transfer from the signed message (VAA): it emits
  TransferRedeemed(uint16 indexed emitterChainId, bytes32 indexed emitterAddress, uint64 indexed sequence) and then
  releases the tokens. Kinds of release: `unlock` (a transfer out of custody), `unlock_native` (custody's wrapped
  gas coin withdrawn and paid out as the gas coin, which leaves no token log), `mint` (a mint of the wrapped
  token). A relayer fee named in the message goes to the caller before the rest goes to the recipient.

Transfer payloads (big-endian): id 1 = Transfer: id(1) amount(32) tokenAddress(32) tokenChain(2) to(32)
toChain(2) fee(32); id 3 = TransferWithPayload: id(1) amount(32) tokenAddress(32) tokenChain(2) to(32) toChain(2)
fromAddress(32) payload(rest). Amounts carry at most 8 decimals ("normalized"); a token with d > 8 decimals moves
amount * 10**(d - 8) base units.

Interface for the live monitor (rpc_* is an incidents/rpc.py Rpc, or the Client below, which adds the endpoints
tested on 2026-10-16, JSON-RPC batches and an optional on-disk cache):
    new_releases(rpc_dst, dst_chain, from_block, to_block) -> list of release dicts, sorted by (block, log_index)
    find_source(rpc_src, src_chain, release) -> source dict with the value check and the agreement check, or None
The pair is the one recorded in raw/wormhole/targets.json ("pair"), chosen by `wormhole_collect.py pairs`.
"""
from __future__ import annotations

import collections
import json
import pathlib
import random
import sqlite3
import sys
import threading
import time
import urllib.error
import urllib.request
import zlib
from decimal import Decimal

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
RAW = HERE / "raw" / "wormhole"
TARGETS_PATH = RAW / "targets.json"
sys.path.insert(0, str(ROOT / "incidents"))
from rpc import Rpc, RangeError, TRANSFER  # noqa: E402

# Wormhole chain ids (sdk/vaa/structs.go) of the seven candidate chains, and EVM chain ids
WH_CHAIN = {"ethereum": 2, "bsc": 4, "polygon": 5, "avalanche": 6, "arbitrum": 23, "optimism": 24, "base": 30}
WH_NAME = {v: k for k, v in WH_CHAIN.items()}
EVM_CHAIN = {"ethereum": 1, "bsc": 56, "polygon": 137, "avalanche": 43114, "arbitrum": 42161, "optimism": 10, "base": 8453}
GAS_SYMBOL = {"ethereum": "ETH", "bsc": "BNB", "polygon": "POL", "avalanche": "AVAX", "arbitrum": "ETH",
              "optimism": "ETH", "base": "ETH"}
# DefiLlama coin prefixes by Wormhole chain id (token origins that can be priced by address)
LLAMA = {1: "solana", 2: "ethereum", 4: "bsc", 5: "polygon", 6: "avax", 13: "klaytn", 14: "celo", 16: "moonbeam",
         23: "arbitrum", 24: "optimism", 25: "xdai", 30: "base", 34: "scroll", 35: "mantle", 36: "blast",
         38: "linea", 39: "berachain", 44: "unichain", 45: "wc", 46: "ink", 48: "monad", 52: "sonic"}

LMP = "0x6eb224fb001ed210e379b335e35efe88672a8ce935d981a6896b27ffdf52a3b2"        # LogMessagePublished
REDEEMED = "0xcaf280c8cfeba144da67230d9b009c8f868a75bac9a528fa0474be1ba317c169"   # TransferRedeemed
DEPOSIT = "0xe1fffcc4923d04b559f4d29a8bfc6cda04eb5b0d3c460751c2402c5c5cc9109c"    # Deposit(address,uint256)
WITHDRAWAL = "0x7fcf532c15f0a6db0bd6d0e038bea71d30d808c7d98cb3bf7268a95bf5081b65"  # Withdrawal(address,uint256)
ZERO = "0x" + "0" * 40
SEL = {"wrappedAsset": "0x1ff1e286", "isWrappedAsset": "0x1a2be4da", "WETH": "0xad5c4648", "chainId": "0x9a8a0592",
       "nativeContract": "0x3d6c043b", "decimals": "0x313ce567", "symbol": "0x95d89b41", "wormhole": "0x84acd1bb",
       "bridgeContracts": "0xad66a5f1", "nextSequence": "0x4cf842b5"}

# Public endpoints tested 2026-10-16: (url, largest eth_getLogs block range answered with an address filter).
# Tenderly answers up to 20,000 results per query and errors beyond; it once returned an empty list for a
# 1,000,000-block Ethereum query with more results than that, so empty answers over long ranges are re-checked.
ENDPOINTS = {
    "ethereum": [("https://mainnet.gateway.tenderly.co", 50_000), ("https://eth.api.pocket.network", 10_000),
                 ("https://rpc.mevblocker.io", 10_000), ("https://ethereum-rpc.publicnode.com", 10_000)],
    "bsc": [(__import__("os").environ.get("BSC_RPC_URL", "https://bsc-dataseed.bnbchain.org"), 50_000),
            ("https://rpc-bsc.48.club", 5_000), ("https://bsc.api.pocket.network", 1_000)],
    "polygon": [("https://polygon.gateway.tenderly.co", 200_000), ("https://rpc-mainnet.matic.quiknode.pro", 10_000),
                ("https://poly.api.pocket.network", 10_000)],
    "avalanche": [("https://avalanche.gateway.tenderly.co", 200_000), ("https://avax.api.pocket.network", 50_000),
                  ("https://avalanche-c-chain.publicnode.com", 50_000)],
    "arbitrum": [("https://arb1.arbitrum.io/rpc", 1_000_000), ("https://arbitrum.gateway.tenderly.co", 1_000_000)],
    "optimism": [("https://optimism.gateway.tenderly.co", 200_000), ("https://op.api.pocket.network", 100_000),
                 ("https://mainnet.optimism.io", 10_000)],
    "base": [("https://base.api.pocket.network", 100_000), ("https://base-rpc.publicnode.com", 1_000),
             ("https://base.gateway.tenderly.co", 1_000)],
}
# second providers for the cross-provider completeness check (first entry of each list not used above first)
ALT_LOGS = {"ethereum": [("https://eth.api.pocket.network", 10_000), ("https://rpc.mevblocker.io", 10_000)],
            "bsc": [("https://rpc-bsc.48.club", 5_000), ("https://bsc.rpc.blxrbdn.com", 5_000)],
            "polygon": [("https://rpc-mainnet.matic.quiknode.pro", 10_000), ("https://poly.api.pocket.network", 10_000)],
            "avalanche": [("https://avax.api.pocket.network", 50_000)],
            "arbitrum": [("https://arbitrum.gateway.tenderly.co", 1_000_000)],
            "optimism": [("https://op.api.pocket.network", 100_000)],
            "base": [("https://base-rpc.publicnode.com", 1_000)]}
# debug_traceTransaction (callTracer) answered on these (2026-10-16); used only to see gas-coin payouts
TRACE = {"ethereum": ["https://eth.api.pocket.network", "https://eth.drpc.org"],
         "bsc": ["https://bsc.api.pocket.network", __import__("os").environ.get("BSC_RPC_URL", "https://bsc-dataseed.bnbchain.org")],
         "base": ["https://base.api.pocket.network"], "polygon": ["https://rpc-mainnet.matic.quiknode.pro"],
         "optimism": ["https://op.api.pocket.network"], "arbitrum": [], "avalanche": []}
# headers, receipts, transactions and calls at the latest block (JSON-RPC batches answered in full, 2026-10-16);
# chains not listed use their log endpoints
GENERAL = {"ethereum": ["https://ethereum-rpc.publicnode.com", "https://mainnet.gateway.tenderly.co",
                        "https://rpc.mevblocker.io", "https://eth.api.pocket.network"],
           "bsc": ["https://bsc-dataseed.bnbchain.org", "https://bsc-dataseed1.defibit.io",
                   "https://bsc-dataseed1.ninicoin.io", "https://bsc-dataseed2.bnbchain.org",
                   "https://bsc-rpc.publicnode.com"]}
# eth_call at past blocks (archive state)
ARCHIVE = {"ethereum": ["https://mainnet.gateway.tenderly.co", "https://rpc.mevblocker.io", "https://eth.api.pocket.network"],
           "bsc": [__import__("os").environ.get("BSC_RPC_URL", "https://bsc-dataseed.bnbchain.org"),
                   "https://bsc-mainnet.public.blastapi.io", "https://bsc.api.pocket.network"]}
BLOCK_TIME = {"ethereum": 12.0, "bsc": 0.45, "polygon": 1.5, "avalanche": 0.92, "arbitrum": 0.265, "optimism": 2.0,
              "base": 2.0}
EMPTY_GUARD = 50_000   # an empty eth_getLogs answer over more blocks than this is re-checked in four parts
LOG_RANGE_KEYS = ("block range", "range too large", "returned more than", "max block range", "maximum block range",
                  "exceeds max", "too many results", "response size", "range is over", "range exceeds",
                  "query timeout", "more than 10000")


def load_targets(path=None):
    return json.loads(pathlib.Path(path or TARGETS_PATH).read_text(encoding="utf-8"))


def pair_of(T=None):
    T = T or load_targets()
    return tuple(T["pair"])


def other_chain(dst_chain, T=None):
    a, b = pair_of(T)
    return b if dst_chain == a else a


# ------------------------------------------------------------------------------------------------ small helpers
def hx(v):
    return int(v, 16) if isinstance(v, str) else int(v)


def topic_u(n):
    return "0x" + format(int(n), "064x")


def addr_topic(a):
    return "0x" + "0" * 24 + a.lower()[2:]


def addr_from_word(w):
    return "0x" + w[-40:].lower()


def word_is_address(w32):
    """True when a bytes32 (hex string) holds a 20-byte address (12 leading zero bytes)."""
    h = w32.lower()[2:] if w32.startswith("0x") else w32.lower()
    return len(h) == 64 and h[:24] == "0" * 24


def normalize(amount, decimals):
    return amount // 10 ** (decimals - 8) if decimals > 8 else amount


def denormalize(amount, decimals):
    return amount * 10 ** (decimals - 8) if decimals > 8 else amount


def units(raw, decimals):
    """Exact decimal string of raw / 10**decimals."""
    q = Decimal(int(raw)).scaleb(-int(decimals))
    s = format(q.normalize(), "f")
    return s if s != "-0" else "0"


B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def b58(b: bytes):
    n = int.from_bytes(b, "big")
    s = ""
    while n:
        n, r = divmod(n, 58)
        s = B58[r] + s
    return "1" * (len(b) - len(b.lstrip(b"\0"))) + s


# ------------------------------------------------------------------------------------------------ decoding
def decode_transfer(payload: bytes):
    """Token bridge transfer payload (id 1 or 3) -> dict, or None for other payloads."""
    if len(payload) < 133 or payload[0] not in (1, 3):
        return None
    d = {"payload_id": payload[0], "amount": int.from_bytes(payload[1:33], "big"),
         "token_address": "0x" + payload[33:65].hex(), "token_chain": int.from_bytes(payload[65:67], "big"),
         "to": "0x" + payload[67:99].hex(), "to_chain": int.from_bytes(payload[99:101], "big")}
    if payload[0] == 1:
        d["fee"] = int.from_bytes(payload[101:133], "big")
        d["extra_bytes"] = len(payload) - 133
    else:
        d["fee"] = 0
        d["from_address"] = "0x" + payload[101:133].hex()
        d["extra_bytes"] = len(payload) - 133
    return d


def decode_lmp(log):
    """LogMessagePublished log -> sender, sequence, nonce, consistency, payload bytes, position."""
    d = bytes.fromhex(log["data"][2:])
    off = int.from_bytes(d[64:96], "big")
    n = int.from_bytes(d[off:off + 32], "big")
    return {"sender": addr_from_word(log["topics"][1]), "sequence": int.from_bytes(d[0:32], "big"),
            "nonce": int.from_bytes(d[32:64], "big"), "consistency": int.from_bytes(d[96:128], "big"),
            "payload": d[off + 32:off + 32 + n], "block": hx(log["blockNumber"]), "tx": log["transactionHash"].lower(),
            "log_index": hx(log["logIndex"])}


def find_vaa(calldata_hex, emitter_chain, emitter32, sequence):
    """Locate the signed message (VAA) for (emitter chain, emitter, sequence) in transaction input, also when it
    is nested in the input of a contract that calls the token bridge. Returns the body's timestamp (the source
    block's time), nonce, consistency level and, when the ABI length word around it can be read, the payload."""
    if not calldata_hex or len(calldata_hex) < 10:
        return None
    cd = bytes.fromhex(calldata_hex[2:])
    pat = int(emitter_chain).to_bytes(2, "big") + bytes.fromhex(emitter32[2:]) + int(sequence).to_bytes(8, "big")
    i = cd.find(pat)
    fallback = None
    while i >= 0:
        body = i - 8
        if body >= 0:
            head = {"timestamp": int.from_bytes(cd[body:body + 4], "big"),
                    "nonce": int.from_bytes(cd[body + 4:body + 8], "big"), "consistency": cd[i + 42] if i + 42 < len(cd) else None}
            for nsig in range(1, 20):
                start = body - 6 - 66 * nsig
                if start < 0:
                    break
                if cd[start] == 1 and cd[start + 5] == nsig:
                    head.update({"guardian_set": int.from_bytes(cd[start + 1:start + 5], "big"), "signatures": nsig})
                    if start >= 32:
                        L = int.from_bytes(cd[start - 32:start], "big")
                        end = start + L
                        if i + 43 + 133 <= end <= len(cd):
                            head["payload"] = cd[i + 43:end]
                            return head
                    fallback = fallback or head
                    break
            fallback = fallback or head
        i = cd.find(pat, i + 1)
    return fallback


# ------------------------------------------------------------------------------------------------ RPC client
class Cache:
    """sqlite key-value store for deterministic RPC answers (receipts, transactions, logs of past blocks,
    block timestamps, traces); values zlib-compressed JSON."""

    def __init__(self, path):
        path = pathlib.Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), timeout=120, check_same_thread=False)
        self.db.execute("CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v BLOB)")
        self.db.execute("CREATE TABLE IF NOT EXISTS ts (b INTEGER PRIMARY KEY, t INTEGER)")
        self.db.commit()
        self.lock = threading.Lock()

    def get(self, k):
        with self.lock:
            r = self.db.execute("SELECT v FROM kv WHERE k=?", (k,)).fetchone()
        return None if r is None else json.loads(zlib.decompress(r[0]).decode())

    def put(self, k, v, commit=True):
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO kv VALUES (?,?)", (k, zlib.compress(json.dumps(v).encode(), 6)))
            if commit:
                self.db.commit()

    def get_ts(self, blocks):
        out = {}
        blocks = list(blocks)
        with self.lock:
            for i in range(0, len(blocks), 500):
                part = blocks[i:i + 500]
                q = "SELECT b, t FROM ts WHERE b IN (%s)" % ",".join("?" * len(part))
                out.update({b: t for b, t in self.db.execute(q, part)})
        return out

    def put_ts(self, d):
        with self.lock:
            self.db.executemany("INSERT OR REPLACE INTO ts VALUES (?,?)", list(d.items()))
            self.db.commit()


class Client(Rpc):
    """incidents/rpc.py Rpc with the endpoints above, JSON-RPC batches, per-endpoint eth_getLogs ranges, re-checks
    of empty answers over long ranges, retries with backoff on HTTP 429, and an optional sqlite cache."""

    CACHEABLE = ("eth_getTransactionReceipt", "eth_getTransactionByHash", "debug_traceTransaction")

    def __init__(self, chain, cache_dir=None, endpoints=None, timeout=90, batch_size=20):
        super().__init__(chain, timeout)
        self.eps = list(endpoints or ENDPOINTS[chain])               # eth_getLogs: (url, largest range)
        self.urls = list(GENERAL.get(chain) or [u for u, _ in self.eps])   # headers, receipts, transactions, calls
        self.archive = list(ARCHIVE.get(chain) or self.urls)          # eth_call at past blocks
        self.chunk = self.eps[0][1]
        self.i = 0
        self.rot = collections.Counter()
        self.batch_size = batch_size
        self.cache = Cache(pathlib.Path(cache_dir) / f"{chain}.sqlite") if cache_dir else None
        self.stats = collections.Counter()
        self._final = None

    # -- transport
    # minimum seconds between requests to one endpoint; the BSC demo key throttled after about a dozen quick
    # requests on 2026-10-16 and recovered at one request per 5 s
    PACE = {"nodereal.io": 5.0, "pocket.network": 0.1, "tenderly.co": 0.1, "publicnode.com": 0.1, "48.club": 0.5}
    BACKOFF_429 = {"nodereal.io": 30.0}

    def _post(self, url, payload):
        gap = next((v for k, v in self.PACE.items() if k in url), 0.0)
        last = getattr(self, "_last", {})
        self._last = last
        wait = last.get(url, 0.0) + gap - time.time()
        if wait > 0:
            time.sleep(wait)
        last[url] = time.time()
        body = json.dumps(payload).encode()
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json",
                                                              "User-Agent": "bridge-limits-probe/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                txt = r.read().decode()
        except urllib.error.HTTPError as e:
            self.stats[f"http_{e.code}"] += 1
            if e.code == 413:
                raise RangeError(f"{url}: HTTP 413")
            if e.code == 429:
                time.sleep(next((v for k, v in self.BACKOFF_429.items() if k in url), 2.0) + random.random() * 2.0)
            raise
        self.calls += 1
        self.stats["calls"] += 1
        return json.loads(txt)

    def _sleep(self, attempt):
        time.sleep(min(30.0, 0.8 * (attempt + 1)) + random.random() * 0.5)

    def _key(self, method, params):
        if method in self.CACHEABLE:
            return method + "|" + json.dumps(params, sort_keys=True).lower()
        if method == "eth_call" and isinstance(params[1], str) and params[1].startswith("0x"):
            return method + "|" + json.dumps(params, sort_keys=True).lower()
        return None

    def _pool(self, method, params):
        if method == "eth_call" and len(params) > 1 and isinstance(params[1], str) and params[1].startswith("0x"):
            return "archive", self.archive
        return "general", self.urls

    def call(self, method, params, retries=10, urls=None):
        key = self._key(method, params) if self.cache else None
        if key:
            v = self.cache.get(key)
            if v is not None:
                return v
        name, pool = (None, urls) if urls else self._pool(method, params)
        last = None
        for attempt in range(retries):
            url = pool[(self.rot[name] if name else attempt) % len(pool)]
            try:
                j = self._post(url, {"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
            except RangeError:
                raise
            except Exception as e:  # noqa: BLE001  network, HTTP 429/5xx, bad JSON
                last = e
                if name:
                    self.rot[name] += 1
                self._sleep(attempt)
                continue
            if isinstance(j, dict) and "error" in j:
                msg = str(j["error"])
                if method == "eth_getLogs" and any(k in msg.lower() for k in LOG_RANGE_KEYS):
                    raise RangeError(f"{url}: {msg[:200]}")
                last = RuntimeError(f"{url}: {msg[:200]}")
                if method == "eth_call" and "execution reverted" in msg.lower():
                    raise last
                if name:
                    self.rot[name] += 1
                self._sleep(attempt)
                continue
            res = j.get("result") if isinstance(j, dict) else None
            if res is None and method in ("eth_getTransactionReceipt", "eth_getTransactionByHash", "eth_getBlockByNumber"):
                last = RuntimeError(f"{url}: null result for {method}")
                if name:
                    self.rot[name] += 1
                self._sleep(attempt)
                continue
            if key:
                self.cache.put(key, res)
            return res
        raise RuntimeError(f"{self.chain} {method} failed: {last}")

    def batch(self, method, plist, size=None):
        """Results of one method over many parameter lists, through JSON-RPC batches (cache first)."""
        size = size or self.batch_size
        res = [None] * len(plist)
        todo = []
        for k, p in enumerate(plist):
            key = self._key(method, p) if self.cache else None
            v = self.cache.get(key) if key else None
            if v is not None:
                res[k] = v
            else:
                todo.append(k)
        for s in range(0, len(todo), size):
            part = todo[s:s + size]
            got = {}
            name, pool = self._pool(method, plist[part[0]])
            for attempt in range(6):
                url = pool[self.rot[name] % len(pool)]
                try:
                    j = self._post(url, [{"jsonrpc": "2.0", "id": n, "method": method, "params": plist[k]}
                                         for n, k in enumerate(part)])
                    if isinstance(j, dict):
                        raise RuntimeError(str(j)[:200])
                    for x in j:
                        if isinstance(x, dict) and x.get("result") is not None and "error" not in x:
                            got[int(x["id"])] = x["result"]
                    if len(got) < len(part):
                        self.stats["batch_partial"] += 1
                        self.rot[name] += 1
                    break
                except RangeError:
                    break
                except Exception:  # noqa: BLE001
                    self.rot[name] += 1
                    self._sleep(attempt)
            for n, k in enumerate(part):
                v = got.get(n)
                if v is None:
                    v = self.call(method, plist[k])
                elif self.cache:
                    key = self._key(method, plist[k])
                    if key:
                        self.cache.put(key, v, commit=False)
                res[k] = v
            if self.cache:
                with self.cache.lock:
                    self.cache.db.commit()
        return res

    # -- blocks and time
    def head(self):
        return int(self.call("eth_blockNumber", []), 16)

    def final_block(self):
        """Blocks at least an hour old; only their logs are cached."""
        if self._final is None:
            self._final = self.head() - int(3600 / BLOCK_TIME[self.chain])
        return self._final

    def block_ts_many(self, blocks):
        blocks = sorted(set(int(b) for b in blocks))
        out = self.cache.get_ts(blocks) if self.cache else {}
        todo = [b for b in blocks if b not in out]
        if todo:
            hdrs = self.batch("eth_getBlockByNumber", [[hex(b), False] for b in todo], size=max(self.batch_size, 40))
            new = {b: int(h["timestamp"], 16) for b, h in zip(todo, hdrs)}
            out.update(new)
            if self.cache:
                fin = self.final_block()
                self.cache.put_ts({b: t for b, t in new.items() if b <= fin})
        return out

    def block_ts(self, number):
        return self.block_ts_many([number])[int(number)]

    def block_at(self, ts, lo=None, hi=None, k=12, guess=None):
        """Smallest block with timestamp >= ts: one batch of (cached) headers per step, a window of +-k blocks
        around the guess (given, else interpolated) plus the bracket's quartiles; regular block times finish in
        one or two steps."""
        hi = hi or self.head()
        thi = self.block_ts(hi)
        if thi < ts:
            raise ValueError("timestamp after head")
        if lo is None:
            lo = max(1, hi - int((thi - ts) / BLOCK_TIME[self.chain] * 1.3) - 1000)
        tlo = self.block_ts(lo)
        while tlo >= ts and lo > 1:
            lo = max(1, lo - ((hi - lo) * 2 + 1000))
            tlo = self.block_ts(lo)
        if tlo >= ts:
            return lo
        while hi - lo > 1:      # invariant: ts(lo) < ts <= ts(hi)
            n = hi - lo
            if n <= 2 * k + 2:
                pts = list(range(lo + 1, hi))
            else:
                g = guess if guess is not None else lo + int((ts - tlo) * n / max(1, thi - tlo))
                guess = None
                cand = {g + j for j in range(-k, k + 1)} | {lo + n * j // 4 for j in (1, 2, 3)}
                pts = sorted(p for p in cand if lo < p < hi)
            tsm = self.block_ts_many(pts)
            for p in pts:
                if tsm[p] < ts:
                    lo, tlo = p, tsm[p]
                else:
                    hi, thi = p, tsm[p]
                    break
        return hi

    # -- logs
    def logs(self, address, topics, b0, b1, step=None, endpoints=None):
        """All logs of `address` matching `topics` in [b0, b1]: cache chunks aligned to the first endpoint's range,
        each fetched with ranges the endpoint in use accepts."""
        eps = endpoints or self.eps
        S = step or eps[0][1]
        out, b = [], int(b0)
        while b <= b1:
            cs = (b // S) * S
            s, e = b, min(int(b1), cs + S - 1)
            out += self._logs_chunk(address, topics, s, e, eps, S)
            b = e + 1
        return out

    def _logs_chunk(self, address, topics, s, e, eps, S):
        tag = "|".join(u for u, _ in eps) if eps is not self.eps else ""
        key = "logs|" + json.dumps([address.lower() if isinstance(address, str) else sorted(a.lower() for a in address),
                                     topics, s, e, tag]).lower()
        cacheable = self.cache is not None and e <= self.final_block()
        if cacheable:
            v = self.cache.get(key)
            if v is not None:
                return v
        res = self._logs_fetch(address, topics, s, e, eps, 0)
        seen, uniq = set(), []
        for x in sorted(res, key=lambda x: (hx(x["blockNumber"]), hx(x["logIndex"]))):
            k = (x["blockNumber"], x["logIndex"], x["transactionHash"])
            if k not in seen:
                seen.add(k)
                uniq.append(x)
        if cacheable:
            self.cache.put(key, uniq)
        return uniq

    def _logs_fetch(self, address, topics, s, e, eps, attempt, rechecked=False):
        url, mx = eps[(self.rot["logs"] if eps is self.eps else attempt) % len(eps)]
        n = e - s + 1
        if n > mx:
            out, b = [], s
            while b <= e:
                out += self._logs_fetch(address, topics, b, min(e, b + mx - 1), eps, attempt, rechecked)
                b += mx
            return out
        flt = {"address": address, "topics": topics, "fromBlock": hex(s), "toBlock": hex(e)}
        try:
            res = self.call("eth_getLogs", [flt], retries=3, urls=[url])
        except RangeError:
            self.stats["range_split"] += 1
            if n <= 50:
                raise
            q = max(1, n // 4)
            out, b = [], s
            while b <= e:
                out += self._logs_fetch(address, topics, b, min(e, b + q - 1), eps, attempt, rechecked)
                b += q
            return out
        except RuntimeError:
            if attempt >= 3 * len(eps):
                raise
            if eps is self.eps:
                self.rot["logs"] += 1
            self._sleep(attempt)
            return self._logs_fetch(address, topics, s, e, eps, attempt + 1, rechecked)
        if not res and n > EMPTY_GUARD and not rechecked:
            # an empty answer over a long range is re-asked in four parts (once)
            self.stats["empty_recheck"] += 1
            q = (n + 3) // 4
            out, b = [], s
            while b <= e:
                out += self._logs_fetch(address, topics, b, min(e, b + q - 1), eps, attempt, True)
                b += q
            return out
        return res

    def trace(self, txh):
        """callTracer trace of a transaction, or None when no endpoint for this chain answers it."""
        urls = TRACE.get(self.chain) or []
        if not urls:
            return None
        try:
            return self.call("debug_traceTransaction", [txh, {"tracer": "callTracer"}], retries=2 * len(urls), urls=urls)
        except RuntimeError:
            return None


def _many(rpc, method, plist):
    if not plist:
        return []
    if hasattr(rpc, "batch"):
        return rpc.batch(method, plist)
    return [rpc.call(method, p) for p in plist]


def _block_ts_many(rpc, blocks):
    if hasattr(rpc, "block_ts_many"):
        return rpc.block_ts_many(blocks)
    return {b: rpc.block_ts(b) for b in sorted(set(blocks))}


# ------------------------------------------------------------------------------------------------ token facts
def _call_word(rpc, to, data, block="latest"):
    try:
        r = rpc.eth_call(to, data, block)
    except Exception:  # noqa: BLE001  reverts and missing functions
        return None
    return r if r and r != "0x" else None


def token_info(rpc, chain, token, T, meta):
    """decimals, symbol, whether the chain's token bridge issued it (isWrappedAsset), and its origin
    (chain id, bytes32 address); cached in `meta` by (chain, token)."""
    k = f"{chain}:{token.lower()}"
    if k in meta:
        return meta[k]
    tb = T["chains"][chain]["token_bridge"]
    r = _call_word(rpc, token, SEL["decimals"])
    dec = int(r, 16) if r else 18
    sym = "?"
    r = _call_word(rpc, token, SEL["symbol"])
    if r:
        raw = bytes.fromhex(r[2:])
        if len(raw) >= 96:
            n = int.from_bytes(raw[32:64], "big")
            sym = raw[64:64 + n].decode(errors="ignore")
        else:
            sym = raw.rstrip(b"\x00").decode(errors="ignore")
    r = _call_word(rpc, tb, SEL["isWrappedAsset"] + "0" * 24 + token.lower()[2:])
    wrapped = bool(r and int(r, 16))
    if wrapped:
        oc = int(_call_word(rpc, token, SEL["chainId"]) or "0x0", 16)
        oa = "0x" + (_call_word(rpc, token, SEL["nativeContract"]) or "0x" + "0" * 64)[2:].rjust(64, "0")[-64:]
    else:
        oc, oa = T["chains"][chain]["wormhole_chain_id"], "0x" + "0" * 24 + token.lower()[2:]
    meta[k] = {"decimals": dec, "symbol": sym.strip() or "?", "wrapped": wrapped, "origin_chain": oc,
               "origin_address": oa.lower()}
    return meta[k]


def wrapped_asset(rpc, chain, token_chain, token_address32, T, meta):
    """Address of the token bridge's wrapped version of (token_chain, token_address) on `chain` (ZERO if none)."""
    k = f"{chain}:wrapped:{token_chain}:{token_address32.lower()}"
    if k not in meta:
        tb = T["chains"][chain]["token_bridge"]
        r = _call_word(rpc, tb, SEL["wrappedAsset"] + format(int(token_chain), "064x") + token_address32.lower()[2:].rjust(64, "0"))
        meta[k] = addr_from_word(r) if r else ZERO
    return meta[k]


# ------------------------------------------------------------------------------------------------ releases
def releases_in_receipt(rpc, dst_chain, rc, tx, T, meta):
    """Every TransferRedeemed of the destination's token bridge in one receipt, with the token movement that
    follows it (logs up to the next TransferRedeemed): transfers out of the token bridge (unlock), withdrawals of
    the wrapped gas coin by the token bridge (unlock_native) and mints of a token the bridge issued (mint)."""
    c = T["chains"][dst_chain]
    tb, weth = c["token_bridge"], c["weth"]
    logs = sorted(rc["logs"], key=lambda x: hx(x["logIndex"]))
    marks = [i for i, x in enumerate(logs) if x["address"].lower() == tb and x["topics"] and x["topics"][0] == REDEEMED]
    out = []
    for k, i in enumerate(marks):
        end = marks[k + 1] if k + 1 < len(marks) else len(logs)
        r = logs[i]
        moves, wd, burn_weth, notes = [], [], [], []
        for x in logs[i + 1:end]:
            a, t = x["address"].lower(), x["topics"]
            if not t:
                continue
            if t[0] == TRANSFER and len(t) == 3:
                frm, to = addr_from_word(t[1]), addr_from_word(t[2])
                amt = int(x["data"], 16) if x["data"] not in ("0x", "") else 0
                if frm == tb and to == ZERO:
                    if a == weth:
                        burn_weth.append({"kind": "unlock_native", "token": a, "to": None, "amount": amt, "li": hx(x["logIndex"])})
                    continue        # a burn by the token bridge belongs to an outgoing transfer
                if frm == tb:
                    moves.append({"kind": "unlock", "token": a, "to": to, "amount": amt, "li": hx(x["logIndex"])})
                elif frm == ZERO and token_info(rpc, dst_chain, a, T, meta)["wrapped"]:
                    moves.append({"kind": "mint", "token": a, "to": to, "amount": amt, "li": hx(x["logIndex"])})
            elif a == weth and t[0] == WITHDRAWAL and addr_from_word(t[1]) == tb:
                wd.append({"kind": "unlock_native", "token": a, "to": None, "amount": int(x["data"], 16), "li": hx(x["logIndex"])})
        moves += wd if wd else burn_weth
        moves.sort(key=lambda m: m["li"])
        rel = {"dst_chain": dst_chain, "emitter_chain": hx(r["topics"][1]), "emitter": r["topics"][2].lower(),
               "sequence": hx(r["topics"][3]), "block": hx(r["blockNumber"]), "tx": r["transactionHash"].lower(),
               "log_index": hx(r["logIndex"]), "tx_from": (tx or {}).get("from", "").lower(),
               "tx_to": ((tx or {}).get("to") or "").lower(), "selector": ((tx or {}).get("input") or "")[:10],
               "src_chain": WH_NAME.get(hx(r["topics"][1]))}
        if not moves:
            rel.update({"kind": "none", "token": None, "symbol": "", "decimals": 0, "amount_raw": 0, "fee_raw": 0,
                        "recipient": None, "fee_to": None, "moves": 0, "origin_chain": None, "origin_address": None})
            notes.append("no token movement after the redeem event")
        else:
            tok = moves[0]["token"]
            same = [m for m in moves if m["token"] == tok and m["kind"] == moves[0]["kind"]]
            if len(same) != len(moves) or len(same) > 2:
                notes.append(f"{len(moves)} token movements after the redeem event; the first {min(2, len(same))} of one token used")
            same = same[:2]
            main = same[-1]
            info = token_info(rpc, dst_chain, tok, T, meta)
            if main["kind"] == "unlock_native":
                sym, oc, oa = GAS_SYMBOL[dst_chain], T["chains"][dst_chain]["wormhole_chain_id"], "0x" + "0" * 24 + tok[2:]
            else:
                sym, oc, oa = info["symbol"], info["origin_chain"], info["origin_address"]
            rel.update({"kind": main["kind"], "token": tok, "symbol": sym, "decimals": info["decimals"],
                        "amount_raw": sum(m["amount"] for m in same), "fee_raw": same[0]["amount"] if len(same) == 2 else 0,
                        "recipient": main["to"], "fee_to": same[0]["to"] if len(same) == 2 else None, "moves": len(same),
                        "origin_chain": oc, "origin_address": oa, "native_amounts": [m["amount"] for m in same]
                        if main["kind"] == "unlock_native" else None})
        vaa = find_vaa((tx or {}).get("input"), rel["emitter_chain"], rel["emitter"], rel["sequence"])
        if vaa is not None:
            vaa = dict(vaa)
            if "payload" in vaa:
                vaa["payload_hex"] = "0x" + vaa.pop("payload").hex()
        rel["vaa"] = vaa
        rel["notes"] = notes
        out.append(rel)
    return out


def native_payouts(rpc, chain, txh, tb, pattern=None):
    """Value transfers made by the token bridge in a transaction, from a callTracer trace (None without one).
    With `pattern` (hex of emitter chain, emitter and sequence), only inside the call into the token bridge whose
    input carries that signed message."""
    tr = rpc.trace(txh) if hasattr(rpc, "trace") else None
    if tr is None:
        return None
    out = []

    def collect(c):
        v = int(c.get("value") or "0x0", 16)
        if (c.get("from") or "").lower() == tb and v > 0 and c.get("type") in ("CALL", "CALLCODE"):
            out.append(((c.get("to") or "").lower(), v))
        for s in c.get("calls") or []:
            collect(s)

    def find(c):
        if (c.get("to") or "").lower() == tb and pattern in (c.get("input") or "").lower():
            collect(c)
            return True
        return any(find(s) for s in c.get("calls") or [])
    if pattern is None:
        collect(tr)
    elif not find(tr):
        return []
    return out


def new_releases(rpc_dst, dst_chain, from_block, to_block, src_chain=None, T=None, meta=None, trace=True):
    """Completed transfers on `dst_chain` in [from_block, to_block] whose emitter is the token bridge of the pair's
    other chain, with the token movement of each: list of release dicts sorted by (block, log index)."""
    T = T or load_targets()
    meta = {} if meta is None else meta
    src_chain = src_chain or other_chain(dst_chain, T)
    cd, cs = T["chains"][dst_chain], T["chains"][src_chain]
    topics = [REDEEMED, topic_u(cs["wormhole_chain_id"]), cs["emitter32"]]
    logs = rpc_dst.logs(cd["token_bridge"], topics, int(from_block), int(to_block))
    txs = sorted({lg["transactionHash"].lower() for lg in logs})
    rcs = _many(rpc_dst, "eth_getTransactionReceipt", [[h] for h in txs])
    tos = _many(rpc_dst, "eth_getTransactionByHash", [[h] for h in txs])
    want = {(lg["transactionHash"].lower(), hx(lg["logIndex"])) for lg in logs}
    out = []
    for h, rc, tx in zip(txs, rcs, tos):
        for r in releases_in_receipt(rpc_dst, dst_chain, rc, tx, T, meta):
            if (r["tx"], r["log_index"]) in want:
                r["src_chain"] = src_chain
                out.append(r)
    if len(out) != len(want):
        raise RuntimeError(f"{dst_chain}: {len(want)} redeem logs but {len(out)} releases parsed")
    tsm = _block_ts_many(rpc_dst, [r["block"] for r in out])
    for r in out:
        r["ts"] = tsm[r["block"]]
    if trace:
        fill_native_recipients(rpc_dst, dst_chain, out, T)
    out.sort(key=lambda r: (r["block"], r["log_index"]))
    return out


def fill_native_recipients(rpc_dst, dst_chain, rels, T):
    """For `unlock_native` releases, the receiver of the gas coin (the token bridge pays it by an internal call,
    which leaves no log): read from a call trace. Sets `recipient` (and `fee_to`), or adds a note."""
    tb = T["chains"][dst_chain]["token_bridge"]
    for r in rels:
        if r["kind"] != "unlock_native" or r.get("recipient"):
            continue
        r["notes"] = [n for n in r.get("notes") or [] if not n.startswith("gas-coin payout")]
        pattern = format(r["emitter_chain"], "04x") + r["emitter"][2:] + format(r["sequence"], "016x")
        pays = native_payouts(rpc_dst, dst_chain, r["tx"], tb, pattern)
        if pays is None:
            r["notes"].append("gas-coin payout not traced (no trace answer)")
            continue
        amts = list(r.get("native_amounts") or [])
        hit = []
        for to, v in pays:          # the payouts in order: relayer fee (if any), then the recipient
            if v in amts:
                hit.append(to)
                amts.remove(v)
        if len(hit) == len(r.get("native_amounts") or []) and hit:
            r["recipient"] = hit[-1]
            if len(hit) == 2:
                r["fee_to"] = hit[0]
        else:
            r["notes"].append("gas-coin payout not found in the trace")
    return rels


# ------------------------------------------------------------------------------------------------ source side
def message_index(rpc_src, src_chain, b0, b1, T=None):
    """Transfer messages published by the source chain's token bridge in [b0, b1]: {sequence: raw log}."""
    T = T or load_targets()
    c = T["chains"][src_chain]
    logs = rpc_src.logs(c["core"], [LMP, addr_topic(c["token_bridge"])], int(b0), int(b1))
    idx = {}
    for lg in logs:
        if lg["address"].lower() != c["core"]:
            continue
        idx[decode_lmp(lg)["sequence"]] = lg
    return idx


def _seq_at(rpc, core, tb, block):
    r = _call_word(rpc, core, SEL["nextSequence"] + "0" * 24 + tb[2:], hex(block))
    return int(r, 16) if r else None


def locate_message(rpc_src, src_chain, sequence, hint_ts=None, T=None):
    """The LogMessagePublished of the source token bridge with this sequence. With a hint (the signed message's
    timestamp, which is the source block's time) a short log query around that time; otherwise a binary search
    on the core contract's nextSequence(emitter) over archive state."""
    T = T or load_targets()
    c = T["chains"][src_chain]
    topics = [LMP, addr_topic(c["token_bridge"])]
    if hint_ts:
        for pad in (60, 3600, 86400):
            try:
                b0 = rpc_src.block_at(int(hint_ts) - pad)
                b1 = rpc_src.block_at(int(hint_ts) + pad + 1)
            except ValueError:
                b1 = rpc_src.head()
            for lg in rpc_src.logs(c["core"], topics, b0, b1):
                if lg["address"].lower() == c["core"] and decode_lmp(lg)["sequence"] == sequence:
                    return lg
    hi = rpc_src.head()
    s_hi = _seq_at(rpc_src, c["core"], c["token_bridge"], hi)
    if s_hi is None or s_hi <= sequence:
        return None
    lo = 1
    while hi - lo > 1:      # invariant: nextSequence(lo) <= sequence < nextSequence(hi)
        mid = (lo + hi) // 2
        s = _seq_at(rpc_src, c["core"], c["token_bridge"], mid)
        if s is None:
            lo = mid
            continue
        if s > sequence:
            hi = mid
        else:
            lo = mid
    for lg in rpc_src.logs(c["core"], topics, hi, hi):
        if lg["address"].lower() == c["core"] and decode_lmp(lg)["sequence"] == sequence:
            return lg
    return None


def value_check(rpc_src, src_chain, rc, msg, p, T, meta):
    """Did the amount move into the source token bridge's custody (a token native to the source chain: Transfer
    to the bridge, or the wrapped gas coin's Deposit/mint to the bridge) or was the wrapped token burned (Transfer
    from the bridge to zero), in the logs of the same transaction between the previous message of the bridge and
    this one?  Returns (value_moved, value_detail, moved_raw, token, decimals, note)."""
    c = T["chains"][src_chain]
    tb, core = c["token_bridge"], c["core"]
    logs = sorted(rc["logs"], key=lambda x: hx(x["logIndex"]))
    pos = next((i for i, x in enumerate(logs) if hx(x["logIndex"]) == msg["log_index"]), None)
    if pos is None:
        return "no", "none", None, None, None, "message log not in its receipt"
    prev = max([i for i, x in enumerate(logs[:pos]) if x["address"].lower() == core and x["topics"]
                and x["topics"][0] == LMP and len(x["topics"]) > 1 and addr_from_word(x["topics"][1]) == tb], default=-1)
    seg = logs[prev + 1:pos]
    if p["token_chain"] == c["wormhole_chain_id"]:
        if not word_is_address(p["token_address"]):
            return "no", "none", None, None, None, "token address of the message is not an address"
        token, detail = addr_from_word(p["token_address"]), "lock"
    else:
        token, detail = wrapped_asset(rpc_src, src_chain, p["token_chain"], p["token_address"], T, meta), "burn"
        if token == ZERO:
            return "no", "none", None, None, None, "no wrapped token for the message's token on the source chain"
    dec = token_info(rpc_src, src_chain, token, T, meta)["decimals"]
    moved = []
    for x in seg:
        if x["address"].lower() != token or not x["topics"]:
            continue
        t0 = x["topics"][0]
        if t0 == TRANSFER and len(x["topics"]) == 3:
            frm, to = addr_from_word(x["topics"][1]), addr_from_word(x["topics"][2])
            amt = int(x["data"], 16) if x["data"] not in ("0x", "") else 0
            if detail == "lock" and to == tb:
                moved.append(amt)
            if detail == "burn" and frm == tb and to == ZERO:
                moved.append(amt)
        elif t0 == DEPOSIT and detail == "lock" and token == c["weth"] and addr_from_word(x["topics"][1]) == tb:
            moved.append(int(x["data"], 16))
    if not moved:
        return "no", "none", None, token, dec, f"no {detail} of the message's token in the source transaction"
    ok = [a for a in moved if normalize(a, dec) == p["amount"]]
    if ok:
        return "yes", detail, ok[0], token, dec, ""
    return "no", detail, moved[0], token, dec, f"{detail} of {units(moved[0], dec)} against {units(denormalize(p['amount'], dec), dec)} in the message"


def agreement(release, p, dst_chain, T):
    """Do the source message's amount, token and recipient equal the release's?"""
    dst_id = T["chains"][dst_chain]["wormhole_chain_id"]
    out = {"to_chain": p["to_chain"] == dst_id}
    dec = release.get("decimals") or 0
    out["amount"] = release["kind"] != "none" and release["amount_raw"] == denormalize(p["amount"], dec)
    out["token"] = (release.get("origin_chain") == p["token_chain"] and
                    (release.get("origin_address") or "").lower() == p["token_address"].lower())
    rcp = release.get("recipient")
    out["recipient"] = bool(rcp) and word_is_address(p["to"]) and addr_from_word(p["to"]) == rcp
    if p["payload_id"] == 1 and release.get("moves") == 2:
        out["fee"] = release["fee_raw"] == denormalize(p["fee"], dec)
    return out


def find_source(rpc_src, src_chain, release, T=None, meta=None, index=None):
    """The source message of a release and the value check in its transaction, or None if the source chain has
    no message from its token bridge with that sequence."""
    T = T or load_targets()
    meta = {} if meta is None else meta
    c = T["chains"][src_chain]
    if release["emitter_chain"] != c["wormhole_chain_id"] or release["emitter"] != c["emitter32"]:
        return None
    lg = (index or {}).get(release["sequence"])
    if lg is None:
        lg = locate_message(rpc_src, src_chain, release["sequence"], hint_ts=(release.get("vaa") or {}).get("timestamp"), T=T)
    if lg is None:
        return None
    msg = decode_lmp(lg)
    if msg["sender"] != c["token_bridge"] or msg["sequence"] != release["sequence"]:
        return None
    p = decode_transfer(msg["payload"])
    ts = _block_ts_many(rpc_src, [msg["block"]])[msg["block"]]
    out = {"src_chain": src_chain, "sequence": msg["sequence"], "block": msg["block"], "ts": ts, "tx": msg["tx"],
           "log_index": msg["log_index"], "nonce": msg["nonce"], "consistency": msg["consistency"],
           "payload_hex": "0x" + msg["payload"].hex(), "payload": p}
    vp = (release.get("vaa") or {}).get("payload_hex")
    out["vaa_payload_equal"] = None if vp is None else (vp.lower() == out["payload_hex"].lower())
    vt = (release.get("vaa") or {}).get("timestamp")
    out["vaa_ts_equal"] = None if vt is None else (int(vt) == ts)
    if p is None:
        out.update({"value_moved": "no", "value_detail": "none", "amount_agrees": "no",
                    "note": "source message is not a token transfer"})
        return out
    rc = rpc_src.receipt(msg["tx"])
    vm, vd, moved, token, dec, note = value_check(rpc_src, src_chain, rc, msg, p, T, meta)
    ag = agreement(release, p, release["dst_chain"], T)
    out.update({"value_moved": vm, "value_detail": vd, "moved_raw": moved, "src_token": token, "src_decimals": dec,
                "agree": ag, "amount_agrees": "yes" if (ag["amount"] and ag["token"] and ag["recipient"]) else "no",
                "note": note})
    return out
