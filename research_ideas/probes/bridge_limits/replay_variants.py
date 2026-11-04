"""Replay variants: placement with control, the response time as a variable, weightings, the best bucket
and K buckets (2026-10-16).

1. Placement with control.  A release-point limit sees classes S, V and D only if the party
   behind the failure cannot change or sidestep it.  Using results/incident_coding.csv:
   - as governed: V failures whose taken keys also controlled the release contract, and D
     failures whose flaw also reached a limit in the release contract, count as unseen;
   - control separated: only the second exclusion applies (the limit's parameters sit with
     a party the keys do not control);
   - pessimistic: 'unknown' codings count as unseen too.
2. Response times as a variable.  Variants for every rule: D times k (k = 2, 5, 10); D
   infinite where the failure was detected through its own outflow (third-party alert,
   user report or failed withdrawal, escrow shortfall); D infinite where no independent
   pause existed (pause_holder no_pause_function or controlled_by_failing_party); D equal to
   the first third-party alert where one was recorded and earlier; an independent alarm on
   releases that match no deposit, pausing within ten minutes (only where an independent
   pause existed or the design adds one); the 9 untimed failures included with D infinite.
   The break-even factor k at which the release-point bucket's share falls below one half.
3. Weightings: by value released (gross), by failure, and by the value finally lost (net of
   recovered_usd).
4. The best bucket for a distribution of response times: among buckets that delay no
   legitimate transfer of the benchmark traffic (Wormhole, nine chains, last 12 months), the
   one minimizing E_G[min{W, b + r D}] over the empirical response times; it supports the
   least concave majorant at the mean of D over the responses that come before b + r D
   reaches W.  Compared with buckets matched at the median response time and at 6 h.
5. K buckets: the minimum of the buckets that support the majorant at 1 h, 6 h, 24 h and
   7 d, against the majorant and the envelope over 1 h to 30 days.
Outputs: results/replay_variants.json, results/replay_variants.md.
"""
from __future__ import annotations

import csv
import json
import math
import os
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "wormhole"))
import replay_incidents as ri  # noqa: E402
from analysis_core import hull_value, upper_concave_hull  # noqa: E402
from pooling_clean import PERIODS, load  # noqa: E402
from replay_matched import envelope_fn, pooled  # noqa: E402

INF = math.inf
ALARM_H = 10 / 60
OUTFLOW_DETECTED = {"third_party_alert", "user_report_or_failed_withdrawal", "escrow_or_balance_shortfall"}


def keys_held():
    """Failures whose release point could not host a contract limit (custody held directly by keys, or a
    chain without programmable custody), as the blind coder read the sources (coding/blind_coding.csv,
    release_point_contract = no). There a release-point limit means moving custody first; today only a
    limit in the signers' software is possible, which sees what the verifier side sees."""
    p = os.path.join(HERE, "coding", "blind_coding.csv")
    if not os.path.exists(p):
        return set()
    return {r["id"] for r in csv.DictReader(open(p, encoding="utf-8")) if r["release_point_contract"].strip().lower() == "no"}


def load_all():
    inc = {r["id"]: r for r in csv.DictReader(open(os.path.join(HERE, "results", "incidents.csv"), encoding="utf-8"))
           if r["in_bridge_set"] == "yes"}
    cod = {r["id"]: r for r in csv.DictReader(open(os.path.join(HERE, "results", "incident_coding.csv"), encoding="utf-8"))}
    held = keys_held()
    ev = []
    for i, r in inc.items():
        c = cod.get(i, {})
        D = r["response_delay_s"]
        alert = r.get("first_alert_lag_s") or ""
        ev.append({
            "id": i, "A": float(r["amount_usd"]), "cls": (r["failure_class"] or "O")[:1],
            "D_h": float(D) / 3600 if D else INF, "timed": bool(D),
            "alert_h": float(alert) / 3600 if alert else None,
            "keys_ctrl": c.get("keys_controlled_release_contract", "n.a."),
            "flaw_reach": c.get("same_flaw_reaches_release_limit", "n.a."),
            "detect": c.get("detection_channel", "unknown"),
            "pause": c.get("pause_holder", "unknown"),
            "recovered": float(c.get("recovered_usd") or 0.0),
            "cls_recoded": (c.get("class_recoded") or r["failure_class"] or "O")[:1],
            "n_chains": ri.chains_released().get(i, 1),
            "keys_held": i in held,
        })
    return ev


