"""Phase B: the detection, decision and pause path in real time.

The last days of the bridge's history are replayed compressed up to the failure time (which sets the
buckets as they stood then), with legitimate deposits still waiting for confirmations in the last
source blocks. Both chains are snapshotted there. Each episode reverts to that snapshot, starts the
watcher, monitor, honest relayer and keeper as separate processes, switches both nodes to mining on
the wall clock (source every 12 s, destination every Bd s), and starts the party holding the second
relayer key after a random delay. The episode ends when every limiter is paused and every unbacked
request is cancelled or executed.

Usage: python run_b.py <Bd> [--reps N] [--ports a b] [--fid E25]
Writes logs/rt_<fid>_d<Bd>.json (raw per-episode records)."""
import argparse
import json
import os
import random
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.dont_write_bytecode = True
import heapq  # noqa: E402

from tb.abi import calldata  # noqa: E402
from tb.contracts import (T_CANCELLED, T_EXECUTED_O, T_EXECUTED_T, T_PAUSED, T_RELAYED, parse_executed,  # noqa: E402
                          parse_relayed)
from tb.replay import DAY, Replay, usd  # noqa: E402
from tb.rpc import Chain  # noqa: E402

PY = sys.executable
WARM_DAYS = 3
PIPE_BLOCKS = 20  # legitimate deposits in each of the last 20 source blocks before the switch


def warm_up(fid, Bd, ports, seed, log):
    rp = Replay(fid, Bd, 64, [], ports, f"rt_{fid}_d{Bd}", os.path.join(HERE, "logs"), seed=seed, log=log)
    rp.setup()
    t_fail = rp.t_fail
    keep = {i for i, t in enumerate(rp.T) if t >= t_fail - WARM_DAYS * DAY}
    rp.sim.q = [e for e in rp.sim.q if not (e[2] == "user" and e[4][0] not in keep)]
    # pipeline: one legitimate deposit per source slot in the last PIPE_BLOCKS slots, sizes drawn from the history
    rng = random.Random(seed)
    base = len(rp.rows)
    rcpt = rp.rows[0][2]
    for j in range(PIPE_BLOCKS):
        i = rng.randrange(len(rp.rows))
        rp.rows.append((10 ** 6 + j, rp.rows[i][1], rcpt))
        rp.sim.at(t_fail - (PIPE_BLOCKS - j) * 12 + 0.5, "user", "deposit", base + j)
    heapq.heapify(rp.sim.q)
    rp.sim.queued = {(e[2], e[3], round(e[0], 6), e[4]) for e in rp.sim.q}
    rp.sim.run(t_fail)
    rp.sim.settle_pools()
    return rp


def read_jsonl(p):
    out = []
    if os.path.exists(p):
        for line in open(p, encoding="utf-8"):
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except Exception:
                    pass
    return out


