"""Relayer, keeper, monitor and the unauthorized party. Each reads and writes the two chains only
through its own RPC connections; none reads another's memory. The same classes run inside the
compressed replay (tb/des.py, simulated time) and as separate real-time processes (proc_*.py)."""
from __future__ import annotations

import math
import time

from .abi import addr_topic, calldata, decode, topic
from .contracts import T_DEPOSITED, T_RELAYED, REQ_TYPES, parse_deposited, parse_relayed

T_TRANSFER = topic("Transfer(address,address,uint256)")
from .rpc import Chain, RpcError
from .world import RELAYER, PAUSER, KEEPER, USER, ATT_RCPT, ATT

GAS_RELAY = 400_000
GAS_DRAIN = 6_000_000
GAS_PAUSE = 150_000
GAS_CANCEL = 150_000
GAS_DEPOSIT = 250_000


def _ok(res):
    return [r for r in res if not isinstance(r, RpcError)]


class Depositor:
    def __init__(self, world, S: Chain):
        self.w, self.S = world, S
        self.acc = world["acc"][USER]

    def deposit(self, dep_id, amount, recipient):
        return self.S.send(self.acc, self.w["s_dep"], calldata("deposit(bytes32,uint256,address)", dep_id, amount, recipient),
                           gas=GAS_DEPOSIT)


class Relayer:
    """Relays each deposit once it has k confirmations, to every receiver."""

    def __init__(self, world, S: Chain, D: Chain, k: int, check_processed=False):
        self.w, self.S, self.D, self.k = world, S, D, k
        self.acc = world["acc"][RELAYER]
        self.check_processed = check_processed  # a restarted relayer skips ids the receiver already took
        self.data = {"relayed": {}, "pending": {}, "n_relays": 0}

    def scan(self, now):
        d = self.data
        h = self.S.head()
        logs = self.S.logs(self.w["s_dep"], [T_DEPOSITED], max(1, h - self.k - 300), h)
        pend, out = {}, []
        for lg in logs:
            x = parse_deposited(lg)
            if x["dep_id"] in d["relayed"]:
                continue
            if h - x["bn"] + 1 >= self.k:
                out.append(x)
            else:
                pend[x["dep_id"]] = x["bn"]
        d["pending"] = pend
        if out and self.check_processed:
            rec = self.w["limiters"][0]["receiver"]
            res = self.D.batch([("eth_call", [{"to": rec, "data": calldata("processed(bytes32)", x["dep_id"])}, "latest"]) for x in out])
            done = [x for x, r in zip(out, res) if int(r, 16) == 1]
            for x in done:
                d["relayed"][x["dep_id"]] = (now, x["bn"], h, "already")
            out = [x for x, r in zip(out, res) if int(r, 16) == 0]
        txs = []
        for x in out:
            for L in self.w["limiters"]:
                txs.append(Chain.txobj(self.acc, L["receiver"],
                                       calldata("relay(bytes32,address,uint256)", x["dep_id"], x["to"], x["amount"]), gas=GAS_RELAY))
            d["relayed"][x["dep_id"]] = (now, x["bn"], h)
        if txs:
            res = self.D.send_many(txs)
            bad = [r for r in res if isinstance(r, RpcError)]
            assert not bad, bad[:2]
            d["n_relays"] += len(txs)
        return out, h, len(txs)

    def need_head(self):
        p = self.data["pending"]
        return min(bn + self.k - 1 for bn in p.values()) if p else None


