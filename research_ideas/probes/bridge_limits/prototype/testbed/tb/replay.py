"""Phase A: compressed replay of a failed bridge's 150-day release history on two anvil nodes.

- legitimate stream: every priced release in data/legit/<ID>.csv becomes a deposit on the source
  chain, made k source blocks before the historical release time so that the relayer's request lands
  at that time; the relayer relays it to every limiter on the destination chain once it has k
  confirmations; a keeper executes queued requests as soon as hold and buckets allow;
- shadow monitors: monitors with different confirmation depths, graces and polling intervals follow
  the same chains and record the alarms they would raise (no transaction);
- failure episodes: at chosen times the chains are snapshotted, the relayer key queues releases for
  deposit ids that do not exist (a burst, or a paced stream), an acting monitor pauses and cancels,
  the outcome is read from the destination chain, and both chains are reverted;
- reorganizations (optional): right after the relayer relays a deposit, the source chain drops the
  blocks back to and including that deposit; the deposits are sent again (variant a) or the relied-
  upon ones are not (variant b)."""
from __future__ import annotations

import json
import math
import os
import random
import time

import numpy as np

from . import fit as F
from .abi import calldata, decode
from .agents import Attacker, Depositor, Keeper, Monitor, Relayer
from .contracts import (T_CANCELLED, T_EXECUTED_O, T_EXECUTED_T, T_PAUSED, T_QUEUED_O, T_QUEUED_T, T_RELAYED,
                        parse_executed, parse_relayed)
from .des import AttackerDES, KeeperDES, MonitorDES, RelayerDES, Sim, UserDES
from .rpc import Chain
from .world import RCPT, connect, deploy_world, start_anvil, stop

BS = 12
WAD = 10 ** 18
FAKE = 1 << 255
DAY = 86400.0


def usd(x):
    return x / WAD


def limiter_configs(t, v, t_fail, margin=1.5):
    B1, R1, n1 = F.fit_bucket(t, v, t_fail, 3600, margin)
    B2, R2, n2 = F.fit_bucket(t, v, t_fail, 86400, margin)
    c1, r1 = F.bucket_units(B1, R1)
    c2, r2 = F.bucket_units(B2, R2)
    lims = [dict(name="L0", kind="outflow", hold=0, buckets=[(c1, r1)]),
            dict(name="L10", kind="outflow", hold=600, buckets=[(c1, r1)]),
            dict(name="T0", kind="tuned", hold=0, buckets=[(c1, r1), (c2, r2)])]
    fits = {"D_1h": {"B_usd": B1, "R_usd_per_h": R1 * 3600, "n_fit": n1, "cap_units": c1, "refill_units_per_s": r1},
            "D_24h": {"B_usd": B2, "R_usd_per_h": R2 * 3600, "n_fit": n2, "cap_units": c2, "refill_units_per_s": r2},
            "margin": margin, "fit_window_days": [120, 30]}
    return lims, fits


class ReorgerDES:
    """Drops source blocks right after the relayer relied on a deposit in them."""

    def __init__(self, depositor, variant, every, delay_range, rng):
        self.dep = depositor
        self.variant = variant
        self.every = every
        self.delay_range = delay_range
        self.rng = rng
        self.data = {"events": [], "count": 0}

    def hook(self, sim, out, h):
        for x in out:
            self.data["count"] += 1
            if self.data["count"] % self.every == 0:
                sim.at(sim.now + self.rng.uniform(*self.delay_range), self.name, "reorg", x["dep_id"], x["bn"])

    def reorg(self, sim, dep_id, bn):
        st = sim.st["S"]
        if st["pool"]:
            sim.at(st["mine_at"] + 0.05, self.name, "reorg", dep_id, bn)
            return
        h = st["head"]
        extra = self.rng.choice([0, 1, 2])
        depth = h - bn + 1 + extra
        relayed = sim.agents["relayer"].r.data["relayed"]
        dropped = sim.reorg_source(depth)
        targets = [x for x in dropped if x["dep_id"] in relayed]
        if self.variant == "a":
            resend = dropped
        else:
            resend = [x for x in dropped if x["dep_id"] not in relayed]
        for x in resend:
            self.dep.deposit(x["dep_id"], x["amount"], x["to"])
        if resend:
            sim.tx_sent("S", len(resend))
        else:
            sim.need_source_head(h + 1)
        sim.notify("S", h, st["last_ts"], False, True)
        self.data["events"].append({"t": sim.now, "trigger": dep_id, "head": h, "depth": depth, "bn": bn,
                                    "targets": [x["dep_id"] for x in targets], "dropped": [x["dep_id"] for x in dropped],
                                    "resent": [x["dep_id"] for x in resend],
                                    "relay_t": {x["dep_id"]: relayed[x["dep_id"]][0] for x in targets}})