def measure(rp, start_block, d_dir, Bd, P, mode):
    D, w = rp.D, rp.w
    hd = D.head()
    att = json.load(open(os.path.join(d_dir, "attacker.jsonl.final.json")))
    mon = json.load(open(os.path.join(d_dir, "monitor.jsonl.final.json")))
    blocks = {(b["chain"], b["n"]): b for b in read_jsonl(os.path.join(d_dir, "watcher.jsonl")) if b.get("ev") == "block"}
    inj = [x for x in read_jsonl(os.path.join(d_dir, "attacker.jsonl")) if x.get("ev") == "inject"]
    polls = [x for x in read_jsonl(os.path.join(d_dir, "monitor.jsonl")) if x.get("ev") == "poll"]
    fake = {x["dep_id"] for x in att["sent"] if x["dep_id"]}
    recs = [L["receiver"] for L in w["limiters"]]
    lims = [L["limiter"] for L in w["limiters"]]
    rel = [parse_relayed(lg) for lg in D.logs(recs, [T_RELAYED], start_block + 1, hd)]
    exe = [parse_executed(lg) for lg in D.logs(lims, [[T_EXECUTED_O, T_EXECUTED_T]], start_block + 1, hd)]
    can = D.logs(lims, [T_CANCELLED], start_block + 1, hd)
    pau = D.logs(lims, [T_PAUSED], start_block + 1, hd)
    gas = {}
    txs = [a["tx"] for a in mon["actions"] if a["kind"] in ("pause", "cancel")]
    for i in range(0, len(txs), 200):
        for h, r in zip(txs[i:i + 200], D.batch([("eth_getTransactionReceipt", [h]) for h in txs[i:i + 200]])):
            if r and not isinstance(r, Exception):
                gas[h] = (int(r["gasUsed"], 16), int(r["status"], 16), int(r["blockNumber"], 16))

    def wall(n):
        b = blocks.get(("D", n))
        return b["wall"] if b else None

    def ts(n):
        b = blocks.get(("D", n))
        return b["ts"] if b else int(D.block(n)["timestamp"], 16)
    out = {"Bd": Bd, "P": P, "mode": mode, "inject_wall": inj[0]["wall"] if inj else None, "limiters": {},
           "n_polls_logged": len(polls)}
    for L in w["limiters"]:
        unb = [r for r in rel if r["receiver"] == L["receiver"] and r["dep_id"] in fake]
        leg = [r for r in rel if r["receiver"] == L["receiver"] and r["dep_id"] not in fake]
        if not unb:
            continue
        urid = {r["rid"] for r in unb}
        b0 = min(r["bn"] for r in unb)
        pl = sorted((int(x["blockNumber"], 16), int(x["logIndex"], 16)) for x in pau if x["address"].lower() == L["limiter"])
        bp, lip = pl[0] if pl else (None, None)
        ex = [e for e in exe if e["limiter"] == L["limiter"]]
        rb = sum(e["value"] for e in ex if e["rid"] in urid and (bp is None or (e["bn"], e["li"]) < (bp, lip)))
        rt = sum(e["value"] for e in ex if e["rid"] in urid)
        cl = [(int(x["blockNumber"], 16), int(x["topics"][1], 16)) for x in can if x["address"].lower() == L["limiter"]]
        c_unb = [b for b, rid in cl if rid in urid]
        c_leg = [rid for b, rid in cl if rid not in urid]
        al = [x for x in mon["alarms"] if x["key"].split(":")[0] == L["receiver"]]
        pa = next((x for x in mon["actions"] if x["kind"] == "pause" and x["lim"] == L["limiter"]), None)
        r = {"b0": b0, "n_unb": len(unb), "n_leg": len(leg), "n_exec_unb": sum(1 for e in ex if e["rid"] in urid),
             "n_cancel_unb": len(c_unb), "n_cancel_legit": len(c_leg),
             "n_leg_executed": sum(1 for e in ex if e["rid"] not in urid),
             "released_before_pause_usd": usd(rb), "released_total_usd": usd(rt),
             "requested_usd": usd(sum(x["amount"] for x in unb)),
             "legit_alarms": sum(1 for x in al if x["dep_id"] not in fake)}
        w0 = wall(b0)
        r["t0_wall"] = w0
        if inj:
            r["request_incl_after_send_s"] = (w0 - inj[0]["wall"]) if w0 else None
        if al:
            fs = min(x["first_seen"] for x in al if x["dep_id"] in fake)
            r["detect_s"] = fs - w0 if w0 else None
            hd_seen = min((p["hd"] for p in polls if any(k.split(":")[0] == L["receiver"] for k in p["new"]) and p["wall"] == fs), default=None)
            if hd_seen is not None:
                r["detect_blocks"] = hd_seen - b0
        if pa:
            r["decide_s"] = pa["t_sent_wall"] - w0 if w0 else None
            r["decide_blocks"] = pa["hd"] - b0
            r["pause_tx"] = pa["tx"]
            if pa["tx"] in gas:
                r["pause_gas"] = gas[pa["tx"]][0]
        if bp is not None:
            r["pause_blocks"] = bp - b0
            r["pause_s"] = (wall(bp) - w0) if (wall(bp) and w0) else None
            r["pause_s_blockts"] = ts(bp) - ts(b0)
            if pa:
                r["pause_incl_after_send_s"] = (wall(bp) - pa["t_sent_wall"]) if wall(bp) else None
                r["pause_incl_after_send_blocks"] = bp - pa["hd"]
        if c_unb:
            bl = max(c_unb)
            r["cancel_last_blocks"] = bl - b0
            r["cancel_last_s"] = (wall(bl) - w0) if (wall(bl) and w0) else None
            r["cancel_last_s_blockts"] = ts(bl) - ts(b0)
            cg = [gas[a["tx"]][0] for a in mon["actions"] if a["kind"] == "cancel" and a["lim"] == L["limiter"] and a["tx"] in gas]
            if cg:
                r["cancel_gas"] = cg
        out["limiters"][L["name"]] = r
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("Bd", type=int)
    ap.add_argument("--reps", type=int, default=8)
    ap.add_argument("--ports", nargs=2, type=int, default=None)
    ap.add_argument("--fid", default="E25")
    ap.add_argument("--Ps", nargs="+", type=float, default=[2, 12, 60])
    ap.add_argument("--modes", nargs="+", default=["burst", "paced"])
    ap.add_argument("--seed", type=int, default=3)
    a = ap.parse_args()
    Bd = a.Bd
    ports = a.ports or ([18901, 18902] if Bd == 2 else [18911, 18912])
    tag = f"rt_{a.fid}_d{Bd}"
    logf = open(os.path.join(HERE, "logs", tag + ".log"), "w", encoding="utf-8")

    def log(msg):
        line = time.strftime("%H:%M:%S ") + msg
        print(line, flush=True)
        logf.write(line + "\n")
        logf.flush()

    rng = random.Random(a.seed)
    rp = warm_up(a.fid, Bd, ports, a.seed, log)
    S, D = rp.S, rp.D
    world_path = os.path.join(HERE, "logs", tag + "_world.json")
    json.dump(rp.w, open(world_path, "w"), indent=1)
    base = {"S_head": rp.sim.st["S"]["head"], "S_ts": rp.sim.st["S"]["last_ts"], "D_head": rp.sim.st["D"]["head"],
            "D_ts": rp.sim.st["D"]["last_ts"]}
    sids = (S.snapshot(), D.snapshot())
    log(f"[{tag}] warm-up done at t_fail {rp.t_fail}; base {base}")
    plan = [(mode, P, rep) for rep in range(a.reps) for mode in a.modes for P in a.Ps]
    rng.shuffle(plan)
    results = []
    urls = rp.urls
    for ei, (mode, P, rep) in enumerate(plan):
        # back to the state at the failure time
        assert S.revert(sids[0]) and D.revert(sids[1])
        for c in (S, D):
            try:
                c.rpc("anvil_dropAllTransactions", [])
            except Exception:
                pass
        sids = (S.snapshot(), D.snapshot())
        assert S.head() == base["S_head"] and D.head() == base["D_head"]
        d_dir = os.path.join(HERE, "logs", tag, f"ep{ei:03d}")
        os.makedirs(d_dir, exist_ok=True)
        stopf = os.path.join(d_dir, "STOP")
        if os.path.exists(stopf):
            os.remove(stopf)
        common = ["--world", world_path, "--s", urls["S"], "--d", urls["D"], "--stop", stopf, "--limit", str(P + 400)]
        procs = {}
        for role, extra in (("watcher", []), ("monitor", ["--P", str(P), "--g", "0", "--km", "64"]),
                            ("relayer", ["--k", "64"]), ("keeper", ["--Bd", str(Bd)])):
            procs[role] = subprocess.Popen([PY, "-B", os.path.join(HERE, "proc_rt.py"), role, "--out",
                                            os.path.join(d_dir, role + ".jsonl")] + common + extra,
                                           stdout=subprocess.DEVNULL, stderr=open(os.path.join(d_dir, role + ".err"), "w"))
        # wait until the monitor is polling
        t_w = time.time()
        while time.time() - t_w < 30:
            if any(x.get("ev") == "ready" for x in read_jsonl(os.path.join(d_dir, "monitor.jsonl"))):
                break
            time.sleep(0.1)
        start_block = D.head()
        S.rpc("evm_setNextBlockTimestamp", [hex(base["S_ts"] + 12)])
        D.rpc("evm_setNextBlockTimestamp", [hex(base["D_ts"] + Bd)])
        S.interval_mining(12)
        D.interval_mining(Bd)
        t_mine = time.time()
        delay = rng.uniform(2.0, 14.0)
        procs["attacker"] = subprocess.Popen([PY, "-B", os.path.join(HERE, "proc_rt.py"), "attacker", "--out",
                                              os.path.join(d_dir, "attacker.jsonl"), "--mode", mode, "--delay", str(delay),
                                              "--idbase", str((1 << 255) + ((1000 + ei) << 32))] + common,
                                             stdout=subprocess.DEVNULL, stderr=open(os.path.join(d_dir, "attacker.err"), "w"))
        # wait until every limiter is paused and no unbacked request is still queued
        t_lim = time.time() + delay + P + 240
        done_t = None
        while time.time() < t_lim:
            time.sleep(0.5)
            res = D.batch([("eth_call", [{"to": L["limiter"], "data": calldata("paused()")}, "latest"]) for L in rp.w["limiters"]])
            if all(int(r, 16) == 1 for r in res if not isinstance(r, Exception)):
                if done_t is None:
                    done_t = time.time()
                if time.time() - done_t > 3 * Bd + 4:
                    break
        open(stopf, "w").close()
        for p in procs.values():
            try:
                p.wait(timeout=20)
            except Exception:
                p.kill()
        S.interval_mining(0)
        D.interval_mining(0)
        try:
            m = measure(rp, start_block, d_dir, Bd, P, mode)
        except Exception as e:  # keep going; record the failure
            m = {"Bd": Bd, "P": P, "mode": mode, "error": repr(e)}
        m.update({"episode": ei, "rep": rep, "delay": delay, "mining_started_wall": t_mine, "all_paused": done_t is not None,
                  "wall_s": time.time() - t_mine})
        results.append(m)
        L0 = m.get("limiters", {}).get("L0", {})
        log(f"[{tag}] ep {ei + 1}/{len(plan)} {mode} P={P}: detect {L0.get('detect_s')}, pause {L0.get('pause_s')} "
            f"({L0.get('pause_blocks')} blk), released {L0.get('released_before_pause_usd')}, paused={done_t is not None}")
        json.dump({"tag": tag, "fid": a.fid, "Bd": Bd, "base": base, "t_fail": rp.t_fail, "world": rp.w,
                   "warm_days": WARM_DAYS, "pipe_blocks": PIPE_BLOCKS, "episodes": results},
                  open(os.path.join(HERE, "logs", tag + ".json"), "w"), indent=1, default=str)
    rp.close()


if __name__ == "__main__":
    main()
