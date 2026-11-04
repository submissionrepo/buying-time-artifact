"""Compressed replay on two anvil nodes. Simulated time is the historical time: every block carries
the timestamp of its slot (multiples of the chain's block time). Blocks are mined on demand: a slot
gets a block when a transaction is waiting for it, when some agent waits for a confirmation depth
(the source then mines every slot until that depth is reached), or during a failure episode (the
destination then mines every slot). Idle stretches are skipped, which is the compression. Agents act
only through their own RPC connections; the driver only decides when each one wakes. A monitor wakes
at its own polling grid, and only when a block arrived or a deadline passed since its last poll,
which leaves out polls that would have changed nothing."""
from __future__ import annotations

import copy
import heapq
import math

from .abi import calldata, id32
from .contracts import T_DEPOSITED, parse_deposited


class Sim:
    def __init__(self, S, D, Bs, Bd, world=None):
        self.S, self.D = S, D
        self.world = world
        self.ch = {"S": S, "D": D}
        self.B = {"S": Bs, "D": Bd}
        self.q = []
        self.seq = 0
        self.queued = set()
        self.agents = {"sim": self}
        self.st = {}
        for c in ("S", "D"):
            b = self.ch[c].block()
            self.st[c] = {"head": int(b["number"], 16), "last_ts": int(b["timestamp"], 16), "pool": 0, "mine_at": None,
                          "need": 0, "active_from": None, "active_until": -1.0, "n_blocks": 0, "n_empty": 0}
        self.now = 0.0
        self.data = {}

    # ------------------------------------------------------------------ scheduling
    def add(self, name, agent):
        agent.name = name
        self.agents[name] = agent

    def remove(self, name):
        self.agents.pop(name, None)

    def at(self, t, name, meth="wake", *args):
        key = (name, meth, round(t, 6), args)
        if key in self.queued:
            return
        self.queued.add(key)
        self.seq += 1
        heapq.heappush(self.q, (t, self.seq, name, meth, args))

    def slot_after(self, c, t):
        B = self.B[c]
        return (math.floor(t / B + 1e-9) + 1) * B

    def slot_ge(self, c, t):
        B = self.B[c]
        return math.ceil(t / B - 1e-9) * B

    # ------------------------------------------------------------------ mining
    def tx_sent(self, c, n=1):
        if n <= 0:
            return
        st = self.st[c]
        st["pool"] += n
        if st["mine_at"] is None:
            s = self.slot_after(c, max(self.now, st["last_ts"]))
            st["mine_at"] = s
            self.at(s, "sim", "mine", c, s)

    def mine(self, sim, c, s):
        st = self.st[c]
        if st["mine_at"] != s:
            return
        self.ch[c].mine_at(s)
        st["head"] += 1
        st["last_ts"] = s
        st["pool"] = 0
        st["mine_at"] = None
        st["n_blocks"] += 1
        self.notify(c, st["head"], s, True, False)

    def notify(self, c, num, ts, had_txs, reorg):
        for name, a in list(self.agents.items()):
            if name != "sim" and hasattr(a, "on_block"):
                a.on_block(self, c, num, ts, had_txs, reorg)

    def catch_up(self, t):
        st = self.st["S"]
        if st["pool"] == 0 and st["active_from"] is not None:
            if st["need"] <= st["head"]:
                st["active_from"] = None
            else:
                first = self.slot_after("S", max(st["last_ts"], st["active_from"]))
                if t >= first:
                    n = min(int(math.floor((t - first) / self.B["S"] + 1e-9)) + 1, st["need"] - st["head"])
                    self.S.mine_n(n, first, self.B["S"])
                    st["head"] += n
                    st["last_ts"] = first + (n - 1) * self.B["S"]
                    st["n_blocks"] += n
                    st["n_empty"] += n
                    if st["head"] >= st["need"]:
                        st["active_from"] = None
                    self.notify("S", st["head"], st["last_ts"], False, False)
        st = self.st["D"]
        if st["pool"] == 0 and st["active_from"] is not None:
            first = self.slot_after("D", max(st["last_ts"], st["active_from"]))
            last = min(t, st["active_until"])
            if last >= first:
                n = int(math.floor((last - first) / self.B["D"] + 1e-9)) + 1
                self.D.mine_n(n, first, self.B["D"])
                st["head"] += n
                st["last_ts"] = first + (n - 1) * self.B["D"]
                st["n_blocks"] += n
                st["n_empty"] += n
                self.notify("D", st["head"], st["last_ts"], False, False)
            if t >= st["active_until"]:
                st["active_from"] = None

    def need_source_head(self, X):
        st = self.st["S"]
        if X > st["need"]:
            st["need"] = X
        if X > st["head"] and st["active_from"] is None:
            st["active_from"] = self.now
        return self.time_of_head(X)

    def time_of_head(self, X):
        st = self.st["S"]
        if X <= st["head"]:
            return self.now
        base = st["active_from"] if st["active_from"] is not None else self.now
        first = self.slot_after("S", max(st["last_ts"], base))
        return first + (X - st["head"] - 1) * self.B["S"]

    def activate_dest(self, t_from, t_until):
        st = self.st["D"]
        st["active_from"] = t_from
        st["active_until"] = t_until

    # ------------------------------------------------------------------ reorganization of the source
    def reorg_source(self, depth):
        """Replace the last `depth` source blocks by empty blocks at the same slots. Returns the
        deposits that were in the dropped blocks."""
        st = self.st["S"]
        assert st["pool"] == 0
        h = st["head"]
        lo = h - depth + 1
        dropped = [parse_deposited(lg) for lg in self.S.logs(self.world["s_dep"], [T_DEPOSITED], lo, h)]
        blocks = self.S.batch([("eth_getBlockByNumber", [hex(n), False]) for n in range(lo, h + 1)])
        tss = [int(b["timestamp"], 16) for b in blocks]
        self.S.rpc("anvil_rollback", [depth])
        try:
            self.S.rpc("anvil_dropAllTransactions", [])
        except Exception:
            pass
        for ts in tss:
            self.S.mine_at(ts)
        assert self.S.head() == h
        return dropped

    # ------------------------------------------------------------------ snapshots for failure episodes
    def save(self):
        assert self.st["S"]["pool"] == 0 and self.st["D"]["pool"] == 0
        sids = (self.S.snapshot(), self.D.snapshot())
        state = copy.deepcopy({"st": self.st, "q": self.q, "seq": self.seq, "queued": self.queued, "now": self.now,
                               "agents": {n: a.data for n, a in self.agents.items() if n != "sim"}})
        return sids, state, set(self.agents)

    def restore(self, saved):
        sids, state, names = saved
        assert self.S.revert(sids[0]) and self.D.revert(sids[1])
        for c in (self.S, self.D):
            try:
                c.rpc("anvil_dropAllTransactions", [])
            except Exception:
                pass
        for n in list(self.agents):
            if n not in names:
                self.remove(n)
        st = copy.deepcopy(state)
        self.st, self.q, self.seq, self.queued, self.now = st["st"], st["q"], st["seq"], st["queued"], st["now"]
        for n, d in st["agents"].items():
            self.agents[n].data = d
        assert self.S.head() == self.st["S"]["head"] and self.D.head() == self.st["D"]["head"]

    # ------------------------------------------------------------------ main loop
    def run(self, until, stop=None):
        while self.q and self.q[0][0] <= until:
            t, _, name, meth, args = heapq.heappop(self.q)
            self.queued.discard((name, meth, round(t, 6), args))
            a = self.agents.get(name)
            if a is None:
                continue
            self.catch_up(t)
            self.now = t
            getattr(a, meth)(self, *args)
            if stop is not None and stop(self):
                return True
        if until > self.now:
            self.catch_up(until)
            self.now = until
        return False

    def settle_pools(self, limit=60.0):
        """Advance until neither chain has a pending transaction (needed before a snapshot)."""
        t_lim = self.now + limit
        while (self.st["S"]["pool"] or self.st["D"]["pool"]) and self.q and self.q[0][0] <= t_lim:
            self.run(self.q[0][0])
        assert not (self.st["S"]["pool"] or self.st["D"]["pool"])