class Keeper:
    """Anyone may call executeNext; the keeper does so for every limiter as soon as the oldest queued
    request is past its hold and every bucket holds its value."""

    def __init__(self, world, D: Chain, maxn=40):
        self.w, self.D, self.maxn = world, D, maxn
        self.acc = world["acc"][KEEPER]
        self.data = {"n_drains": 0}

    def plan(self):
        """{limiter: earliest time at which the head request can execute, or None}."""
        calls = [("eth_getBlockByNumber", ["latest", False])]
        for L in self.w["limiters"]:
            a = L["limiter"]
            calls += [("eth_call", [{"to": a, "data": calldata(s)}, "latest"]) for s in ("paused()", "head()", "nextId()", "lastRefill()")]
            if L["kind"] == "outflow":
                calls.append(("eth_call", [{"to": a, "data": calldata("tokens()")}, "latest"]))
            else:
                calls += [("eth_call", [{"to": a, "data": calldata("available(uint256)", k)}, "latest"]) for k in range(len(L["buckets"]))]
        res = self.D.batch(calls)
        T = int(res[0]["timestamp"], 16)
        i = 1
        st = []
        for L in self.w["limiters"]:
            paused, head, nxt, last = (int(x, 16) for x in res[i:i + 4])
            i += 4
            nb = 1 if L["kind"] == "outflow" else len(L["buckets"])
            vals = [int(x, 16) for x in res[i:i + nb]]
            i += nb
            st.append((L, paused, head, nxt, last, vals))
        # head requests (skipping cancelled ones)
        out = {}
        for L, paused, head, nxt, last, vals in st:
            if paused or head >= nxt:
                out[L["limiter"]] = None
                continue
            rid, req = head, None
            while rid < nxt:
                r = decode(REQ_TYPES, self.D.call(L["limiter"], calldata("requests(uint256)", rid)))
                if r[2] == 3:  # cancelled
                    rid += 1
                    continue
                req = r
                break
            if req is None or req[2] != 1:
                out[L["limiter"]] = None
                continue
            ready, value = req[1], req[5]
            tmin = ready
            if L["kind"] == "outflow":
                cap, refill = L["buckets"][0]
                tokens = vals[0]
                if value > tokens:
                    tmin = max(tmin, last + math.ceil((value - tokens) / refill))
            else:
                for (cap, refill), av in zip(L["buckets"], vals):
                    if value > av:
                        tmin = max(tmin, T + math.ceil((value - av) / refill))
            out[L["limiter"]] = tmin
        return out

    def execute(self, limiters):
        txs = [Chain.txobj(self.acc, self.w["executor"], calldata("drain(address,uint256)", a, self.maxn), gas=GAS_DRAIN)
               for a in limiters]
        res = self.D.send_many(txs)
        self.data["n_drains"] += len(txs)
        return res


