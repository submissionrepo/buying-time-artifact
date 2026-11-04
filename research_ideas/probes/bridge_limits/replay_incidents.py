"""Counterfactual replay of bridge outflow events under rule families (2026-10-16).

Input: results/incidents.csv with at least the columns
  id, name, date, amount_usd, failure_class (V, D, S, O), release_side,
  outflow_duration_s, detection_lag_s, pause_lag_s
(written by the incident pipeline in incidents/).

For event i with amount A_i and response delay D_i (pause lag if present, else
detection lag), the counterfactual loss under a rule with containment curve beta is
  L_i = min(A_i, beta(D_i))                      if the rule's placement covers the class,
  L_i = A_i                                      otherwise (Theorem 2),
and the contained value is A_i - L_i.  Events without a measured response delay are
reported separately and left out of the shares.

Rule families (Theorem 3), parameters swept:
  ramp     token bucket with refill r (USD per hour) and burst b = r * 1 h;
  cliff    time lock at H hours (loss A_i when D_i > H; an automatic release at H would
           add the underlying rule's release before H);
  freeze   cumulative cap theta with independent review (loss min(A_i, theta)).
Placements:
  release  enforced where value is released (escrow withdrawal or mint): covers V, D, S,
           except a D failure whose flaw also reached a limit in the releasing contract
           (same_flaw_reaches_release_limit = yes in results/incident_coding.csv);
  verifier enforced in the verifiers' own software: covers S only;
  source   enforced on the source side when sending: covers S only.
"""
from __future__ import annotations

import csv
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
COVERS = {"release": {"V", "D", "S"}, "verifier": {"S"}, "source": {"S"}}
# an unbacked mint redeemed through the same bridge sends its redemption leg through the
# verifiers, so a limit in their software sees that leg, though not the minted claims sold on the
# minting chain. Share of the failure's value released against the minted claims, from
# results/incidents.csv (release_shares) for the failures coded "both" whose redemption passed the
# bridge's verifiers; class S failures are seen whole anyway.
REDEEMED_VIA_VERIFIERS = {
    "E11": 93750 / 120000,   # 93,750 of 120,000 minted wETH redeemed against the Ethereum escrow
    "E51": 1.0,              # all seven mints redeemed against the Axelar-side escrow
    "E31": (3.78 + 0.2) / 4.5,  # Ethereum (3.78M) and BSC (0.2M) redemptions of 4.5M
}


# After the blind recoding (coding/blind_coding.csv, check_location = offchain_verifier): class D
# failures whose flawed check ran in the verifiers' own off-chain software (an observer, an off-chain node,
# the single required verifier, a relayer's event reader), so the releases were signed or authorized by
# that software and a limit in it would have metered them; incidents.csv failure_basis says the same.
VERIFIER_CHECKS = {"E03", "E04", "E06", "E45", "E56"}


def verifier_share(event):
    """Share of a failure's value that passes the verifiers: all of it for class S and for the class D
    failures of VERIFIER_CHECKS, the redeemed leg for the unbacked mints of REDEEMED_VIA_VERIFIERS,
    none otherwise."""
    if event["cls"] in COVERS["verifier"]:
        return 1.0
    if event.get("id", "") in VERIFIER_CHECKS:
        return 1.0
    return REDEEMED_VIA_VERIFIERS.get(event.get("id", ""), 0.0)


def _flaw_reach():
    p = os.path.join(HERE, "results", "incident_coding.csv")
    if not os.path.exists(p):
        return {}
    with open(p, encoding="utf-8") as fh:
        return {r["id"]: r.get("same_flaw_reaches_release_limit", "") for r in csv.DictReader(fh)}