def seen_release(e, mode, cls_key="cls"):
    c = e[cls_key]
    if c not in ("S", "V", "D"):
        return False
    if c == "D" and (e["flaw_reach"] == "yes" or (mode == "pessimistic" and e["flaw_reach"] == "unknown")):
        return False
    if c == "V" and mode in ("governed", "pessimistic"):
        if e["keys_ctrl"] == "yes" or (mode == "pessimistic" and e["keys_ctrl"] == "unknown"):
            return False
    return True


def contained(events, loss, weight="value"):
    if weight == "value":
        w = lambda e: e["A"]
    elif weight == "net":
        w = lambda e: max(0.0, e["A"] - e["recovered"])
    else:
        w = lambda e: 1.0
    tot = sum(w(e) for e in events)
    if weight == "event":
        return statistics.mean(1 - loss(e) / e["A"] for e in events)
    # by value: weight each failure's contained fraction by its weight
    return sum(w(e) * (1 - loss(e) / e["A"]) for e in events) / tot if tot else math.nan


def make_rules(E_full):
    return {
        "bucket 1M/h": lambda D: 1e6 + 1e6 * D,
        "hold 24 h": lambda D: 0.0 if D <= 24 else INF,
        "matched benchmark": lambda D: E_full(math.ceil(D)) if math.isfinite(D) else INF,
    }


