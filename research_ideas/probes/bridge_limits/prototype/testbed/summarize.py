"""Summarize the end-to-end testbed runs into results/testbed.json and results/testbed.md (2026-10-16).

Inputs (logs/): phase A runs written by run_a.py (a failed bridge's legitimate releases replayed on two
local anvil chains in compressed simulated time, with unbacked requests injected every few days and at
the failure time) and phase B runs written by run_b.py (the last days replayed, then the watcher,
monitor, relayer, keeper and the party holding the second relayer key as separate OS processes on the
wall clock).

Limiters in every run: L0 (OutflowLimiter, no hold), L10 (OutflowLimiter, 10-minute hold), T0
(TunedLimiter, two buckets in series). The monitor matches every release request to a source deposit
with k_m confirmations, polls every P seconds, and on an unmatched request sends pause and cancels the
unmatched queued requests.  Reported per configuration: detection and pause latency (from the block
that holds the first unbacked request), the value released before the pause per limiter, and the
monitor's alarms on legitimate requests (false alarms).
"""
import glob
import json
import os
import statistics

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "..", "results")


def q(xs, p):
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    k = (len(xs) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def stats(xs):
    xs = [x for x in xs if x is not None]
    return {"n": len(xs), "median": q(xs, 0.5), "max": max(xs) if xs else None, "min": min(xs) if xs else None}


def phase_a(path):
    d = json.load(open(path, encoding="utf-8"))
    out = {"run": d["run"], "fid": d["fid"], "Bd": d["Bd"], "Bs": d["Bs"], "k": d["k"], "n_releases": d["n_releases"],
           "fits": d["fits"], "legit": {}, "monitors": {}, "episodes": {}}
    for name, L in d["legit"].items():
        a = L["all"]
        out["legit"][name] = {"n_requests": L["n_requests"], "n_executed": L["n_executed"], "value_usd": L["value_usd"],
                              "share_value_delayed": a["share_value_delayed"], "wait_p50_s": a["wait_p50_s"],
                              "wait_p99_s": a["wait_p99_s"], "excess_wait_max_h": a["excess_wait_max_h"]}
    for name, m in d["shadow"].items():
        out["monitors"][name] = {k: m.get(k) for k in ("cfg", "n_polls", "n_matched", "n_alarms", "alarms_by_reason",
                                                         "n_alarmed_deposits", "open_at_end", "reorg_targets",
                                                         "reorg_targets_alarmed", "reorg_targets_resent",
                                                         "alarms_on_resent_targets", "alarms_on_dropped_targets",
                                                         "alarms_on_other_deposits")
                                 if k in m}
        if m.get("alarm_delay_after_reorg_s"):
            out["monitors"][name]["alarm_delay_after_reorg_s"] = stats(m["alarm_delay_after_reorg_s"])
    groups = {}
    for e in d.get("episodes", []):
        key = f"{e['mode']} P={e['P']:g}"
        groups.setdefault(key, []).append(e)
    for key, eps in sorted(groups.items()):
        g = {"n": len(eps)}
        for lim in ("L0", "L10", "T0"):
            xs = [e["limiters"][lim] for e in eps if lim in e["limiters"]]
            if not xs:
                continue
            g[lim] = {"detect_s": stats([x.get("detect_s") for x in xs]),
                      "pause_s": stats([x.get("pause_s") for x in xs]),
                      "pause_blocks": stats([x.get("pause_blocks") for x in xs]),
                      "released_before_pause_usd": stats([x.get("released_before_pause_usd") for x in xs]),
                      "requested_usd": stats([x.get("requested_usd") for x in xs]),
                      "available_at_inj_usd": stats([x.get("available_at_inj_usd") for x in xs]),
                      "share_released": stats([x["released_before_pause_usd"] / x["requested_usd"]
                                               for x in xs if x.get("requested_usd")]),
                      "n_cancel_legit": sum(x.get("n_cancel_legit", 0) for x in xs),
                      "pause_gas": stats([x.get("pause_gas") for x in xs]),
                      "cancel_gas": stats([c for x in xs for c in (x.get("cancel_gas") or [])])}
        g["false_alarms_during_episodes"] = sum(1 for e in eps for r in e.get("alarm_reasons", []) if r != "missing")
        out["episodes"][key] = g
    if d.get("reorg_events") is not None:
        ev = [e for e in d["reorg_events"] if isinstance(e, dict)]
        out["reorg_events"] = {"n": len(ev), "variant": d["cfg"].get("reorg", {}).get("variant"),
                               "n_dropped_deposits": sum(len(e.get("dropped", [])) for e in ev),
                               "n_relied_upon": sum(len(e.get("targets", [])) for e in ev),
                               "n_resent": sum(len(e.get("resent", [])) for e in ev),
                               "depth": stats([e.get("depth") for e in ev])}
    out["wall_s"] = d.get("wall_s")
    return out


def phase_b(path):
    d = json.load(open(path, encoding="utf-8"))
    eps = [e for e in d["episodes"] if "limiters" in e]
    out = {"tag": d["tag"], "Bd": d["Bd"], "n_episodes": len(d["episodes"]), "n_ok": len(eps),
           "errors": [e.get("error") for e in d["episodes"] if "error" in e], "groups": {}}
    groups = {}
    for e in eps:
        groups.setdefault(f"{e['mode']} P={e['P']:g}", []).append(e)
    for key, es in sorted(groups.items()):
        g = {"n": len(es)}
        for lim in ("L0", "L10", "T0"):
            xs = [e["limiters"][lim] for e in es if lim in e["limiters"]]
            if not xs:
                continue
            g[lim] = {"detect_s": stats([x.get("detect_s") for x in xs]),
                      "pause_s": stats([x.get("pause_s") for x in xs]),
                      "pause_blocks": stats([x.get("pause_blocks") for x in xs]),
                      "released_before_pause_usd": stats([x.get("released_before_pause_usd") for x in xs]),
                      "legit_alarms": sum(x.get("legit_alarms", 0) for x in xs)}
        out["groups"][key] = g
    return out


def main():
    logs = os.path.join(HERE, "logs")
    res = {"phase_a": {}, "phase_b": {}}
    for p in sorted(glob.glob(os.path.join(logs, "*.json"))):
        b = os.path.basename(p)[:-5]
        if b.startswith("rt_") and not b.endswith("_world"):
            res["phase_b"][b] = phase_b(p)
        elif not b.startswith(("rt_", "forged_")) and "quick" not in b:  # forged_*: summarize_forged.py
            res["phase_a"][b] = phase_a(p)
    json.dump(res, open(os.path.join(OUT, "testbed.json"), "w", encoding="utf-8"), indent=1, default=str)
    L = ["# End-to-end testbed (generated by prototype/testbed/summarize.py)", ""]
    for name, r in res["phase_a"].items():
        L += [f"## Phase A: {name} ({r['fid']}, destination block {r['Bd']} s, relayer waits k = {r['k']})", ""]
        L.append("Legitimate requests: " + "; ".join(
            f"{k}: {v['n_executed']}/{v['n_requests']} executed, {100 * v['share_value_delayed']:.2f}% of value delayed, "
            f"wait p50 {v['wait_p50_s']:.0f} s" for k, v in r["legit"].items()))
        L.append("")
        L.append("Monitors on the legitimate stream: " + "; ".join(
            f"{k}: {v.get('n_alarms')} alarms on {v.get('n_matched')} matched" for k, v in r["monitors"].items()))
        L.append("")
        if r.get("reorg_events"):
            re_ = r["reorg_events"]
            L.append(f"Reorganizations (variant {re_['variant']}): {re_['n']} events, {re_['n_relied_upon']} relayed deposits "
                     f"dropped, {re_['n_resent']} sent again. Per monitor: " + "; ".join(
                         f"{k}: {v.get('reorg_targets_alarmed')} of {v.get('reorg_targets')} relied-upon deposits alarmed "
                         f"({v.get('alarms_on_dropped_targets')} never sent again, {v.get('alarms_on_resent_targets')} sent again), "
                         f"{v.get('alarms_on_other_deposits')} alarms on other deposits"
                         for k, v in r["monitors"].items()))
            L.append("")
        if r["episodes"]:
            L += ["| injection | n | detect s (med/max) | pause s (med/max) | pause blocks (max) | released before pause, H=0 (med/max USD) | H=10 min | tuned |",
                  "|---|---|---|---|---|---|---|---|"]
            for key, g in r["episodes"].items():
                a, b, t = g.get("L0"), g.get("L10"), g.get("T0")
                L.append(f"| {key} | {g['n']} | {a['detect_s']['median']:.1f} / {a['detect_s']['max']:.1f} | "
                         f"{a['pause_s']['median']:.1f} / {a['pause_s']['max']:.1f} | {a['pause_blocks']['max']} | "
                         f"{a['released_before_pause_usd']['median']:,.0f} / {a['released_before_pause_usd']['max']:,.0f} | "
                         f"{b['released_before_pause_usd']['median']:,.0f} / {b['released_before_pause_usd']['max']:,.0f} | "
                         f"{t['released_before_pause_usd']['median']:,.0f} / {t['released_before_pause_usd']['max']:,.0f} |")
            L.append("")
    for name, r in res["phase_b"].items():
        L += [f"## Phase B (wall clock): {name}, destination block {r['Bd']} s; {r['n_ok']} of {r['n_episodes']} episodes complete", ""]
        if r["errors"]:
            L.append(f"Errors: {r['errors']}")
            L.append("")
        L += ["| injection | n | detect s (med/max) | pause s (med/max) | pause blocks (max) | released before pause H=0 (med USD) | H=10 min | legit alarms |",
              "|---|---|---|---|---|---|---|---|"]
        for key, g in r["groups"].items():
            a, b = g.get("L0"), g.get("L10")
            L.append(f"| {key} | {g['n']} | {a['detect_s']['median']:.1f} / {a['detect_s']['max']:.1f} | "
                     f"{a['pause_s']['median']:.1f} / {a['pause_s']['max']:.1f} | {a['pause_blocks']['max']} | "
                     f"{a['released_before_pause_usd']['median']:,.0f} | {b['released_before_pause_usd']['median']:,.0f} | "
                     f"{a['legit_alarms'] + b['legit_alarms']} |")
        L.append("")
    open(os.path.join(OUT, "testbed.md"), "w", encoding="utf-8").write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
