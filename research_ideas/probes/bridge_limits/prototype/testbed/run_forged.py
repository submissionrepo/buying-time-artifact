"""Runs: forged deposits (an EVENT failure) against two acting monitors, 2026-10-16.

A failure episode here does not use the relayer key. The party calls the source contract's flawed path
(SourceDeposit.depositUnchecked), which records and announces a deposit without moving value; the honest
relayer relays each forged deposit to every limiter once it has k confirmations. At each injection point
two episodes run from the same snapshot: one with a monitor that matches each release request to the
recorded deposit (id, amount, recipient, depth), and one that also requires the deposit's transaction to
have moved the amount into the source escrow (Monitor.value_check). Everything else is as in run_a.py.

Usage: python run_forged.py [--fid E25] [--every-days 15] [--ports 18711 18712]
Writes logs/forged_<fid>.json and .log."""
import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.dont_write_bytecode = True
from tb.replay import Replay, DAY  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fid", default="E25")
    ap.add_argument("--Bd", type=int, default=12)
    ap.add_argument("--k", type=int, default=64)
    ap.add_argument("--P", type=float, default=12.0)
    ap.add_argument("--every-days", type=float, default=15.0)
    ap.add_argument("--reps-last", type=int, default=3)
    ap.add_argument("--ports", nargs=2, type=int, default=[18711, 18712])
    ap.add_argument("--seed", type=int, default=3)
    a = ap.parse_args()
    tag = f"forged_{a.fid}_d{a.Bd}_k{a.k}"
    logf = open(os.path.join(HERE, "logs", tag + ".log"), "w", encoding="utf-8")

    def log(msg):
        line = time.strftime("%H:%M:%S ") + msg
        print(line, flush=True)
        logf.write(line + "\n")
        logf.flush()

    w0 = time.time()
    rp = Replay(a.fid, a.Bd, a.k, [], a.ports, tag, os.path.join(HERE, "logs"), seed=a.seed, log=log)
    episodes = []
    try:
        rp.setup()
        t0, t_end = float(rp.T[0]), rp.t_fail
        pts, x = [], t0 + a.every_days * DAY
        while x < t_end - 2 * DAY:
            pts.append(x)
            x += a.every_days * DAY
        pts.append(t_end)
        idx = 0
        for j, tp in enumerate(pts):
            rp.sim.run(tp)
            rp.sim.settle_pools()
            reps = a.reps_last if j == len(pts) - 1 else 1
            for rep in range(reps):
                phi = rp.rng.uniform(0, a.P)
                t_inj = rp.sim.now + 1.0 + rp.rng.uniform(0, a.Bd)
                for vc in (False, True):
                    idx += 1
                    r = rp.episode(idx, "forged", a.P, 0, a.k, phi, t_inj, T_max=1800.0, value_check=vc)
                    r.update(point=j, rep=rep, at_failure_time=j == len(pts) - 1)
                    episodes.append(r)
                    lim = {k: (v.get("released_before_pause_usd"), v.get("detect_s"), v.get("pause_s")) for k, v in r["limiters"].items()}
                    log(f"[{tag}] point {j + 1}/{len(pts)} rep {rep} value_check={vc}: alarms {r['n_alarms']} {r['alarm_reasons']} {lim}")
        out = {"tag": tag, "fid": a.fid, "Bd": a.Bd, "k": a.k, "P": a.P, "n_releases": len(rp.rows), "points": pts,
               "episodes": episodes, "wall_s": time.time() - w0}
        json.dump(out, open(os.path.join(HERE, "logs", tag + ".json"), "w", encoding="utf-8"), indent=1, default=str)
        log(f"[{tag}] wrote logs/{tag}.json; wall {time.time() - w0:.0f}s")
    finally:
        rp.close()


if __name__ == "__main__":
    main()