class Replay:
    def __init__(self, fid, Bd, k, shadow, ports, tag, out_dir, seed=1, reorg=None, injections=None,
                 keep_states=512, k_acting=None, log=print):
        self.fid, self.Bd, self.k, self.shadow, self.ports, self.tag = fid, Bd, k, shadow, ports, tag
        self.out_dir = out_dir
        self.rng = random.Random(seed)
        self.reorg_cfg = reorg
        self.inj_cfg = injections
        self.keep_states = keep_states
        self.k_acting = k_acting if k_acting is not None else k
        self.log = log
        self.conns = []

    # -------------------------------------------------------------- setup
    def chain(self, which):
        c = Chain(self.urls[which], which)
        self.conns.append(c)
        return c

    def setup(self):
        t_fail, leg, t, v, counts = F.history(self.fid)
        self.t_fail, self.leg, self.T, self.V, self.counts = t_fail, leg, t, v, counts
        self.lims_cfg, self.fits = limiter_configs(t, v, t_fail)
        dep_times = t - self.k * BS
        genesis = int(dep_times[0] - 2 * DAY)
        self.urls = {"S": f"http://127.0.0.1:{self.ports[0]}", "D": f"http://127.0.0.1:{self.ports[1]}"}
        self.procs = [start_anvil(self.ports[0], 1001, genesis, keep_states=self.keep_states),
                      start_anvil(self.ports[1], 1002, genesis, keep_states=self.keep_states)]
        self.S = connect(self.urls["S"], "S")
        self.D = connect(self.urls["D"], "D")
        self.w = deploy_world(self.S, self.D, self.lims_cfg)
        self.lim_by_name = {L["name"]: L for L in self.w["limiters"]}
        self.sim = Sim(self.S, self.D, BS, self.Bd, world=self.w)
        rcpt = self.w["acc"][RCPT]
        self.rows = [(i + 1, max(1, F.to_units(float(v[i]))), rcpt) for i in range(len(t))]
        self.depositor = Depositor(self.w, self.chain("S"))
        self.sim.add("user", UserDES(self.depositor, self.rows))
        hook = None
        if self.reorg_cfg:
            rg = ReorgerDES(Depositor(self.w, self.chain("S")), self.reorg_cfg["variant"], self.reorg_cfg["every"],
                            tuple(self.reorg_cfg["delay_range"]), random.Random(self.reorg_cfg.get("seed", 7)))
            self.sim.add("reorger", rg)
            hook = rg.hook
        self.sim.add("relayer", RelayerDES(Relayer(self.w, self.chain("S"), self.chain("D"), self.k), react=1.0, hook=hook))
        self.sim.add("keeper", KeeperDES(Keeper(self.w, self.chain("D")), react=0.5))
        self.shadow_phi = {}
        for m in self.shadow:
            mon = Monitor(m["name"], self.w, self.chain("S"), self.chain("D"), m["k_m"], m["g"], m.get("kf"), acting=False,
                          start_block=self.D.head())
            phi = self.rng.uniform(0, m["P"])
            self.shadow_phi[m["name"]] = phi
            self.sim.add("mon:" + m["name"], MonitorDES(mon, m["P"], phi))
        for i, td in enumerate(dep_times):
            self.sim.at(float(td), "user", "deposit", i)
        self.log(f"[{self.tag}] setup: {len(t)} releases, t_fail {t_fail}, genesis {genesis}, fits {self.fits['D_1h']['B_usd']:.0f} "
                 f"/ {self.fits['D_1h']['R_usd_per_h']:.0f} per h")

    # -------------------------------------------------------------- failure episodes
    def bucket_state(self, block):
        """Available tokens per limiter (per bucket) at the end of `block` and that block's timestamp."""
        tsb = int(self.D.block(block)["timestamp"], 16)
        out = {}
        for L in self.w["limiters"]:
            if L["kind"] == "outflow":
                out[L["limiter"]] = [int(self.D.call(L["limiter"], calldata("available()"), block), 16)]
            else:
                out[L["limiter"]] = [int(self.D.call(L["limiter"], calldata("available(uint256)", k), block), 16)
                                     for k in range(len(L["buckets"]))]
        return tsb, out

    def episode(self, idx, mode, P, g, k_m, phi, t_inj, T_max=900.0, pace_s=60.0, n_burst=20, value_check=False):
        sim, w = self.sim, self.w
        saved = sim.save()
        start_block = sim.st["D"]["head"]
        Sm, Dm, Da, Sa = Chain(self.urls["S"]), Chain(self.urls["D"]), Chain(self.urls["D"]), Chain(self.urls["S"])
        mon = Monitor("acting", w, Sm, Dm, k_m, g, None, acting=True, start_block=start_block, value_check=value_check)
        sim.add("mon:acting", MonitorDES(mon, P, phi))
        att = Attacker(w, Da, w["limiters"], FAKE + (idx << 32), S=Sa)
        burst, paced = {}, {}
        for L in w["limiters"]:
            cap = min(c for c, _ in L["buckets"])
            refill = min(r for _, r in L["buckets"])
            burst[L["limiter"]] = [cap // 10] * n_burst
            paced[L["limiter"]] = [int(0.5 * refill * pace_s)]
        if mode == "forged":
            # one forged deposit is relayed to every limiter, so the amounts are one list, sized
            # like a burst at the smallest bucket
            cap = min(c for L in w["limiters"] for c, _ in L["buckets"])
            burst = [cap // 10] * n_burst
        t_end = t_inj + T_max
        sim.add("attacker", AttackerDES(att, mode, burst, paced, pace_s, t_end))
        sim.at(t_inj, "attacker", "start")
        sim.activate_dest(t_inj, t_end)

        def done(s):
            ps = mon.data["paused_sent"]
            if len(ps) < len(w["limiters"]):
                return False
            return s.now >= max(x["t"] for x in ps.values()) + 120.0
        w0 = time.time()
        sim.run(t_end, stop=done)
        res = self.measure(start_block, att, mon, mode, P, g, k_m, phi, t_inj)
        res["wall_s"] = time.time() - w0
        res["value_check"] = value_check
        sim.restore(saved)
        for c in (Sm, Dm, Da, Sa):
            c.close()
        return res

    def measure(self, start_block, att, mon, mode, P, g, k_m, phi, t_inj):
        D, w = self.D, self.w
        hd = D.head()
        fake = {x["dep_id"] for x in att.data["sent"] if x["dep_id"]}
        recs = [L["receiver"] for L in w["limiters"]]
        lims = [L["limiter"] for L in w["limiters"]]
        rel = [parse_relayed(lg) for lg in D.logs(recs, [T_RELAYED], start_block + 1, hd)]
        exe = [parse_executed(lg) for lg in D.logs(lims, [[T_EXECUTED_O, T_EXECUTED_T]], start_block + 1, hd)]
        can = D.logs(lims, [T_CANCELLED], start_block + 1, hd)
        pau = D.logs(lims, [T_PAUSED], start_block + 1, hd)
        bns = set()
        out = {"mode": mode, "P": P, "g": g, "k_m": k_m, "phi": phi, "t_inj": t_inj, "Bd": self.Bd, "limiters": {}}
        per = {}
        for L in w["limiters"]:
            unb = [r for r in rel if r["receiver"] == L["receiver"] and r["dep_id"] in fake]
            leg = [r for r in rel if r["receiver"] == L["receiver"] and r["dep_id"] not in fake]
            if not unb:
                continue
            urid = {r["rid"]: r for r in unb}
            b0 = min(r["bn"] for r in unb)
            pl = sorted([(int(x["blockNumber"], 16), int(x["logIndex"], 16), x["transactionHash"]) for x in pau
                         if x["address"].lower() == L["limiter"]])
            bp, lip, ptx = pl[0] if pl else (None, None, None)
            ex = [e for e in exe if e["limiter"] == L["limiter"]]
            rel_before = sum(e["value"] for e in ex if e["rid"] in urid and (bp is None or (e["bn"], e["li"]) < (bp, lip)))
            rel_total = sum(e["value"] for e in ex if e["rid"] in urid)
            n_exec_unb = sum(1 for e in ex if e["rid"] in urid)
            cl = [(int(x["blockNumber"], 16), int(x["topics"][1], 16)) for x in can if x["address"].lower() == L["limiter"]]
            c_unb = [b for b, rid in cl if rid in urid]
            c_leg = [rid for b, rid in cl if rid not in urid]
            al = [a for a in mon.data["alarms"] if a["key"].split(":")[0] == L["receiver"]]
            first_seen = min((a["first_seen"] for a in al), default=None)
            t_alarm = min((a["t"] for a in al), default=None)
            seen_hd = min((a["hd"] for a in al if a["t"] == t_alarm), default=None)
            pa = mon.data["paused_sent"].get(L["limiter"])
            ca = [a for a in mon.data["actions"] if a["kind"] == "cancel" and a["lim"] == L["limiter"]]
            per[L["name"]] = dict(b0=b0, bp=bp, ptx=ptx, bc_first=min(c_unb) if c_unb else None, bc_last=max(c_unb) if c_unb else None,
                                  n_unb=len(unb), n_leg=len(leg), n_exec_unb=n_exec_unb, n_cancel_unb=len(c_unb),
                                  n_cancel_legit=len(c_leg), released_before_pause=rel_before, released_total=rel_total,
                                  requested=sum(r["amount"] for r in unb), first_seen=first_seen, t_alarm=t_alarm, alarm_hd=seen_hd,
                                  pause_sent_t=pa["t"] if pa else None, pause_sent_hd=pa["hd"] if pa else None,
                                  cancel_txs=[a["tx"] for a in ca], pause_tx=pa["tx"] if pa else None)
            bns |= {x for x in (b0, bp, per[L["name"]]["bc_last"], per[L["name"]]["bc_first"], seen_hd) if x is not None}
            if b0 > 1:
                bns.add(b0 - 1)
        bl = sorted(bns)
        tsd = {}
        for i in range(0, len(bl), 200):
            res = D.batch([("eth_getBlockByNumber", [hex(n), False]) for n in bl[i:i + 200]])
            for n, b in zip(bl[i:i + 200], res):
                tsd[n] = int(b["timestamp"], 16)
        # gas of the monitor's transactions
        txs = [x for p in per.values() for x in ([p["pause_tx"]] if p["pause_tx"] else []) + p["cancel_txs"]]
        gas = {}
        for i in range(0, len(txs), 200):
            for h, r in zip(txs[i:i + 200], D.batch([("eth_getTransactionReceipt", [h]) for h in txs[i:i + 200]])):
                if isinstance(r, Exception):
                    self.log(f"receipt error {h}: {r}")
                    continue
                if r:
                    gas[h] = (int(r["gasUsed"], 16), int(r["status"], 16), int(r["blockNumber"], 16))
        for name, p in per.items():
            L = self.lim_by_name[name]
            ts0 = tsd[p["b0"]]
            r = {k: p[k] for k in ("b0", "n_unb", "n_leg", "n_exec_unb", "n_cancel_unb", "n_cancel_legit")}
            r["ts0"] = ts0
            r["requested_usd"] = usd(p["requested"])
            r["released_before_pause_usd"] = usd(p["released_before_pause"])
            r["released_total_usd"] = usd(p["released_total"])
            if p["first_seen"] is not None:
                r["detect_s"] = p["first_seen"] - ts0
                r["decide_s"] = p["t_alarm"] - ts0
                r["detect_blocks"] = p["alarm_hd"] - p["b0"]
            if p["bp"] is not None:
                r["pause_s"] = tsd[p["bp"]] - ts0
                r["pause_blocks"] = p["bp"] - p["b0"]
                r["pause_incl_after_send_s"] = tsd[p["bp"]] - p["pause_sent_t"] if p["pause_sent_t"] else None
                r["pause_incl_after_send_blocks"] = p["bp"] - p["pause_sent_hd"] if p["pause_sent_hd"] else None
            if p["bc_last"] is not None:
                r["cancel_first_s"] = tsd[p["bc_first"]] - ts0
                r["cancel_last_s"] = tsd[p["bc_last"]] - ts0
                r["cancel_last_blocks"] = p["bc_last"] - p["b0"]
            if p["pause_tx"] in gas:
                r["pause_gas"] = gas[p["pause_tx"]][0]
            cg = [gas[h][0] for h in p["cancel_txs"] if h in gas and gas[h][1] == 1]
            if cg:
                r["cancel_gas"] = cg
            # bucket state just before the first unbacked request, and the fluid release bounds
            if p["b0"] - 1 in tsd:
                tsb, av = self.bucket_state(p["b0"] - 1)
                av0 = [min(c, a + rf * (ts0 - tsb)) for (c, rf), a in zip(L["buckets"], av[L["limiter"]])]
                r["available_at_inj_usd"] = usd(min(av0))
                if p["bp"] is not None and L["hold"] == 0:
                    dtp = tsd[p["bp"]] - ts0
                    r["fluid_bound_at_pause_usd"] = usd(min(a + rf * dtp for (c, rf), a in zip(L["buckets"], av0)))
                r["fluid_bound_10min_usd"] = usd(min(a + rf * max(0, 600 - L["hold"]) for (c, rf), a in zip(L["buckets"], av0))
                                                 if L["hold"] < 600 else 0.0)
            out["limiters"][name] = r
        out["n_alarms"] = len(mon.data["alarms"])
        out["alarm_reasons"] = sorted({a["why"] for a in mon.data["alarms"]})
        return out

    def run_injections(self, points, combos, reps_last=1, T_max=900.0):
        res = []
        idx = 0
        for j, tp in enumerate(points):
            self.sim.run(tp)
            self.sim.settle_pools()
            reps = reps_last if j == len(points) - 1 else 1
            for rep in range(reps):
                for mode, P, g in combos:
                    idx += 1
                    phi = self.rng.uniform(0, P)
                    t_inj = self.sim.now + 1.0 + self.rng.uniform(0, self.Bd)
                    r = self.episode(idx, mode, P, g, self.k_acting, phi, t_inj, T_max=T_max)
                    r["point"] = j
                    r["at_failure_time"] = j == len(points) - 1
                    r["rep"] = rep
                    res.append(r)
            self.log(f"[{self.tag}] injections at point {j + 1}/{len(points)} (t={tp:.0f}) done; episodes {idx}")
        return res

    # -------------------------------------------------------------- statistics after the replay
    def block_ts(self, chain, bns):
        bl = sorted(set(bns))
        out = {}
        for i in range(0, len(bl), 500):
            res = chain.batch([("eth_getBlockByNumber", [hex(n), False]) for n in bl[i:i + 500]])
            for n, b in zip(bl[i:i + 500], res):
                out[n] = int(b["timestamp"], 16)
        return out

    def legit_stats(self):
        D, w = self.D, self.w
        hd = D.head()
        recs = [L["receiver"] for L in w["limiters"]]
        lims = [L["limiter"] for L in w["limiters"]]
        rel = [parse_relayed(lg) for lg in D.logs(recs, [T_RELAYED], 0, hd)]
        exe = [parse_executed(lg) for lg in D.logs(lims, [[T_EXECUTED_O, T_EXECUTED_T]], 0, hd)]
        ts = self.block_ts(D, [r["bn"] for r in rel] + [e["bn"] for e in exe])
        out = {}
        for L in w["limiters"]:
            req = {r["rid"]: r for r in rel if r["receiver"] == L["receiver"]}
            ex = {e["rid"]: e for e in exe if e["limiter"] == L["limiter"]}
            rids = sorted(req)
            t_req = np.array([ts[req[i]["bn"]] for i in rids], dtype=float)
            val = np.array([usd(req[i]["amount"]) for i in rids])
            done = np.array([i in ex for i in rids])
            t_ex = np.array([ts[ex[i]["bn"]] if i in ex else np.nan for i in rids])
            wait = t_ex - t_req
            mech = max(L["hold"], self.Bd)
            excess = wait - mech
            delayed = excess > 0.5
            # fluid FIFO bucket(s) on the same arrival times (shifted by the hold)
            fl = np.zeros(len(rids))
            for cap, refill in L["buckets"]:
                d = F.fifo_delays(list(t_req + L["hold"]), list(val), usd(cap) * (1 + 1e-9) + 1e-6, usd(refill))
                fl = np.maximum(fl, np.array(d))
            fl_delayed = fl > 1e-6
            wins = {"all": np.ones(len(rids), bool),
                    "first_30d": t_req < self.t_fail - 120 * DAY,
                    "fit_90d": (t_req >= self.t_fail - 120 * DAY) & (t_req < self.t_fail - 30 * DAY),
                    "test_30d": t_req >= self.t_fail - 30 * DAY}
            o = {"hold": L["hold"], "kind": L["kind"], "n_requests": len(rids), "n_executed": int(done.sum()),
                 "value_usd": float(val.sum()), "min_wait_s": mech}
            for wn, m in wins.items():
                if not m.any():
                    continue
                dm = delayed & m & done
                o[wn] = {"n": int(m.sum()), "value_usd": float(val[m].sum()),
                         "n_delayed": int(dm.sum()), "value_delayed_usd": float(val[dm].sum()),
                         "share_value_delayed": float(val[dm].sum() / val[m].sum()),
                         "excess_wait_p50_h": float(np.median(excess[dm]) / 3600) if dm.any() else 0.0,
                         "excess_wait_max_h": float(np.max(excess[dm]) / 3600) if dm.any() else 0.0,
                         "wait_p50_s": float(np.nanmedian(wait[m])), "wait_p99_s": float(np.nanquantile(wait[m], 0.99)),
                         "fluid_n_delayed": int((fl_delayed & m).sum()),
                         "fluid_share_value_delayed": float(val[fl_delayed & m].sum() / val[m].sum()),
                         "max_abs_diff_onchain_vs_fluid_s": float(np.nanmax(np.abs(excess[m & done] - fl[m & done]))) if (m & done).any() else 0.0}
            out[L["name"]] = o
        return out

    def shadow_stats(self, reorg_events=None):
        out = {}
        tgt = {}
        resent = set()
        if reorg_events:
            for e in reorg_events:
                for d in e["targets"]:
                    tgt[d] = e
                resent |= set(e["resent"])
        for m in self.shadow:
            mon = self.sim.agents["mon:" + m["name"]].m
            al = mon.data["alarms"]
            o = {"cfg": m, "phi": self.shadow_phi[m["name"]], "n_polls": mon.data["n_polls"], "n_matched": mon.data["n_matched"],
                 "n_alarms": len(al), "alarms_by_reason": {}, "n_alarmed_deposits": len({a["dep_id"] for a in al}),
                 "open_at_end": sum(1 for it in mon.data["items"].values() if it["state"] in ("pending", "prov"))}
            for a in al:
                o["alarms_by_reason"][a["why"]] = o["alarms_by_reason"].get(a["why"], 0) + 1
            if reorg_events is not None:
                al_ids = {}
                for a in al:
                    al_ids.setdefault(a["dep_id"], []).append(a)
                n_t = len(tgt)
                hit = [d for d in tgt if d in al_ids]
                o["reorg_targets"] = n_t
                o["reorg_targets_alarmed"] = len(hit)
                o["reorg_targets_resent"] = sum(1 for d in tgt if d in resent)
                o["alarms_on_resent_targets"] = sum(1 for d in hit if d in resent)
                o["alarms_on_dropped_targets"] = sum(1 for d in hit if d not in resent)
                o["alarm_delay_after_reorg_s"] = sorted(min(a["t"] for a in al_ids[d]) - tgt[d]["t"] for d in hit)
                o["alarms_on_other_deposits"] = sum(1 for d in al_ids if d not in tgt)
            out[m["name"]] = o
        return out

    def close(self):
        for c in self.conns:
            c.close()
        stop(self.procs)
