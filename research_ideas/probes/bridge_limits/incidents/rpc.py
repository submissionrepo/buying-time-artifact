"""Minimal JSON-RPC client for public EVM endpoints (bridge drain timing, 2026-10-16).

Endpoint behaviour tested 2026-10-16:
- Ethereum: rpc.mevblocker.io and eth.drpc.org serve archive state and historical eth_getLogs
  (ranges up to about 10,000 blocks); eth.drpc.org also answers trace_filter on short ranges.
  ethereum-rpc.publicnode.com refuses archive requests without a token.
- Other chains are listed in ENDPOINTS and tried in order; failures rotate to the next endpoint.
No addresses or hashes live in this file; callers pass them in from data/incidents/.
"""
import json
import os
import time
import urllib.request

ENDPOINTS = {
    "ethereum": ["https://rpc.mevblocker.io", "https://eth.drpc.org", "https://mainnet.gateway.tenderly.co"],
    "ethereum_trace": ["https://eth.drpc.org"],
    # BSC: set BSC_RPC_URL to an archive endpoint that serves historical logs and traces; the public
    # BNB Chain endpoints refuse eth_getLogs and 1rpc caps logs at 50 blocks.
    "bsc": [__import__("os").environ.get("BSC_RPC_URL", "https://bsc-dataseed.bnbchain.org"), "https://1rpc.io/bnb"],
    "bsc_trace": [__import__("os").environ.get("BSC_RPC_URL", "https://bsc-dataseed.bnbchain.org")],
    # Polygon: only 1rpc answered historical eth_getLogs (50-block cap) on 2026-10-16.
    "polygon": ["https://1rpc.io/matic"],
    "arbitrum": ["https://arbitrum.drpc.org", "https://arb1.arbitrum.io/rpc"],
    "base": ["https://base.drpc.org", "https://mainnet.base.org"],
    "fantom": ["https://fantom.drpc.org", "https://rpc.ftm.tools"],
    "avalanche": ["https://avalanche.drpc.org", "https://api.avax.network/ext/bc/C/rpc"],
    "optimism": ["https://optimism.drpc.org", "https://mainnet.optimism.io"],
}

RANGE_ERROR_KEYS = ("range", "limit", "too many", "exceed", "10000", "10,000", "response size",
                    "too large", "query returned more than")


class RangeError(RuntimeError):
    pass


class Rpc:
    def __init__(self, chain, timeout=60):
        self.chain = chain
        self.urls = ENDPOINTS[chain]
        self.i = 0
        self.timeout = timeout
        self.calls = 0

    def call(self, method, params, retries=6):
        last = None
        for attempt in range(retries):
            url = self.urls[self.i % len(self.urls)]
            body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
            req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json",
                                                                  "User-Agent": "bridge-limits-probe/1.0"})
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    j = json.loads(resp.read().decode())
                self.calls += 1
                if "error" in j:
                    msg = str(j["error"])
                    last = RuntimeError(f"{url}: {msg[:200]}")
                    if any(k in msg.lower() for k in RANGE_ERROR_KEYS):
                        raise RangeError(str(last))
                    self.i += 1
                    time.sleep(0.6 * (attempt + 1))
                    continue
                return j["result"]
            except RangeError:
                raise
            except Exception as e:  # network errors, HTTP errors, bad JSON
                last = e
                self.i += 1
                time.sleep(0.6 * (attempt + 1))
        raise RuntimeError(f"{self.chain} rpc {method} failed: {last}")

    # --- helpers -------------------------------------------------------------------------------
    def block(self, number, full=False):
        return self.call("eth_getBlockByNumber", [hex(number) if isinstance(number, int) else number, full])

    def block_ts(self, number):
        return int(self.block(number)["timestamp"], 16)

    def head(self):
        return int(self.call("eth_blockNumber", []), 16)

    def block_at(self, ts, lo=1, hi=None):
        """Smallest block number with timestamp >= ts (binary search on headers)."""
        hi = hi or self.head()
        while lo < hi:
            mid = (lo + hi) // 2
            if self.block_ts(mid) < ts:
                lo = mid + 1
            else:
                hi = mid
        return lo

    def logs(self, address, topics, b0, b1, step=5000):
        out = []
        b = b0
        cur = step
        while b <= b1:
            e = min(b + cur - 1, b1)
            try:
                res = self.call("eth_getLogs", [{"address": address, "topics": topics,
                                                 "fromBlock": hex(b), "toBlock": hex(e)}])
            except RangeError:
                if cur <= 50:
                    raise
                cur = max(50, cur // 4)
                continue
            out += res
            b = e + 1
        return out

    def receipt(self, txh):
        return self.call("eth_getTransactionReceipt", [txh])

    def tx(self, txh):
        return self.call("eth_getTransactionByHash", [txh])

    def balance(self, addr, block):
        return int(self.call("eth_getBalance", [addr, hex(block)]), 16)

    def eth_call(self, to, data, block="latest"):
        return self.call("eth_call", [{"to": to, "data": data}, hex(block) if isinstance(block, int) else block])

    def trace_filter(self, from_addrs, b0, b1, step=2000, to_addrs=None):
        out = []
        b = b0
        cur = step
        while b <= b1:
            e = min(b + cur - 1, b1)
            flt = {"fromBlock": hex(b), "toBlock": hex(e)}
            if from_addrs:
                flt["fromAddress"] = from_addrs
            if to_addrs:
                flt["toAddress"] = to_addrs
            try:
                res = self.call("trace_filter", [flt])
            except RangeError:
                if cur <= 20:
                    raise
                cur = max(20, cur // 4)
                continue
            out += res or []
            b = e + 1
        return out


TRANSFER = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
WETH_WITHDRAWAL = "0x7fcf532c15f0a6db0bd6d0e038bea71d30d808c7d98cb3bf7268a95bf5081b65"
PAUSED = "0x62e78cea01bee320cd4e420270b5ea74000d11b0c9f74754ebdbfc544b05a258"  # Paused(address)


def topic_addr(a):
    return "0x" + "0" * 24 + a.lower()[2:]


def addr_from_topic(t):
    return "0x" + t[-40:]


def erc20_meta(rpc, token, cache):
    """Return (symbol, decimals) via eth_call; cache by token address."""
    if token in cache:
        return cache[token]
    sym, dec = "?", 18
    try:
        r = rpc.eth_call(token, "0x313ce567")
        dec = int(r, 16) if r and r != "0x" else 18
    except Exception:
        pass
    try:
        r = rpc.eth_call(token, "0x95d89b41")
        if r and len(r) > 2:
            raw = bytes.fromhex(r[2:])
            if len(raw) >= 96:
                n = int.from_bytes(raw[32:64], "big")
                sym = raw[64:64 + n].decode(errors="ignore")
            else:
                sym = raw.rstrip(b"\x00").decode(errors="ignore")
    except Exception:
        pass
    cache[token] = (sym, dec)
    return cache[token]