class Monitor:
    """Follows the receivers' Relayed events (deposit id, request id, recipient, amount) at the
    destination head and matches each to a source deposit with the same id, amount and recipient
    with at least k_m confirmations, each deposit backing at most one request per receiver. A request
    with no such deposit g seconds after it was first seen raises an alarm; an acting monitor then
    pauses that limiter and cancels the unmatched requests that are still queued. With recheck_kf, a
    matched request stays under watch until its deposit has kf confirmations, and a deposit that
    disappears or falls below k_m reopens it."""

    def __init__(self, name, world, S: Chain, D: Chain, k_m, g, recheck_kf=None, acting=False, start_block=0,
                 limiters=None, value_check=False):
        self.name, self.w, self.S, self.D = name, world, S, D
        self.k_m, self.g, self.kf, self.acting = k_m, g, recheck_kf, acting
        # with value_check, a deposit counts only if its transaction moved the amount into the
        # source escrow (a token Transfer to the deposit contract in the same transaction); a recorded
        # deposit that moved nothing, as a forged deposit event, stays unmatched and raises the alarm
        self.value_check = value_check
        self.backed = {}
        lims = limiters or world["limiters"]
        self.rec2lim = {L["receiver"]: L["limiter"] for L in lims}
        self.receivers = list(self.rec2lim)
        self.acc = world["acc"][PAUSER]
        self.data = {"items": {}, "consumed": {}, "dest_scanned": start_block, "alarms": [], "actions": [],
                     "paused_sent": {}, "n_polls": 0, "n_final": 0, "n_matched": 0, "polls": []}
        self.sent_now = 0  # transactions sent in the last poll (for the replay's mining)

    # -------------------------------------------------------------- queries for scheduling
    def need_source_head(self):
        best = None
        for it in self.data["items"].values():
            if it["state"] == "pending" and it["dep_bn"] is not None:
                x = it["dep_bn"] + self.k_m - 1
            elif it["state"] == "prov":
                x = it["dep_bn"] + self.kf - 1
            else:
                continue
            best = x if best is None else min(best, x)
        return best

    def next_deadline(self):
        ds = [it["seen"] + self.g for it in self.data["items"].values() if it["state"] == "pending"]
        return min(ds) if ds else None

    def has_open(self):
        return any(it["state"] in ("pending", "prov") for it in self.data["items"].values())

    def has_pending_missing(self):
        return any(it["state"] == "pending" and it["dep_bn"] is None for it in self.data["items"].values())

    # -------------------------------------------------------------- the poll
    def poll(self, now, log_poll=False):
        d = self.data
        d["n_polls"] += 1
        self.sent_now = 0
        hd = self.D.head()
        new = []
        if hd > d["dest_scanned"]:
            for lg in self.D.logs(self.receivers, [T_RELAYED], d["dest_scanned"] + 1, hd):
                r = parse_relayed(lg)
                key = f"{r['receiver']}:{r['rid']}"
                d["items"][key] = {"key": key, "receiver": r["receiver"], "rid": r["rid"], "dep_id": r["dep_id"],
                                   "to": r["to"], "amount": r["amount"], "bn_d": r["bn"], "seen": now, "seen_hd": hd,
                                   "first_seen": now, "state": "pending", "why": None, "dep_bn": None}
                new.append(key)
            d["dest_scanned"] = hd
        open_keys = [k for k, it in d["items"].items() if it["state"] in ("pending", "prov")]
        hs = None
        alarm = []
        if open_keys:
            calls = [("eth_blockNumber", [])] + [
                ("eth_call", [{"to": self.w["s_dep"], "data": calldata("deposits(bytes32)", d["items"][k]["dep_id"])}, "latest"])
                for k in open_keys]
            res = self.S.batch(calls)
            hs = int(res[0], 16)
            for k, r in zip(open_keys, res[1:]):
                it = d["items"][k]
                amount, rcpt, bn = decode(["uint128", "address", "uint64"], r)
                exists = amount != 0
                same = exists and amount == it["amount"] and rcpt == it["to"]
                conf = hs - bn + 1 if exists else 0
                ck = it["receiver"] + ":" + it["dep_id"]
                other = d["consumed"].get(ck)
                dup = other is not None and other != k
                if it["state"] == "pending":
                    if same and conf >= self.k_m and not dup and self.value_check and not self._backed(it["dep_id"], it["amount"], bn):
                        it["dep_bn"] = None
                        it["why"] = "no value"
                        if now - it["seen"] >= self.g - 1e-9:
                            alarm.append(k)
                    elif same and conf >= self.k_m and not dup:
                        it["dep_bn"] = bn
                        it["matched"] = now
                        d["consumed"][ck] = k
                        d["n_matched"] += 1
                        it["state"] = "prov" if (self.kf and conf < self.kf) else "final"
                    else:
                        it["dep_bn"] = bn if (same and not dup) else None
                        it["why"] = ("consumed" if dup else "unconfirmed") if same else ("mismatch" if exists else "missing")
                        if now - it["seen"] >= self.g - 1e-9:
                            alarm.append(k)
                else:  # prov
                    if same and conf >= self.k_m:
                        it["dep_bn"] = bn
                        if conf >= self.kf:
                            it["state"] = "final"
                    else:
                        it["state"] = "pending"
                        it["seen"] = now
                        it["reopened"] = now
                        d["consumed"].pop(ck, None)
                        it["dep_bn"] = bn if same else None
                        it["why"] = "unconfirmed" if same else ("mismatch" if exists else "missing")
                        if self.g <= 0:
                            alarm.append(k)
        if log_poll:
            d["polls"].append((now, hd, hs, len(new), len(alarm)))
        if alarm:
            self._alarm(now, alarm, hd, hs)
        # drop finished items
        for k in [k for k, it in d["items"].items() if it["state"] == "final"]:
            d["n_final"] += 1
            del d["items"][k]
        return new, alarm

    def _backed(self, dep_id, amount, bn):
        """Whether the deposit's transaction moved `amount` of the source token into the deposit contract."""
        key = (dep_id, bn)
        if key not in self.backed:
            dep = self.S.logs(self.w["s_dep"], [T_DEPOSITED, dep_id], bn, bn)
            txs = {lg["transactionHash"] for lg in dep}
            moved = self.S.logs(self.w["s_token"], [T_TRANSFER, None, addr_topic(self.w["s_dep"])], bn, bn)
            self.backed[key] = any(lg["transactionHash"] in txs and int(lg["data"], 16) == amount for lg in moved)
        return self.backed[key]

    def _alarm(self, now, keys, hd, hs):
        d = self.data
        by_lim = {}
        for k in keys:
            it = d["items"][k]
            it["state"] = "alarmed"
            it["alarm_t"] = now
            d["alarms"].append({"t": now, "key": k, "dep_id": it["dep_id"], "amount": it["amount"], "why": it["why"],
                                "first_seen": it["first_seen"], "seen": it["seen"], "bn_d": it["bn_d"], "hd": hd, "hs": hs,
                                "reopened": it.get("reopened")})
            by_lim.setdefault(self.rec2lim[it["receiver"]], []).append(it)
        if not self.acting:
            return
        txs, meta = [], []
        for lim, its in by_lim.items():
            if lim not in d["paused_sent"]:
                txs.append(Chain.txobj(self.acc, lim, calldata("pause()"), gas=GAS_PAUSE))
                meta.append(("pause", lim, None))
            st = self.D.batch([("eth_call", [{"to": lim, "data": calldata("requests(uint256)", it["rid"])}, "latest"]) for it in its])
            for it, r in zip(its, st):
                status = decode(REQ_TYPES, r)[2]
                if status == 1:
                    txs.append(Chain.txobj(self.acc, lim, calldata("cancel(uint256)", it["rid"]), gas=GAS_CANCEL))
                    meta.append(("cancel", lim, it["rid"]))
                else:
                    d["actions"].append({"t": now, "kind": "skip", "lim": lim, "rid": it["rid"], "status": status, "hd": hd})
        if txs:
            res = self.D.send_many(txs)
            t_sent = time.time()  # wall clock when the node accepted the transactions (real-time runs)
            self.sent_now = len(txs)
            for (kind, lim, rid), h in zip(meta, res):
                rec = {"t": now, "kind": kind, "lim": lim, "rid": rid, "tx": h if isinstance(h, str) else str(h), "hd": hd, "hs": hs,
                       "t_sent_wall": t_sent}
                d["actions"].append(rec)
                if kind == "pause":
                    d["paused_sent"][lim] = rec