# ---------------------------------------------------------------------- agent adapters
class UserDES:
    def __init__(self, depositor, rows):
        self.dep = depositor
        self.rows = rows  # list of (dep_id_int, amount_units, recipient)
        self.data = {}

    def deposit(self, sim, i):
        dep_id, amount, rcpt = self.rows[i]
        self.dep.deposit(id32(dep_id), amount, rcpt)
        sim.tx_sent("S")


class RelayerDES:
    def __init__(self, relayer, react=1.0, hook=None):
        self.r = relayer
        self.react = react
        self.hook = hook

    @property
    def data(self):
        return self.r.data

    @data.setter
    def data(self, v):
        self.r.data = v

    def on_block(self, sim, c, num, ts, had_txs, reorg):
        if c == "S" and (had_txs or reorg):
            sim.at(max(ts, sim.now) + self.react, self.name)

    def wake(self, sim):
        out, h, ntx = self.r.scan(sim.now)
        if ntx:
            sim.tx_sent("D", ntx)
        if out and self.hook is not None:
            self.hook(sim, out, h)
        need = self.r.need_head()
        if need is not None:
            sim.at(sim.need_source_head(need) + self.react, self.name)


class KeeperDES:
    def __init__(self, keeper, react=0.5):
        self.k = keeper
        self.react = react

    @property
    def data(self):
        return self.k.data

    @data.setter
    def data(self, v):
        self.k.data = v

    def on_block(self, sim, c, num, ts, had_txs, reorg):
        if c == "D" and had_txs:
            sim.at(ts + self.react, self.name)

    def wake(self, sim):
        plan = self.k.plan()
        ns = sim.slot_after("D", sim.now)
        now_l = []
        for lim, te in plan.items():
            if te is None:
                continue
            s = max(sim.slot_ge("D", te), ns)
            if s <= ns:
                now_l.append(lim)
            else:
                sim.at(s - sim.B["D"] + 0.01, self.name)
        if now_l:
            self.k.execute(now_l)
            sim.tx_sent("D", len(now_l))


