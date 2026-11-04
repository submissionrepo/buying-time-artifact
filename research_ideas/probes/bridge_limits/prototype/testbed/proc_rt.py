"""Real-time processes for phase B, one OS process each, every one with its own RPC connections:

  watcher   records the wall-clock time at which each new block of either chain is first seen
  monitor   the independent pauser: polls every P seconds (same Monitor class as the replay)
  relayer   the honest relayer: relays deposits with k confirmations (polls every second)
  keeper    calls executeNext whenever a limiter's oldest request can execute
  attacker  holds the second relayer key: queues releases with no deposit, drains every block

Usage: python proc_rt.py <role> --world W.json --s URL --d URL --out OUT.jsonl --stop STOPFILE [role options]
Each process exits when STOPFILE exists or its time limit passes."""
import argparse
import ctypes
import json
import os
import random
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.dont_write_bytecode = True
from tb.abi import calldata  # noqa: E402
from tb.agents import Attacker, Keeper, Monitor, Relayer  # noqa: E402
from tb.rpc import Chain  # noqa: E402

try:
    ctypes.windll.winmm.timeBeginPeriod(1)  # 1 ms sleep granularity on Windows
except Exception:
    pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("role")
    ap.add_argument("--world", required=True)
    ap.add_argument("--s", required=True)
    ap.add_argument("--d", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--stop", required=True)
    ap.add_argument("--limit", type=float, default=600)
    ap.add_argument("--P", type=float, default=12)
    ap.add_argument("--g", type=float, default=0)
    ap.add_argument("--km", type=int, default=64)
    ap.add_argument("--k", type=int, default=64)
    ap.add_argument("--mode", default="burst")
    ap.add_argument("--delay", type=float, default=5)
    ap.add_argument("--pace", type=float, default=60)
    ap.add_argument("--nburst", type=int, default=20)
    ap.add_argument("--idbase", type=int, default=(1 << 255) + (1 << 40))
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--Bd", type=float, default=2)
    a = ap.parse_args()
    w = json.load(open(a.world, encoding="utf-8"))
    out = open(a.out, "w", encoding="utf-8")
    t_stop = time.time() + a.limit

    def log(rec):
        out.write(json.dumps(rec, default=str) + "\n")
        out.flush()

    def stopped():
        return os.path.exists(a.stop) or time.time() > t_stop

    log({"ev": "start", "role": a.role, "wall": time.time(), "pid": os.getpid()})
    if a.role == "watcher":
        S, D = Chain(a.s, "S"), Chain(a.d, "D")
        last = {"S": S.head(), "D": D.head()}
        log({"ev": "heads", "wall": time.time(), "S": last["S"], "D": last["D"]})
        while not stopped():
            for name, c in (("S", S), ("D", D)):
                h = c.head()
                if h > last[name]:
                    tw = time.time()
                    for n in range(last[name] + 1, h + 1):
                        b = c.block(n)
                        log({"ev": "block", "chain": name, "n": n, "wall": tw, "ts": int(b["timestamp"], 16),
                             "ntx": len(b["transactions"])})
                    last[name] = h
            time.sleep(0.005)
    elif a.role == "monitor":
        S, D = Chain(a.s, "S"), Chain(a.d, "D")
        mon = Monitor("rt", w, S, D, a.km, a.g, None, acting=True, start_block=D.head())
        log({"ev": "ready", "wall": time.time(), "start_block": mon.data["dest_scanned"], "P": a.P, "g": a.g, "km": a.km})
        n_act = 0
        t_next = time.time()
        while not stopped():
            t = time.time()
            new, alarm = mon.poll(t)
            t1 = time.time()
            acts = mon.data["actions"][n_act:]
            n_act = len(mon.data["actions"])
            if new or alarm or acts:
                log({"ev": "poll", "wall": t, "end": t1, "hd": mon.data["dest_scanned"], "new": new, "alarm": alarm,
                     "actions": acts})
            t_next += a.P
            while t_next < time.time():
                t_next += a.P
            while not stopped() and time.time() < t_next:
                time.sleep(min(0.01, max(0.0, t_next - time.time())))
        json.dump({k: v for k, v in mon.data.items() if k != "consumed"}, open(a.out + ".final.json", "w"), default=str)
    elif a.role == "relayer":
        S, D = Chain(a.s, "S"), Chain(a.d, "D")
        r = Relayer(w, S, D, a.k, check_processed=True)
        while not stopped():
            t = time.time()
            out_, h, ntx = r.scan(t)
            if ntx:
                log({"ev": "relay", "wall": t, "end": time.time(), "head_s": h, "deps": [x["dep_id"] for x in out_]})
            time.sleep(1.0)
    elif a.role == "keeper":
        D = Chain(a.d, "D")
        k = Keeper(w, D)
        last = D.head()
        while not stopped():
            h = D.head()
            if h > last:
                last = h
                b = D.block(h)
                ts = int(b["timestamp"], 16)
                plan = k.plan()
                go = [lim for lim, te in plan.items() if te is not None and te <= ts + a.Bd]
                if go:
                    k.execute(go)
                    log({"ev": "drain", "wall": time.time(), "head": h, "lims": go})
            time.sleep(0.02)
    elif a.role == "attacker":
        D = Chain(a.d, "D")
        att = Attacker(w, D, w["limiters"], a.idbase)
        burst, paced = {}, {}
        for L in w["limiters"]:
            cap = min(c for c, _ in L["buckets"])
            refill = min(r for _, r in L["buckets"])
            burst[L["limiter"]] = [cap // 10] * a.nburst
            paced[L["limiter"]] = [int(0.5 * refill * a.pace)]
        time.sleep(a.delay)
        t = time.time()
        n = att.relay(t, burst if a.mode == "burst" else paced, drain=True, tag=a.mode)
        log({"ev": "inject", "wall": t, "end": time.time(), "n": n, "head": D.head()})
        last = D.head()
        next_pace = t + a.pace
        while not stopped():
            h = D.head()
            if h > last:
                last = h
                res = D.batch([("eth_call", [{"to": L["limiter"], "data": calldata("paused()")}, "latest"]) for L in w["limiters"]])
                unp = [L["limiter"] for L, r in zip(w["limiters"], res) if int(r, 16) == 0]
                if not unp:
                    log({"ev": "all_paused", "wall": time.time(), "head": h})
                    break
                tw = time.time()
                att.drain(tw, unp)
                log({"ev": "drain", "wall": tw, "head": h, "lims": unp})
                if a.mode == "paced" and time.time() >= next_pace:
                    tw = time.time()
                    att.relay(tw, {k: v for k, v in paced.items() if k in unp}, drain=True, tag="paced")
                    log({"ev": "paced", "wall": tw, "head": h})
                    next_pace += a.pace
            time.sleep(0.005)
        json.dump(att.data, open(a.out + ".final.json", "w"), default=str)
    log({"ev": "exit", "wall": time.time()})


if __name__ == "__main__":
    main()