class Attacker:
    """Holds one of the bridge's relayer keys: queues releases for deposit ids that do not exist, and
    (as anyone may) calls executeNext through the executor."""

    def __init__(self, world, D: Chain, targets, id_base: int, S: Chain | None = None):
        self.w, self.D, self.targets, self.S = world, D, targets, S
        self.acc = world["acc"][ATT]
        self.rcpt = world["acc"][ATT_RCPT]
        self.data = {"next": 0, "sent": []}
        self.id_base = id_base

    def forge(self, now, amounts):
        """Forged deposits on the source chain through the flawed path (depositUnchecked), which
        the honest relayer then relays to every limiter; amounts: [amount, ...]."""
        txs, ids = [], []
        for a in amounts:
            fid = self.fake_id()
            txs.append(Chain.txobj(self.acc, self.w["s_dep"], calldata("depositUnchecked(bytes32,uint256,address)", fid, a, self.rcpt),
                                   gas=GAS_DEPOSIT, tip_gwei=50))
            ids.append((fid, a))
        res = self.S.send_many(txs)
        for (fid, a), h in zip(ids, res):
            self.data["sent"].append({"t": now, "kind": "forged", "lim": None, "dep_id": fid, "amount": a,
                                      "tx": h if isinstance(h, str) else str(h)})
        return len(txs)

    def fake_id(self):
        j = self.data["next"]
        self.data["next"] += 1
        return "0x" + (self.id_base + j).to_bytes(32, "big").hex()

    def relay(self, now, amounts, drain=True, tag="burst"):
        """amounts: {limiter: [amount, ...]}; each request gets a fresh id with no deposit."""
        txs, meta = [], []
        for L in self.targets:
            for a in amounts.get(L["limiter"], []):
                fid = self.fake_id()
                txs.append(Chain.txobj(self.acc, L["receiver"], calldata("relay(bytes32,address,uint256)", fid, self.rcpt, a),
                                       gas=GAS_RELAY, tip_gwei=50))
                meta.append((tag, L["limiter"], fid, a))
            if drain:
                txs.append(Chain.txobj(self.acc, self.w["executor"], calldata("drain(address,uint256)", L["limiter"], 40),
                                       gas=GAS_DRAIN, tip_gwei=50))
                meta.append(("drain", L["limiter"], None, 0))
        res = self.D.send_many(txs)
        for m, h in zip(meta, res):
            self.data["sent"].append({"t": now, "kind": m[0], "lim": m[1], "dep_id": m[2], "amount": m[3],
                                      "tx": h if isinstance(h, str) else str(h)})
        return len(txs)

    def drain(self, now, limiters):
        txs = [Chain.txobj(self.acc, self.w["executor"], calldata("drain(address,uint256)", a, 40), gas=GAS_DRAIN, tip_gwei=50)
               for a in limiters]
        res = self.D.send_many(txs)
        for a, h in zip(limiters, res):
            self.data["sent"].append({"t": now, "kind": "drain", "lim": a, "dep_id": None, "amount": 0,
                                      "tx": h if isinstance(h, str) else str(h)})
        return len(txs)
