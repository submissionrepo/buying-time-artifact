"""JSON-RPC client for a local anvil node over a websocket (HTTP on Windows localhost costs about
10 ms per call; the websocket about 1 ms). Development accounts are unlocked, so transactions are
signed by the node through eth_sendTransaction."""
from __future__ import annotations

import json
import time

from websockets.sync.client import connect

GWEI = 10 ** 9


class RpcError(Exception):
    def __init__(self, method, err):
        super().__init__(f"{method}: {err}")
        self.method = method
        self.err = err


class Chain:
    def __init__(self, url: str, name: str = ""):
        self.url = url.replace("http://", "ws://")
        self.name = name
        self.ws = None
        self._id = 0
        self.ncalls = 0
        self._connect()

    def _connect(self, tries=200):
        for i in range(tries):
            try:
                self.ws = connect(self.url, max_size=None, open_timeout=10, close_timeout=1)
                return
            except Exception:
                if i == tries - 1:
                    raise
                time.sleep(0.05)

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass

    def rpc(self, method, params=None):
        self._id += 1
        self.ncalls += 1
        self.ws.send(json.dumps({"jsonrpc": "2.0", "id": self._id, "method": method, "params": params or []}))
        j = json.loads(self.ws.recv(timeout=300))
        if "error" in j:
            raise RpcError(method, j["error"])
        return j["result"]

    def batch(self, calls):
        """calls: list of (method, params). Returns results in order (RpcError objects for errors)."""
        if not calls:
            return []
        body = []
        ids = []
        for m, p in calls:
            self._id += 1
            ids.append(self._id)
            body.append({"jsonrpc": "2.0", "id": self._id, "method": m, "params": p})
        self.ncalls += 1
        self.ws.send(json.dumps(body))
        res = {x["id"]: x for x in json.loads(self.ws.recv(timeout=300))}
        out = []
        for (m, _), i in zip(calls, ids):
            x = res[i]
            out.append(RpcError(m, x["error"]) if "error" in x else x["result"])
        return out

    # ---------------------------------------------------------------- reads
    def head(self) -> int:
        return int(self.rpc("eth_blockNumber"), 16)

    def block(self, n="latest", full=False):
        tag = n if isinstance(n, str) else hex(n)
        return self.rpc("eth_getBlockByNumber", [tag, full])

    def call(self, to, data, block="latest"):
        tag = block if isinstance(block, str) else hex(block)
        return self.rpc("eth_call", [{"to": to, "data": data}, tag])

    def logs(self, address, topics, frm, to):
        if isinstance(frm, int) and isinstance(to, int) and to < frm:
            return []
        f = {"address": address, "topics": topics,
             "fromBlock": frm if isinstance(frm, str) else hex(frm),
             "toBlock": to if isinstance(to, str) else hex(to)}
        return self.rpc("eth_getLogs", [f])

    def receipt(self, h):
        return self.rpc("eth_getTransactionReceipt", [h])

    # ---------------------------------------------------------------- writes
    @staticmethod
    def txobj(frm, to, data, gas=500_000, tip_gwei=1, value=0, nonce=None):
        tx = {"from": frm, "data": data, "gas": hex(gas), "maxFeePerGas": hex(5000 * GWEI),
              "maxPriorityFeePerGas": hex(int(tip_gwei * GWEI)), "value": hex(value)}
        if to is not None:
            tx["to"] = to
        if nonce is not None:
            tx["nonce"] = hex(nonce)
        return tx

    def send(self, frm, to, data, gas=500_000, tip_gwei=1, value=0, nonce=None):
        return self.rpc("eth_sendTransaction", [self.txobj(frm, to, data, gas, tip_gwei, value, nonce)])

    def send_many(self, txs):
        """txs: list of tx objects (txobj). Nonces are assigned here from each sender's pending count,
        in list order (the node may process a batch concurrently). One batch request; returns hashes
        (or RpcError)."""
        if not txs:
            return []
        senders = sorted({t["from"] for t in txs})
        res = self.batch([("eth_getTransactionCount", [a, "pending"]) for a in senders])
        nxt = {a: int(r, 16) for a, r in zip(senders, res)}
        for t in txs:
            if "nonce" not in t:
                t["nonce"] = hex(nxt[t["from"]])
                nxt[t["from"]] += 1
        return self.batch([("eth_sendTransaction", [t]) for t in txs])

    def wait_receipt(self, h, timeout=300.0, poll=0.02):
        t0 = time.time()
        while True:
            r = self.receipt(h)
            if r is not None:
                return r
            if time.time() - t0 > timeout:
                raise TimeoutError(h)
            time.sleep(poll)

    # ---------------------------------------------------------------- node control
    def automine(self, on: bool):
        self.rpc("evm_setAutomine", [on])

    def interval_mining(self, seconds: int):
        self.rpc("evm_setIntervalMining", [seconds])

    def mine_at(self, ts: int):
        """Mine one block with the given timestamp; it takes the pending pool."""
        self.rpc("evm_setNextBlockTimestamp", [hex(int(ts))])
        self.rpc("evm_mine", [])

    def mine_n(self, n: int, first_ts: int, interval: int):
        """Mine n blocks at first_ts, first_ts + interval, ..."""
        if n <= 0:
            return
        self.rpc("evm_setNextBlockTimestamp", [hex(int(first_ts))])
        self.rpc("anvil_mine", [hex(n), hex(interval)])

    def snapshot(self):
        return self.rpc("evm_snapshot")

    def revert(self, sid):
        return self.rpc("evm_revert", [sid])

    def nonce(self, a, tag="pending"):
        return int(self.rpc("eth_getTransactionCount", [a, tag]), 16)

    def accounts(self):
        return self.rpc("eth_accounts")