class MonitorDES:
    def __init__(self, mon, P, phi):
        self.m = mon
        self.P = P
        self.phi = phi

    @property
    def data(self):
        return self.m.data

    @data.setter
    def data(self, v):
        self.m.data = v

    def grid(self, t):
        return self.phi + math.ceil((t - self.phi) / self.P - 1e-9) * self.P

    def on_block(self, sim, c, num, ts, had_txs, reorg):
        if c == "D" and had_txs:
            sim.at(self.grid(ts + 1e-3), self.name)
        elif c == "S":
            if reorg and self.m.has_open():
                sim.at(self.grid(sim.now + 1e-3), self.name)
            elif had_txs and self.m.has_pending_missing():
                sim.at(self.grid(ts + 1e-3), self.name)

    def wake(self, sim):
        self.m.poll(sim.now)
        if self.m.sent_now:
            sim.tx_sent("D", self.m.sent_now)
        X = self.m.need_source_head()
        if X is not None:
            sim.at(self.grid(sim.need_source_head(X) + 1e-3), self.name)
        dl = self.m.next_deadline()
        if dl is not None and dl > sim.now + 1e-9:
            sim.at(self.grid(dl), self.name)


class AttackerDES:
    """Unbacked requests with the relayer key from t_inj; executeNext on every destination slot
    (submitted right after the previous block, so it precedes any pause sent in the same interval)."""

    def __init__(self, att, mode, burst_amounts, paced_amounts, pace_s, t_end):
        self.a = att
        self.mode = mode
        self.burst_amounts = burst_amounts
        self.paced_amounts = paced_amounts
        self.pace_s = pace_s
        self.t_end = t_end

    @property
    def data(self):
        return self.a.data

    @data.setter
    def data(self, v):
        self.a.data = v

    def _unpaused(self):
        res = self.a.D.batch([("eth_call", [{"to": L["limiter"], "data": calldata("paused()")}, "latest"]) for L in self.a.targets])
        return [L["limiter"] for L, r in zip(self.a.targets, res) if int(r, 16) == 0]

    def start(self, sim):
        if self.mode == "forged":
            # forged deposits on the source chain; the honest relayer relays them, and the
            # party only calls executeNext on the destination from then on
            sim.tx_sent("S", self.a.forge(sim.now, self.burst_amounts))
            sim.at(sim.slot_after("D", sim.now) + 0.01, self.name, "tick")
            return
        amounts = self.burst_amounts if self.mode == "burst" else self.paced_amounts
        sim.tx_sent("D", self.a.relay(sim.now, amounts, drain=True, tag=self.mode))
        if self.mode == "paced":
            sim.at(sim.now + self.pace_s, self.name, "pace")
        sim.at(sim.slot_after("D", sim.now) + 0.01, self.name, "tick")

    def tick(self, sim):
        if sim.now > self.t_end:
            return
        lims = self._unpaused()
        if lims:
            sim.tx_sent("D", self.a.drain(sim.now, lims))
            sim.at(sim.slot_after("D", sim.now) + 0.01, self.name, "tick")

    def pace(self, sim):
        if sim.now > self.t_end:
            return
        lims = set(self._unpaused())
        if not lims:
            return
        amounts = {k: v for k, v in self.paced_amounts.items() if k in lims}
        sim.tx_sent("D", self.a.relay(sim.now, amounts, drain=True, tag="paced"))
        sim.at(sim.now + self.pace_s, self.name, "pace")