def chains_released():
    """Number of chains whose release points paid out unauthorized value (results/incident_coding.csv,
    n_chains_released); 1 where it was not determined.  A limit per release contract, so a
    failure that drained k chains faces k limits (Corollary 4.2)."""
    p = os.path.join(HERE, "results", "incident_coding.csv")
    if not os.path.exists(p):
        return {}
    out = {}
    with open(p, encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            s = (r.get("n_chains_released") or "").strip().lstrip(">=").strip()
            out[r["id"]] = int(s) if s.isdigit() and int(s) > 0 else 1
    return out


PER_CHANNEL = True   # default: one limit per release contract


def load(path):
    rows = []
    reach = _flaw_reach()
    nch = chains_released()
    with open(path, encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if "in_bridge_set" in r and str(r["in_bridge_set"]).strip().lower() not in ("true", "1", "yes"):
                continue
            try:
                A = float(r["amount_usd"])
            except (KeyError, ValueError):
                continue
            def f(key):
                try:
                    v = float(r.get(key, "") or "nan")
                except ValueError:
                    v = math.nan
                return v
            D = f("response_delay_s") if "response_delay_s" in r else math.nan
            if math.isnan(D):
                D = f("pause_lag_s")
            if math.isnan(D):
                D = f("detection_lag_s")
            rows.append({"id": r.get("id", ""), "name": r.get("name", ""), "A": A,
                         "cls": (r.get("failure_class", "O") or "O").strip()[:1].upper(),
                         "D_h": D / 3600.0 if not math.isnan(D) else math.nan,
                         "dur_h": f("outflow_duration_s") / 3600.0,
                         "flaw_reach": reach.get(r.get("id", ""), ""),
                         "n_chains": nch.get(r.get("id", ""), 1)})
    return rows


def loss(event, shape, param, placement, per_channel=None):
    """Loss of one failure under one rule.  With per_channel (the default), every chain the failure
    drained has its own copy of the rule, so ramps and cumulative caps let out n_chains times their
    curve; a hold lets out nothing or everything either way."""
    A, D, cls = event["A"], event["D_h"], event["cls"]
    k = event.get("n_chains", 1) if (PER_CHANNEL if per_channel is None else per_channel) else 1
    if placement == "verifier":
        s = verifier_share(event)
        if s == 0.0:
            return A
        if s < 1.0:   # only the redeemed leg passes the verifiers; the rest is lost in full
            return A * (1 - s) + loss({**event, "A": A * s, "cls": "S"}, shape, param, placement, per_channel)
        cls = "S"     # the whole failure passes the verifiers (class S, or a check in their own software)
    if cls not in COVERS[placement]:
        return A
    if placement == "release" and cls == "D" and event.get("flaw_reach") == "yes":
        return A
    if shape == "ramp":
        r = param
        return min(A, k * (r * 1.0 + r * D))
    if shape == "cliff":
        return A if D > param else 0.0
    if shape == "freeze":
        return min(A, k * param)
    raise ValueError(shape)


def summarize(rows):
    timed = [e for e in rows if not math.isnan(e["D_h"])]
    total = sum(e["A"] for e in timed)
    out = {"n_events": len(rows), "n_timed": len(timed), "value_timed": total,
           "value_untimed": sum(e["A"] for e in rows if math.isnan(e["D_h"])), "curves": {}}
    for placement in ("release", "verifier"):
        for shape, grid in (("ramp", [1e5, 3e5, 1e6, 3e6, 1e7, 3e7]), ("cliff", [1, 6, 12, 24, 72]),
                            ("freeze", [1e6, 1e7, 5e7, 1e8])):
            pts = []
            for p in grid:
                L = sum(loss(e, shape, p, placement) for e in timed)
                pts.append({"param": p, "loss": L, "contained_share": 1 - L / total if total else math.nan})
            out["curves"][f"{placement}:{shape}"] = pts
            pooled = []
            for p in grid:
                L = sum(loss(e, shape, p, placement, per_channel=False) for e in timed)
                pooled.append({"param": p, "loss": L, "contained_share": 1 - L / total if total else math.nan})
            out.setdefault("curves_pooled", {})[f"{placement}:{shape}"] = pooled
    by_class = {}
    for e in timed:
        by_class[e["cls"]] = by_class.get(e["cls"], 0.0) + e["A"]
    out["value_by_class_timed"] = by_class
    return out


def write_md(res, out_path):
    L = ["# Outflow events: counterfactual containment by rule shape and placement (generated)", "",
         "Generated by `replay_incidents.py` from `results/incidents.csv` (bridge events only). For each event with a measured "
         "first response delay D, the loss under a rule is min(amount, beta(D)) if the rule's placement covers the event's failure "
         "class (Theorem 2) and the full amount otherwise. Ramp: token bucket with refill r and burst one hour of refill. Cliff: "
         "time lock, everything released once D > H. Freeze: cumulative cap theta with independent review. Placement 'release' covers "
         "classes V, D, S; 'verifier' covers S only.", "",
         f"Events: {res['n_events']}; with a measured response delay: {res['n_timed']} "
         f"(USD {res['value_timed']/1e6:,.1f}M); without: USD {res['value_untimed']/1e6:,.1f}M. "
         "Value by class among timed events (USD M): " + ", ".join(f"{k} {v/1e6:,.1f}" for k, v in sorted(res['value_by_class_timed'].items())), ""]
    labels = {"ramp": ("refill r (USD M per hour)", 1e6), "cliff": ("deadline H (hours)", 1.0), "freeze": ("cap theta (USD M)", 1e6)}
    for key, pts in res["curves"].items():
        placement, shape = key.split(":")
        name, scale = labels[shape]
        L += [f"## {placement} placement, {shape}", "", f"| {name} | loss (USD M) | contained share |", "|---|---|---|"]
        for p in pts:
            L.append(f"| {p['param']/scale:g} | {p['loss']/1e6:,.1f} | {p['contained_share']:.3f} |")
        L.append("")
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(chr(10).join(L) + chr(10))


def main(path=None):
    path = path or os.path.join(HERE, "results", "incidents.csv")
    rows = load(path)
    res = summarize(rows)
    if path.endswith(os.path.join("results", "incidents.csv")):
        write_md(res, os.path.join(HERE, "results", "incident_replay.md"))
    print(json.dumps(res, indent=1))
    return res


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