def main():
    ev = load_all()
    timed = [e for e in ev if e["timed"]]
    full = load("series_full_hourly.csv")
    start = PERIODS["12 months"]
    E_full = envelope_fn(pooled(full, start))
    rules = make_rules(E_full)
    res = {"n_events": len(ev), "n_timed": len(timed), "placement": {}, "response": {}, "weights": {}}

    def loss_fn(rule, mode, Dmap=lambda e: e["D_h"], placement="release", cls_key="cls"):
        f = rules[rule]

        def loss(e):
            if placement == "verifier" or (placement == "release_contract" and e["keys_held"]):
                # class S whole, and the redeemed leg of an unbacked mint redeemed through
                # the bridge (replay_incidents.verifier_share)
                s = ri.verifier_share({**e, "cls": e[cls_key]})
                if s == 0.0:
                    return e["A"]
                D = Dmap(e)
                if not math.isfinite(D):
                    return e["A"]
                return e["A"] * (1 - s) + min(e["A"] * s, e["n_chains"] * f(D))
            seen = seen_release(e, mode, cls_key)
            if not seen:
                return e["A"]
            D = Dmap(e)
            if not math.isfinite(D):
                return e["A"]
            # one limit per release contract (Corollary 4.2); a hold's 0 or infinity is unchanged
            return min(e["A"], e["n_chains"] * f(D))
        return loss

    # 1. placement with control, by value, timed failures
    for rule in rules:
        res["placement"][rule] = {
            "verifier": contained(timed, loss_fn(rule, "separated", placement="verifier")),
            "release_separated": contained(timed, loss_fn(rule, "separated")),
            "release_governed": contained(timed, loss_fn(rule, "governed")),
            "release_pessimistic": contained(timed, loss_fn(rule, "pessimistic")),
            "release_separated_recoded": contained(timed, loss_fn(rule, "separated", cls_key="cls_recoded")),
            # where custody was held directly by keys, only the signers' software can host a limit
            "release_contract_only": contained(timed, loss_fn(rule, "separated", placement="release_contract")),
        }
    vshare = lambda pred: sum(e["A"] for e in timed if pred(e)) / sum(e["A"] for e in timed)
    res["shares"] = {
        "V_keys_ctrl_yes_value": vshare(lambda e: e["cls"] == "V" and e["keys_ctrl"] == "yes"),
        "D_flaw_reach_yes_value": vshare(lambda e: e["cls"] == "D" and e["flaw_reach"] == "yes"),
        "n_V_keys_ctrl_yes": sum(e["cls"] == "V" and e["keys_ctrl"] == "yes" for e in ev),
        "n_V": sum(e["cls"] == "V" for e in ev),
        "n_D_flaw_reach_yes": sum(e["cls"] == "D" and e["flaw_reach"] == "yes" for e in ev),
        "n_D": sum(e["cls"] == "D" for e in ev),
        "no_independent_pause_value": vshare(lambda e: e["pause"] in ("no_pause_function", "controlled_by_failing_party")),
        "outflow_detected_value": vshare(lambda e: e["detect"] in OUTFLOW_DETECTED),
        "n_outflow_detected": sum(e["detect"] in OUTFLOW_DETECTED for e in timed),
        "recovered_share_timed": sum(e["recovered"] for e in timed) / sum(e["A"] for e in timed),
    }

    # 2. response times as a variable (release point, control separated, the recommended design)
    variants = {
        "base": lambda e: e["D_h"],
        "x2": lambda e: 2 * e["D_h"],
        "x5": lambda e: 5 * e["D_h"],
        "x10": lambda e: 10 * e["D_h"],
        "outflow_detected_never": lambda e: INF if e["detect"] in OUTFLOW_DETECTED else e["D_h"],
        "no_independent_pause_never": lambda e: INF if e["pause"] in ("no_pause_function", "controlled_by_failing_party") else e["D_h"],
        "alert_time": lambda e: min(e["D_h"], e["alert_h"]) if e["alert_h"] is not None else e["D_h"],
        "alarm_10min": lambda e: min(e["D_h"], ALARM_H),
        "alarm_1h": lambda e: min(e["D_h"], 1.0),
    }
    for rule in rules:
        res["response"][rule] = {k: contained(timed, loss_fn(rule, "separated", Dmap=f)) for k, f in variants.items()}
        res["response"][rule]["all57_untimed_never"] = contained(ev, loss_fn(rule, "separated"))
    # break-even factor for the bucket at the release point
    be = None
    for k in [1 + 0.25 * j for j in range(0, 400)]:
        if contained(timed, loss_fn("bucket 1M/h", "separated", Dmap=lambda e, k=k: k * e["D_h"])) < 0.5:
            be = k
            break
    res["breakeven_factor_bucket"] = be
    be_m = None
    for k in [1 + 0.25 * j for j in range(0, 400)]:
        if contained(timed, loss_fn("matched benchmark", "separated", Dmap=lambda e, k=k: k * e["D_h"])) < 0.5:
            be_m = k
            break
    res["breakeven_factor_matched"] = be_m

    # 3. weightings
    for rule in rules:
        res["weights"][rule] = {w: contained(timed, loss_fn(rule, "separated"), weight=w) for w in ("value", "event", "net")}

    # 4. best bucket for the distribution of response times (benchmark envelope, last 12 months)
    Ds = sorted(e["D_h"] for e in timed)
    grid = list(range(1, 24 * 80 + 1))
    pts = [(float(u), E_full(u)) for u in grid]
    hull = upper_concave_hull(pts)
    lines = []
    for (x1, y1), (x2, y2) in zip(hull, hull[1:]):
        r = (y2 - y1) / (x2 - x1)
        lines.append((y1 - r * x1, r, x1, x2))
    best = {}
    for W in (5e8, 1e9, 2e9):
        def exp_loss(b, r):
            return statistics.mean(min(W, b + r * D) for D in Ds)
        cand = [(exp_loss(b, r), b, r, x1, x2) for (b, r, x1, x2) in lines if b >= 0]
        el, b, r, x1, x2 = min(cand)
        med = statistics.median(Ds)
        def line_at(D):
            for (bb, rr, a1, a2) in lines:
                if a1 <= D <= a2:
                    return bb, rr
            return lines[-1][0], lines[-1][1]
        bm, rm = line_at(med)
        b6, r6 = line_at(6.0)
        crossing = (W - b) / r if r > 0 else INF
        best[f"{W:.0e}"] = {"expected_loss": el, "support_from_h": x1, "support_to_h": x2,
                            "mean_D_below_crossing_h": statistics.mean([D for D in Ds if b + r * D < W]) if any(b + r * D < W for D in Ds) else None,
                            "expected_loss_median_matched": exp_loss(bm, rm), "expected_loss_6h_matched": exp_loss(b6, r6),
                            "crossing_h": crossing}
    res["best_bucket"] = {"median_D_h": statistics.median(Ds), "mean_D_h": statistics.mean(Ds), "by_W": best}

    # 5. K buckets supporting the majorant at 1 h, 6 h, 24 h, 7 d
    def support(D):
        for (b, r, x1, x2) in lines:
            if x1 <= D <= x2:
                return b, r
        return lines[-1][0], lines[-1][1]
    Ks = [support(D) for D in (1, 6, 24, 168)]
    worst_hull = max(min(b + r * u for b, r in Ks) / hull_value(hull, float(u)) for u in range(1, 24 * 30 + 1))
    worst_env = max(min(b + r * u for b, r in Ks) / E_full(u) for u in range(1, 24 * 30 + 1))
    res["k_buckets"] = {"anchors_h": [1, 6, 24, 168], "max_ratio_to_majorant": worst_hull, "max_ratio_to_envelope": worst_env}

    with open(os.path.join(HERE, "results", "replay_variants.json"), "w", encoding="utf-8") as fh:
        json.dump(res, fh, indent=1, default=str)
    nl = chr(10)
    out = ["# Replay variants (generated)", "", "Generated by `replay_variants.py`; see its docstring.", "",
           "## Placement with control (share of value contained, timed failures)", "",
           "| rule | verifier side | release, control separated | release, as governed | release, pessimistic | release, separated, recoded classes |", "|---|---|---|---|---|---|"]
    for rule, v in res["placement"].items():
        out.append(f"| {rule} | {v['verifier']:.3f} | {v['release_separated']:.3f} | {v['release_governed']:.3f} | {v['release_pessimistic']:.3f} | {v['release_separated_recoded']:.3f} |")
    out += ["", "Shares: " + json.dumps({k: (round(v, 3) if isinstance(v, float) else v) for k, v in res["shares"].items()}), "",
            "## Response times as a variable (release point, control separated)", "",
            "| rule | " + " | ".join(variants.keys()) + " | all 57, untimed never |", "|---|" + "---|" * (len(variants) + 1)]
    for rule, v in res["response"].items():
        out.append(f"| {rule} | " + " | ".join(f"{v[k]:.3f}" for k in variants) + f" | {v['all57_untimed_never']:.3f} |")
    out += ["", f"Break-even factor (release-point share below one half): bucket {res['breakeven_factor_bucket']}, matched benchmark {res['breakeven_factor_matched']}.", "",
            "## Weightings (release point, control separated)", "", "| rule | by value | by failure | by value finally lost |", "|---|---|---|---|"]
    for rule, v in res["weights"].items():
        out.append(f"| {rule} | {v['value']:.3f} | {v['event']:.3f} | {v['net']:.3f} |")
    out += ["", "## Best bucket for the distribution of response times (benchmark traffic)", "",
            f"Median response {res['best_bucket']['median_D_h']:.2f} h; mean {res['best_bucket']['mean_D_h']:.1f} h.", ""]
    for W, v in best.items():
        out.append(f"- W = {W}: best expected loss {v['expected_loss']/1e6:.1f}M (supporting segment {v['support_from_h']:.0f} to {v['support_to_h']:.0f} h; "
                   f"mean of D below the crossing {v['mean_D_below_crossing_h']}); matched at the median: {v['expected_loss_median_matched']/1e6:.1f}M; matched at 6 h: {v['expected_loss_6h_matched']/1e6:.1f}M")
    out += ["", f"K buckets at 1 h, 6 h, 24 h, 7 d: at most {res['k_buckets']['max_ratio_to_majorant']:.3f} times the majorant and {res['k_buckets']['max_ratio_to_envelope']:.3f} times the envelope over 1 h to 30 days."]
    with open(os.path.join(HERE, "results", "replay_variants.md"), "w", encoding="utf-8") as fh:
        fh.write(nl.join(out) + nl)
    print(nl.join(out))


if __name__ == "__main__":
    main()
