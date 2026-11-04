"""Phase A runs: compressed replays of a failed bridge's release history on two local anvil nodes.

Usage: python run_a.py <run name> [--ports 18701 18702] [--quick N]
Writes logs/<run>.json."""
import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.dont_write_bytecode = True
from tb.replay import Replay, DAY  # noqa: E402

SHADOW_MAIN = [dict(name="km64_g0", k_m=64, g=0, P=12), dict(name="km12_g0", k_m=12, g=0, P=12),
               dict(name="km2_g0", k_m=2, g=0, P=12)]


def shadow_k(k):
    """Monitors for a relayer that waits k < 64 blocks: k_m = k, k_m = 1 < k, and the finalized depth
    k_m = 64 with no grace and with graces just below and above the (64 - k) * 12 s it needs."""
    thr = (64 - k) * 12
    return [dict(name=f"km{k}_g0", k_m=k, g=0, P=12), dict(name="km1_g0", k_m=1, g=0, P=12),
            dict(name="km64_g0", k_m=64, g=0, P=12), dict(name=f"km64_g{thr - 24}", k_m=64, g=thr - 24, P=12),
            dict(name=f"km64_g{thr + 36}", k_m=64, g=thr + 36, P=12)]


SHADOW_REORG = [dict(name="km2_g0", k_m=2, g=0, P=12), dict(name="km1_g0", k_m=1, g=0, P=12),
                dict(name="km2_g30", k_m=2, g=30, P=12), dict(name="km2_g30_recheck64", k_m=2, g=30, P=12, kf=64),
                dict(name="km64_g900", k_m=64, g=900, P=12)]

COMBOS = [(mode, P, 0) for mode in ("burst", "paced") for P in (2, 12, 60)]

RUNS = {
    "E25_d2_k64": dict(fid="E25", Bd=2, k=64, shadow=SHADOW_MAIN, inject=dict(every_days=5, reps_last=10)),
    "E25_d12_k64": dict(fid="E25", Bd=12, k=64, shadow=SHADOW_MAIN, inject=dict(every_days=5, reps_last=10)),
    "E25_d2_k12": dict(fid="E25", Bd=2, k=12, shadow=shadow_k(12)),
    "E25_d2_k2": dict(fid="E25", Bd=2, k=2, shadow=shadow_k(2)),
    "E25_d2_k2_reorg_a": dict(fid="E25", Bd=2, k=2, shadow=SHADOW_REORG,
                              reorg=dict(variant="a", every=40, delay_range=[0, 120], seed=11)),
    "E25_d2_k2_reorg_b": dict(fid="E25", Bd=2, k=2, shadow=SHADOW_REORG,
                              reorg=dict(variant="b", every=40, delay_range=[0, 120], seed=11)),
    "E15_d2_k64": dict(fid="E15", Bd=2, k=64, shadow=SHADOW_MAIN[:1], inject=dict(every_days=15, reps_last=5)),
    "E15_d12_k64": dict(fid="E15", Bd=12, k=64, shadow=SHADOW_MAIN[:1], inject=dict(every_days=15, reps_last=5)),
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run")
    ap.add_argument("--ports", nargs=2, type=int, default=[18701, 18702])
    ap.add_argument("--quick", type=int, default=0, help="replay only the first N releases (smoke test)")
    ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args()
    cfg = RUNS[a.run]
    tag = a.run + (f"_quick{a.quick}" if a.quick else "")
    logf = open(os.path.join(HERE, "logs", tag + ".log"), "w", encoding="utf-8")

    def log(msg):
        line = time.strftime("%H:%M:%S ") + msg
        print(line, flush=True)
        logf.write(line + "\n")
        logf.flush()

    w0 = time.time()
    rp = Replay(cfg["fid"], cfg["Bd"], cfg["k"], cfg["shadow"], a.ports, tag, os.path.join(HERE, "logs"), seed=a.seed,
                reorg=cfg.get("reorg"), log=log)
    try:
        rp.setup()
        if a.quick:
            # keep the first N deposits only
            keep = set(range(a.quick))
            rp.sim.q = [e for e in rp.sim.q if not (e[2] == "user" and e[4][0] not in keep)]
            import heapq
            heapq.heapify(rp.sim.q)
            rp.sim.queued = {(e[2], e[3], round(e[0], 6), e[4]) for e in rp.sim.q}
            t_end = float(rp.T[a.quick - 1]) + 2 * DAY
        else:
            t_end = rp.t_fail
        episodes = []
        if cfg.get("inject"):
            t0 = float(rp.T[0])
            step = cfg["inject"]["every_days"] * DAY
            pts = []
            x = t0 + step
            while x < t_end - 2 * DAY:
                pts.append(x)
                x += step
            pts.append(t_end)
            if a.quick:
                pts = pts[-2:]
            episodes = rp.run_injections(pts, COMBOS, reps_last=cfg["inject"]["reps_last"] if not a.quick else 1)
        rp.sim.run(t_end + 30 * DAY)
        log(f"[{tag}] replay done; wall {time.time() - w0:.0f}s; S blocks {rp.sim.st['S']['n_blocks']} "
            f"(empty {rp.sim.st['S']['n_empty']}), D blocks {rp.sim.st['D']['n_blocks']}")
        reorg_events = rp.sim.agents["reorger"].data["events"] if cfg.get("reorg") else None
        out = {"run": a.run, "tag": tag, "cfg": {k: v for k, v in cfg.items()}, "fid": cfg["fid"], "Bd": cfg["Bd"], "Bs": 12,
               "k": cfg["k"], "t_fail": rp.t_fail, "t_first": float(rp.T[0]), "n_releases": len(rp.rows),
               "counts": rp.counts, "fits": rp.fits, "world": {k: v for k, v in rp.w.items() if k != "acc"},
               "legit": rp.legit_stats(), "shadow": rp.shadow_stats(reorg_events), "episodes": episodes,
               "reorg_events": reorg_events,
               "sim": {"S_blocks": rp.sim.st["S"]["n_blocks"], "S_empty": rp.sim.st["S"]["n_empty"],
                       "D_blocks": rp.sim.st["D"]["n_blocks"], "S_head": rp.sim.st["S"]["head"], "D_head": rp.sim.st["D"]["head"],
                       "relays": rp.sim.agents["relayer"].r.data["n_relays"], "drains": rp.sim.agents["keeper"].k.data["n_drains"]},
               "wall_s": time.time() - w0}
        json.dump(out, open(os.path.join(HERE, "logs", tag + ".json"), "w", encoding="utf-8"), indent=1, default=str)
        log(f"[{tag}] wrote logs/{tag}.json; wall {time.time() - w0:.0f}s")
    finally:
        rp.close()


if __name__ == "__main__":
    main()
