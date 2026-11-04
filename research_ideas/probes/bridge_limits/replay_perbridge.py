"""Per-bridge counterfactual: limits fitted to each failed bridge's own traffic (2026-10-16).

For every failure with a release history in data/legit/<ID>.csv (legitimate releases at the
bridge's release point over the 150 days before the first unauthorized release, built by
data/legit/*.py; columns ts_utc, leg, asset, amount, usd, kind, priced) this script fits limits to
that history and replays the failure against them.

Limits (each release contract, "leg", gets its own limit, with its assets pooled in US dollars; a
failure is charged the sum over the bridge's legs, Corollary 4.2, an upper bound when it drained
fewer legs):
- floor: the envelope E of the whole 150 days (Lambda* with h = 0); it delays none of that
  history, so it is an in-sample best case for limits that delay no legitimate transfer;
- bucket: min_r B(r) + r D_fit over the fit window, scaled by a margin m (Proposition 7.3), for
  D_fit in {1, 6, 24, 50} hours (50 h is the mean response time of the timed failures);
- review: transfers at or above the q-quantile of the fit window's sizes wait for a review; a
  bucket for D_fit = 1 h takes the rest (Proposition 5.4); q in {0.99, 0.999};
- the margin grid {1, 1.25, 1.5, 2, 3} for the frontier figure.
Windows: origin 1 fits on [t - 120 d, t - 30 d) and tests delay on [t - 30 d, t); origin 2 fits on
[t - 150 d, t - 60 d) and tests on [t - 60 d, t - 30 d). Containment uses origin 1, the limit in
force at the failure under a monthly refit. Window sensitivity: the bucket fitted on 60 or 120
days that end 30 days before the failure.

Losses: min{a, sum over legs of the leg's release within D} where a is the value the failure
released and D its first public response; a failure the release point does not see (class O, or
a flaw that also reached a limit in the release contract) loses a. Variants: as governed (class V
failures whose taken keys also controlled the release contract lose a); D x 5; no response for
failures detected through their own outflow; an alarm on releases not backed by deposited value
that pauses ell after the first unauthorized release (D replaced by min(D, ell), ell = 10 min and
1 h); the alarm with no limit at all (the loss is the value released within ell, from the
incident data's share_10m and share_1h, with their ranges).

Delay: each fitted bucket replays the test window's transfers (FIFO fluid bucket, full at the
start; rolling_v2.fifo_delays). Reported: share of value and number of transfers delayed, wait
quantiles, episodes in which the bucket bound (runs of delayed transfers; the false alarms of an
alarm that fires when the limit binds), the transfers sent to review and their value, and the
mean wait per dollar of tested value with reviews waiting L in {1, 6, 24} hours.

Aggregates over failures, excluding failures that met a deployed limit (E30: its release was
already capped by the limit in force; Section 6 of the paper): by value, by failure, net of value
later returned or frozen (weights a - recovered), a bootstrap 90% interval over failures (2,000
resamples, fixed seed) and the range when one failure is left out. A variant leaves out releases
of uncertain ownership (OUTSIZED).

Outputs: results/replay_perbridge.json, results/replay_perbridge.md.
Run with the Python environment of requirements.txt.
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import math
import os
import statistics
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "ccip"))
from rolling_v2 import fifo_delays  # noqa: E402
from replay_incidents import VERIFIER_CHECKS  # noqa: E402

DAY = 86400.0
H = 3600.0
ORIGINS = {"o1": ((120 * DAY, 30 * DAY), (30 * DAY, 0.0)), "o2": ((150 * DAY, 60 * DAY), (60 * DAY, 30 * DAY))}
ALT_FITS = {"fit60": (90 * DAY, 30 * DAY), "fit120": (150 * DAY, 30 * DAY)}
MARGINS = [1.0, 1.25, 1.5, 2.0, 3.0]
D_FITS = {"1h": 1 * H, "6h": 6 * H, "24h": 24 * H, "50h": 50 * H}
REVIEW_LATENCIES_H = [1, 6, 24]
ALARMS = {"10min": 600.0, "1h": 3600.0}
EXCLUDE_FROM_AGG = {"E30": "met a deployed limit; its release was already capped (Section 6)"}
OUTFLOW_DETECTED = {"third_party_alert", "user_report_or_failed_withdrawal", "escrow_or_balance_shortfall"}
# Unpriced assets valued at the asset they track, from the nearest priced release of that asset in
# the same file (within 36 h). E11: DefiLlama has no series for bETH or HBTC (E11 README).
PARITY = {"E11": {"bETH": ("ETH", "WETH"), "HBTC": ("WBTC",)}}
# Variant: the outsized releases left out (data/legit READMEs): two releases of over 100,000 ETH in
# E13, and the largest release in E14. Public address labels (Etherscan) attribute both E13
# recipients to one exchange's wallets, and a wallet of the same exchange deposited the first amount
# back 40 minutes later; the E14 recipient is unlabeled, funded from an exchange wallet, and transacted
# with a trading firm's and a liquidity protocol's addresses. None is an operator's own address, so all
# stay in the main series.
OUTSIZED = {"E13": 300e6, "E14": 50e6}

DESIGNS = {"floor": None}
for _k, _d in D_FITS.items():
    DESIGNS[f"bucket {_k} m=1.5"] = ("bucket", _d, 1.5, None)
for _m in MARGINS:
    DESIGNS[f"bucket 6h m={_m}"] = ("bucket", 6 * H, _m, None)
    DESIGNS[f"review 1h m={_m} q=0.999"] = ("review", H, _m, 0.999)
    DESIGNS[f"review 1h m={_m} q=0.99"] = ("review", H, _m, 0.99)
MAIN = {"floor": "floor", "bucket": "bucket 6h m=1.5", "review": "review 1h m=1.5 q=0.999", "review100": "review 1h m=1.5 q=0.99"}


def ts(s: str) -> float:
    return dt.datetime.strptime(s.strip(), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc).timestamp()


def quant(xs, q):
    return float(np.quantile(xs, q)) if len(xs) else math.nan


def share_range(s):
    """share_10m / share_1h fields: '0.831' or a range '0.000-1.000'."""
    s = (s or "").strip()
    if not s:
        return (math.nan, math.nan)
    if "-" in s[1:]:
        lo, hi = s.split("-", 1) if not s.startswith("-") else (s, s)
        return (float(lo), float(hi))
    return (float(s), float(s))


def load_failures():
    inc = {r["id"]: r for r in csv.DictReader(open(os.path.join(HERE, "results", "incidents.csv"), encoding="utf-8"))
           if r["in_bridge_set"] == "yes"}
    cod = {r["id"]: r for r in csv.DictReader(open(os.path.join(HERE, "results", "incident_coding.csv"), encoding="utf-8"))}
    return inc, cod


def parity_prices(rows, ref_assets):
    pts = sorted((ts(r["ts_utc"]), float(r["usd"]) / float(r["amount"])) for r in rows
                 if r["asset"] in ref_assets and r.get("priced") == "yes" and r.get("usd") and float(r["amount"] or 0) > 0)
    times = np.array([p[0] for p in pts])
    prices = np.array([p[1] for p in pts])

    def price(t):
        if len(times) == 0:
            return None
        k = int(np.searchsorted(times, t))
        best = min((abs(times[j] - t), prices[j]) for j in (k - 1, k) if 0 <= j < len(times))
        return best[1] if best[0] <= 36 * 3600 else None
    return price


def load_history(path, t_fail, fid=None, drop_above=None):
    rows = list(csv.DictReader(open(path, encoding="utf-8")))
    par = {a: parity_prices(rows, refs) for a, refs in PARITY.get(fid, {}).items()}
    legs = {}
    n_all, n_priced, n_unpriced, n_parity, n_dropped = len(rows), 0, 0, 0, 0
    for r in rows:
        t = ts(r["ts_utc"])
        assert t < t_fail, (path, r["ts_utc"])
        assert t >= t_fail - 150 * DAY - 1, (path, r["ts_utc"])
        if r.get("priced", "yes") == "yes" and r.get("usd"):
            v = float(r["usd"])
        elif r["asset"] in par and par[r["asset"]](t) is not None:
            v = float(r["amount"]) * par[r["asset"]](t)
            n_parity += 1
        else:
            n_unpriced += 1
            continue
        if v <= 0:
            continue
        if drop_above is not None and v > drop_above:
            n_dropped += 1
            continue
        n_priced += 1
        legs.setdefault(r["leg"], []).append((t, v))
    out = {}
    for k, s in legs.items():
        s.sort()
        out[k] = (np.array([t for t, _ in s]), np.array([v for _, v in s]))
    return out, {"n_rows": n_all, "n_priced": n_priced, "n_unpriced": n_unpriced, "n_parity": n_parity, "n_dropped": n_dropped}


def burst_np(t, v, r):
    """B(r) of analysis_core.burstiness, vectorized (t sorted)."""
    A = np.cumsum(v)
    return float(np.max((A - r * t) - np.minimum.accumulate((A - v) - r * t)))


def best_bucket_np(t, v, D, iters=200):
    """analysis_core.best_bucket_exact with burst_np: the same search bracket and iterations."""
    span = (t[-1] - t[0]) if len(t) > 1 else 1.0
    hi = 2.0 * float(v.sum()) / max(span, 1.0) + float(v.max()) / max(D, 1.0)
    lo, g = 0.0, (math.sqrt(5) - 1) / 2
    f = lambda r: burst_np(t, v, r) + r * D
    x1, x2 = hi - g * (hi - lo), lo + g * (hi - lo)
    f1, f2 = f(x1), f(x2)
    for _ in range(iters):
        if f1 <= f2:
            hi, x2, f2 = x2, x1, f1
            x1 = hi - g * (hi - lo)
            f1 = f(x1)
        else:
            lo, x1, f1 = x1, x2, f2
            x2 = lo + g * (hi - lo)
            f2 = f(x2)
    r = (lo + hi) / 2
    b = burst_np(t, v, r)
    b0 = burst_np(t, v, 0.0)
    if b0 <= b + r * D:
        return b0, 0.0
    return b, r


def envelope_np(t, v, u):
    """analysis_core.envelope_events, vectorized (t sorted)."""
    if u <= 0 or len(t) == 0:
        return 0.0
    A = np.concatenate([[0.0], np.cumsum(v)])
    idx = np.searchsorted(t, t - u, side="right")
    return float(np.max(A[1:] - A[idx]))


FIT_CACHE = {}


def fit(t_all, v_all, t_fail, fit_win, Dfit, q, key):
    """(threshold, (b, r)) of the bucket fitted on fit_win for D_fit, after removing the reviewed
    transfers (q-quantile and above); cached across margins."""
    ck = (key, fit_win, Dfit, q)
    if ck not in FIT_CACHE:
        m = (t_all >= t_fail - fit_win[0]) & (t_all < t_fail - fit_win[1])
        if not m.any():
            FIT_CACHE[ck] = (math.inf, None)
        else:
            fv = v_all[m]
            s = float(np.quantile(fv, q)) if q else math.inf
            small = fv < s
            FIT_CACHE[ck] = (s, best_bucket_np(t_all[m][small], fv[small], Dfit) if small.any() else None)
    return FIT_CACHE[ck]


def test_stats(t_all, v_all, t_fail, test_win, s, b, r):
    m = (t_all >= t_fail - test_win[0]) & (t_all < t_fail - test_win[1])
    tt, tv = t_all[m], v_all[m]
    small = tv < s
    st = {"test_value": float(tv.sum()), "test_n": int(len(tv)), "review_value": float(tv[~small].sum()),
          "review_n": int((~small).sum()), "delayed_value": 0.0, "delayed_n": 0, "waits_h": [], "dollar_hours": 0.0,
          "episodes": 0, "days": (test_win[0] - test_win[1]) / DAY}
    if small.any():
        d = fifo_delays(tt[small].tolist(), tv[small].tolist(), b * (1 + 1e-9) + 1e-6, r)
        prev = False
        for v, w in zip(tv[small].tolist(), d):
            on = w > 1e-9
            if on:
                st["delayed_value"] += v
                st["delayed_n"] += 1
                st["waits_h"].append(w / H)
                st["dollar_hours"] += v * min(w, 30 * DAY) / H
                if not prev:
                    st["episodes"] += 1
            prev = on
    return st


def seen(cls, c, governed):
    if cls not in ("S", "V", "D"):
        return False
    if cls == "D" and c.get("same_flaw_reaches_release_limit") == "yes":
        return False
    if cls == "V" and governed and c.get("keys_controlled_release_contract") == "yes":
        return False
    return True


# designs that use an independent check that value deposited on the sending side backs each
# release (Section 8 of the paper). The check reads both chains from its own nodes and compares, per
# asset, what the release side has released or minted with what the sending side holds (a conservation
# check, as in Liu et al.'s accounting); an event-matching check instead pairs each release with a
# deposit event. Custody held directly by keys (coding/blind_coding.csv, release_point_contract = no;
# results/blind_agreement.json keys_held_ids) hosts no contract that could hold, limit or pause, so
# releases signed by taken keys there (class V) are stopped by nothing; for classes S and D the hold,
# the limit and the pause sit in the signers' software, which the failure did not take.
def _keys_held():
    p = os.path.join(HERE, "results", "blind_agreement.json")
    return set(json.load(open(p, encoding="utf-8")).get("keys_held_ids", [])) if os.path.exists(p) else set()


KEYS_HELD = _keys_held()
GATE_H = 600.0          # hold on every withdrawal while the check runs (the testbed paused within 60 s)
REVIEW_L = 3600.0       # latency of the review of the largest transfers


def check_sees(fid, cls, kind="conservation", as_built=False):
    """Whether the check flags the failure's first unauthorized release and an independent party can
    stop what is still queued: classes S, V and D. The main analysis assumes custody in a contract, as
    for the limits; with custody as built (as_built), class V from custody held by keys cannot be
    stopped. An event-matching check also misses class S, whose forged deposit event matches the release."""
    if cls not in ("S", "V", "D"):
        return False
    if as_built and cls == "V" and fid in KEYS_HELD:
        return False
    if kind == "matching" and cls == "S":
        return False
    return True


def compute(inc, cod, ids, legit_dir, drop_outsized=False, fit_override=None):
    out = {}
    for i in ids:
        r, c = inc[i], cod.get(i, {})
        t_fail = ts(r["first_release_utc"])
        legs, cnt = load_history(os.path.join(legit_dir, f"{i}.csv"), t_fail, fid=i,
                                 drop_above=OUTSIZED.get(i) if drop_outsized else None)
        A = float(r["amount_usd"])
        D_s = float(r["response_delay_s"]) if r["response_delay_s"] else math.inf
        cls = (r["failure_class"] or "O")[:1]
        f = {"name": r["name"], "date": r["date"], "A": A, "cls": cls, "D_h": D_s / H,
             "recovered": float(c.get("recovered_usd") or 0.0),
             "share_10m": share_range(r.get("share_10m")), "share_1h": share_range(r.get("share_1h")),
             "legs": {k: {"n": int(len(v[0])), "value": float(v[1].sum())} for k, v in legs.items()},
             "counts": cnt, "detect": c.get("detection_channel"), "pause": c.get("pause_holder"),
             "keys_ctrl": c.get("keys_controlled_release_contract"), "resp_basis": r.get("response_basis", ""),
             "keys_held": i in KEYS_HELD, "check_sees": check_sees(i, cls), "check_sees_built": check_sees(i, cls, as_built=True),
             "check_sees_matching": check_sees(i, cls, "matching"), "limits": {}}
        f["legit_value_per_day"] = sum(v["value"] for v in f["legs"].values()) / 150.0
        starts = [float(t_all.min()) for t_all, _ in legs.values() if len(t_all)]
        f["history_days"] = (t_fail - min(starts)) / DAY if starts else 0.0
        for name, spec in DESIGNS.items():
            fns, tests = [], {o: [] for o in ORIGINS}
            for leg, (t_all, v_all) in legs.items():
                if spec is None:
                    fns.append(lambda D, t_all=t_all, v_all=v_all: envelope_np(t_all, v_all, D))
                    continue
                kind, Dfit, mu, q = spec
                fw = fit_override if fit_override else ORIGINS["o1"][0]
                s, bb = fit(t_all, v_all, t_fail, fw, Dfit, q, (i, leg, drop_outsized))
                if bb is None:
                    continue
                b, rr = mu * bb[0], mu * bb[1]
                fns.append(lambda D, b=b, rr=rr: b + rr * D)
                for o, (fwin, twin) in ORIGINS.items():
                    if fit_override and o != "o1":
                        continue
                    so, bbo = (s, bb) if o == "o1" else fit(t_all, v_all, t_fail, fwin, Dfit, q, (i, leg, drop_outsized))
                    if bbo is None:
                        continue
                    tests[o].append(test_stats(t_all, v_all, t_fail, twin, so, mu * bbo[0], mu * bbo[1]))

            def release(D, fns=fns):
                return sum(fn(D) for fn in fns) if math.isfinite(D) else math.inf

            def loss(D, governed=False):
                if not seen(cls, c, governed) or not math.isfinite(D):
                    return A
                return min(A, release(D))

            def behind_hold(Hs):
                """Loss of the limit behind a hold of Hs on every withdrawal, the response at D_s
                cancelling what is still held (Theorem 4.1: delta_H in series with the limit)."""
                return 0.0 if D_s <= Hs else loss(D_s - Hs)
            is_review = spec is not None and spec[0] == "review"
            res = {"release_1h": release(H), "release_6h": release(6 * H),
                   "loss": loss(D_s), "loss_governed": loss(D_s, governed=True), "loss_x5": loss(5 * D_s),
                   "loss_outflow_never": loss(math.inf if f["detect"] in OUTFLOW_DETECTED else D_s),
                   # custody held by keys hosts no release-point limit; a limit in the signers'
                   # software sees class S and the class D failures of the verifiers' own checks
                   "loss_keysheld": (A if (i in KEYS_HELD and (cls == "V" or (cls == "D" and i not in VERIFIER_CHECKS)))
                                     else loss(D_s)),
                   # the review is the check; if the check fails, the party's large withdrawals
                   # pass it after REVIEW_L, a cliff on top of the bucket (Proposition 5.4(iii))
                   "loss_check_fails": (A if (is_review and seen(cls, c, False) and D_s > REVIEW_L) else loss(D_s)),
                   # a hold of GATE_H on every withdrawal while the check runs, this limit behind it
                   "loss_gate_works": 0.0 if (check_sees(i, cls) and seen(cls, c, False)) else behind_hold(GATE_H),
                   "loss_gate_works_matching": 0.0 if (check_sees(i, cls, "matching") and seen(cls, c, False)) else behind_hold(GATE_H),
                   "loss_gate_fails": behind_hold(GATE_H)}
            # with custody as built: class V from custody held by keys is stopped by nothing
            kh_v = i in KEYS_HELD and cls == "V"
            res["loss_gate_works_built"] = A if kh_v else res["loss_gate_works"]
            for a, ell in ALARMS.items():
                # the alarm pauses only the failures the check flags and someone can stop
                res[f"loss_alarm_{a}"] = loss(min(D_s, ell)) if check_sees(i, cls) else loss(D_s)
                res[f"loss_alarm_{a}_matching"] = loss(min(D_s, ell)) if check_sees(i, cls, "matching") else loss(D_s)
            for o, sts in tests.items():
                if not sts:
                    continue
                tv = sum(x["test_value"] for x in sts)
                res[f"test_{o}"] = {
                    "test_value": tv, "test_n": sum(x["test_n"] for x in sts),
                    "delayed_value": sum(x["delayed_value"] for x in sts), "delayed_n": sum(x["delayed_n"] for x in sts),
                    "review_value": sum(x["review_value"] for x in sts), "review_n": sum(x["review_n"] for x in sts),
                    "dollar_hours": sum(x["dollar_hours"] for x in sts), "episodes": sum(x["episodes"] for x in sts),
                    "days": sts[0]["days"], "waits_h": [w for x in sts for w in x["waits_h"]]}
            f["limits"][name] = res
        out[i] = f
    return out


def exclusions(F):
    """Failures shown but not aggregated: those of EXCLUDE_FROM_AGG, and (17 histories) those whose
    rebuilt history starts later than the start of the first fit window, since the designs are fitted to the
    90 days that end 30 days before the failure (E01: routers deployed 40 days before the failure)."""
    out = dict(EXCLUDE_FROM_AGG)
    for i, f in F.items():
        if i not in out and f.get("history_days", 150.0) < ORIGINS["o1"][0][0] / DAY:
            out[i] = (f"history starts {f['history_days']:.0f} days before the failure; the designs are fitted to "
                      f"the 90 days that end 30 days before it")
    return out


def aggregate(F, rng_seed=20261016, exclude=None):
    """Value-weighted, event-weighted and net-of-recovery shares, bootstrap and leave-one-out."""
    excl = exclusions(F) if exclude is None else exclude
    ids = [i for i in F if i not in excl]
    A = np.array([F[i]["A"] for i in ids])
    Wn = np.array([max(0.0, F[i]["A"] - F[i]["recovered"]) for i in ids])
    rng = np.random.default_rng(rng_seed)
    boot_idx = rng.integers(0, len(ids), size=(2000, len(ids)))
    agg = {"ids": ids}

    def shares(L):
        kept = 1 - L / A
        out = {"value": float(1 - L.sum() / A.sum()), "event": float(kept.mean()),
               "net": float((Wn * kept).sum() / Wn.sum()) if Wn.sum() > 0 else math.nan}
        b = 1 - L[boot_idx].sum(axis=1) / A[boot_idx].sum(axis=1)
        out["boot_lo"], out["boot_hi"] = (float(x) for x in np.quantile(b, [0.05, 0.95]))
        loo = [1 - (L.sum() - L[k]) / (A.sum() - A[k]) for k in range(len(ids))]
        out["loo_lo"], out["loo_hi"] = float(min(loo)), float(max(loo))
        return out
    loss_keys = (("loss", "loss_governed", "loss_x5", "loss_outflow_never", "loss_keysheld", "loss_check_fails",
                  "loss_gate_works", "loss_gate_works_matching", "loss_gate_fails", "loss_gate_works_built")
                 + tuple(f"loss_alarm_{x}" for x in ALARMS) + tuple(f"loss_alarm_{x}_matching" for x in ALARMS))
    # the failures whose first response was a pause (or a report of one), not an acknowledgment
    pf = [k for k, i in enumerate(ids) if F[i].get("resp_basis") in ("pause", "pause report")]
    agg["pause_first_ids"] = [ids[k] for k in pf]
    for name in DESIGNS:
        a = {}
        for key in loss_keys:
            a[key] = shares(np.array([F[i]["limits"][name][key] for i in ids]))
        Lpf = np.array([F[ids[k]]["limits"][name]["loss"] for k in pf])
        Apf = A[pf]
        a["loss_pause_first_subset"] = {"value": float(1 - Lpf.sum() / Apf.sum()) if len(pf) else math.nan,
                                        "event": float((1 - Lpf / Apf).mean()) if len(pf) else math.nan, "n": len(pf)}
        for o in ORIGINS:
            ts_ = [F[i]["limits"][name].get(f"test_{o}") for i in ids if F[i]["limits"][name].get(f"test_{o}")]
            if not ts_:
                continue
            tv = sum(t["test_value"] for t in ts_)
            months = sum(t["days"] for t in ts_) / 30.0
            d = {"test_value": tv, "test_n": sum(t["test_n"] for t in ts_),
                 "delayed_share": sum(t["delayed_value"] for t in ts_) / tv,
                 "delayed_share_max": max(t["delayed_value"] / t["test_value"] if t["test_value"] else 0 for t in ts_),
                 "delayed_n": sum(t["delayed_n"] for t in ts_),
                 "review_share": sum(t["review_value"] for t in ts_) / tv, "review_n": sum(t["review_n"] for t in ts_),
                 "reviews_per_bridge_month": sum(t["review_n"] for t in ts_) / months,
                 "episodes_per_bridge_month": sum(t["episodes"] for t in ts_) / months,
                 "bridges_with_episodes": sum(t["episodes"] > 0 for t in ts_),
                 "wait_p50_h": quant([w for t in ts_ for w in t["waits_h"]], 0.5),
                 "wait_p90_h": quant([w for t in ts_ for w in t["waits_h"]], 0.9),
                 "hours_per_dollar": sum(t["dollar_hours"] for t in ts_) / tv}
            d["total_delayed_share"] = d["delayed_share"] + d["review_share"]
            for L in REVIEW_LATENCIES_H:
                d[f"hours_per_dollar_review{L}h"] = (sum(t["dollar_hours"] for t in ts_) + L * sum(t["review_value"] for t in ts_)) / tv
            # counts and tails over all tested transfers, a reviewed transfer waiting REVIEW_L
            n_all = d["test_n"]
            waits = [w for t in ts_ for w in t["waits_h"]] + [REVIEW_L / H] * d["review_n"]
            full = np.concatenate([np.zeros(max(0, n_all - len(waits))), np.array(waits, dtype=float)])
            d["count_delayed_share"] = len(waits) / n_all if n_all else math.nan
            d["wait_all_p95_h"], d["wait_all_p99_h"], d["wait_all_p999_h"] = (float(np.quantile(full, q)) for q in (0.95, 0.99, 0.999))
            rpm = [t["review_n"] / (t["days"] / 30.0) for t in ts_]
            d["reviews_per_month_min"], d["reviews_per_month_median"], d["reviews_per_month_max"] = (
                float(min(rpm)), float(statistics.median(rpm)), float(max(rpm)))
            a[f"test_{o}"] = d
        agg[name] = a
    # the alarm with no limit: the loss is the value released within ell of the first release
    for a, key in (("10min", "share_10m"), ("1h", "share_1h")):
        # a failure the check does not flag, or that nobody can stop, loses all of it
        lo = np.array([F[i]["A"] * F[i][key][0] if F[i]["check_sees"] else F[i]["A"] for i in ids])
        hi = np.array([F[i]["A"] * F[i][key][1] if F[i]["check_sees"] else F[i]["A"] for i in ids])
        agg[f"alarm_only_{a}"] = {"value_lo": float(1 - hi.sum() / A.sum()), "value_hi": float(1 - lo.sum() / A.sum()),
                                  "event_lo": float((1 - hi / A).mean()), "event_hi": float((1 - lo / A).mean())}
    agg["value"] = float(A.sum())
    return agg


def main():
    inc, cod = load_failures()
    legit_dir = os.path.join(HERE, "data", "legit")
    ids = sorted(f[:-4] for f in os.listdir(legit_dir) if f.endswith(".csv") and f[:-4] in inc
                 and inc[f[:-4]]["response_delay_s"])
    F = compute(inc, cod, ids, legit_dir)
    excl = exclusions(F)
    out = {"params": {"origins_days": {o: [w[0][0] / DAY, w[0][1] / DAY, w[1][0] / DAY, w[1][1] / DAY] for o, w in ORIGINS.items()},
                      "history_days": 150, "excluded_from_aggregates": excl, "alarms_s": ALARMS,
                      "review_latencies_h": REVIEW_LATENCIES_H, "gate_h_s": GATE_H, "review_l_s": REVIEW_L,
                      "keys_held": sorted(KEYS_HELD)},
           "failures": F, "aggregate": aggregate(F, exclude=excl)}
    total = sum(float(r["amount_usd"]) for r in inc.values())
    agg_ids = out["aggregate"]["ids"]
    out["n_failures"] = len(F)
    out["n_aggregate"] = len(agg_ids)
    out["value_share_of_bridge_set"] = sum(F[i]["A"] for i in agg_ids) / total
    out["value_share_all_rebuilt"] = sum(f["A"] for f in F.values()) / total
    # what sets the floor of the failure with the largest floor loss: the envelope of its history
    # over its response time, with and without its outsized releases (public address labels attribute
    # the two E13 releases to an exchange's wallets; data/legit/E13_README.md)
    big = max(agg_ids, key=lambda i: F[i]["limits"]["floor"]["loss"])
    tb = ts(inc[big]["first_release_utc"])
    Db = float(inc[big]["response_delay_s"])
    full = load_history(os.path.join(legit_dir, f"{big}.csv"), tb, fid=big)[0]
    trim = load_history(os.path.join(legit_dir, f"{big}.csv"), tb, fid=big, drop_above=OUTSIZED.get(big))[0]
    out["largest_floor_loss"] = {
        "id": big, "A": F[big]["A"], "D_h": Db / H,
        "E_D": sum(envelope_np(t, v, Db) for t, v in full.values()),
        "E_D_without_outsized": sum(envelope_np(t, v, Db) for t, v in trim.values()),
        "outsized_usd": sum(float(v[v > OUTSIZED[big]].sum()) for _, v in full.values()) if big in OUTSIZED else 0.0}
    # without releases of uncertain ownership
    FV = compute(inc, cod, ids, legit_dir, drop_outsized=True)
    out["variant_outsized"] = {"dropped": {i: f["counts"]["n_dropped"] for i, f in FV.items() if f["counts"]["n_dropped"]},
                               "aggregate": {k: v for k, v in aggregate(FV, exclude=excl).items() if k in ("floor", MAIN["bucket"], MAIN["review"])}}
    # fit-window sensitivity for the main bucket
    out["window_sensitivity"] = {}
    for wname, fw in ALT_FITS.items():
        FIT_CACHE.clear()
        Fw = compute(inc, cod, ids, legit_dir, fit_override=fw)
        aw = aggregate(Fw, exclude=excl)
        out["window_sensitivity"][wname] = {k: {"value": aw[k]["loss"]["value"], "event": aw[k]["loss"]["event"],
                                                "delayed_share": aw[k].get("test_o1", {}).get("delayed_share")}
                                            for k in (MAIN["bucket"], MAIN["review"])}
    for f in out["failures"].values():
        for res in f["limits"].values():
            for o in ORIGINS:
                if f"test_{o}" in res:
                    res[f"test_{o}"].pop("waits_h", None)
    json.dump(out, open(os.path.join(HERE, "results", "replay_perbridge.json"), "w", encoding="utf-8"), indent=1)

    G = out["aggregate"]
    L = ["# Per-bridge counterfactual (generated)", "",
         f"Generated by `replay_perbridge.py`; see its docstring. Failures with a rebuilt history: {len(F)} "
         f"({100 * out['value_share_all_rebuilt']:.1f}% of the bridge set's value); in the aggregates: {len(agg_ids)} "
         f"({100 * out['value_share_of_bridge_set']:.1f}%), excluding " + "; ".join(f"{k} ({v})" for k, v in excl.items()) + ".", "",
         "## Per failure (kept share at the observed response time)", "",
         "| id | A (M) | class | D (h) | legs | legit/day (M) | floor | bucket 6h | review 1/1000 | review + alarm 10 min | alarm only 10 min | bucket delayed (o1) | reviews (o1) |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for i, f in sorted(F.items(), key=lambda kv: -kv[1]["A"]):
        kept = lambda k, key="loss": 100 * (1 - f["limits"][k][key] / f["A"])
        tb = f["limits"][MAIN["bucket"]].get("test_o1", {})
        trv = f["limits"][MAIN["review"]].get("test_o1", {})
        s10 = f["share_10m"]
        L.append(f"| {i} | {f['A'] / 1e6:.0f} | {f['cls']} | {f['D_h']:.1f} | {len(f['legs'])} | {f['legit_value_per_day'] / 1e6:.2f} | "
                 f"{kept('floor'):.0f}% | {kept(MAIN['bucket']):.0f}% | {kept(MAIN['review']):.0f}% | {kept(MAIN['review'], 'loss_alarm_10min'):.0f}% | "
                 f"{100 * (1 - s10[1]):.0f}-{100 * (1 - s10[0]):.0f}% | "
                 f"{100 * tb.get('delayed_value', 0) / max(tb.get('test_value', 1), 1):.1f}% | {trv.get('review_n', 0)} |")
    L += ["", "## Aggregates (kept share; bootstrap 90% interval; leave-one-out range)", "",
          "| design | by value | 90% | LOO | by failure | net of recoveries | governed | D x 5 | outflow never | alarm 10 min | alarm 1 h |",
          "|---|---|---|---|---|---|---|---|---|---|---|"]
    for name in ["floor"] + [f"bucket {k} m=1.5" for k in D_FITS] + [MAIN["review"], MAIN["review100"]]:
        a = G[name]
        s = a["loss"]
        L.append(f"| {name} | {100 * s['value']:.1f}% | {100 * s['boot_lo']:.0f}-{100 * s['boot_hi']:.0f}% | {100 * s['loo_lo']:.0f}-{100 * s['loo_hi']:.0f}% | "
                 f"{100 * s['event']:.1f}% | {100 * s['net']:.1f}% | {100 * a['loss_governed']['value']:.1f}% | {100 * a['loss_x5']['value']:.1f}% | "
                 f"{100 * a['loss_outflow_never']['value']:.1f}% | {100 * a['loss_alarm_10min']['value']:.1f}% | {100 * a['loss_alarm_1h']['value']:.1f}% |")
    for a in ("10min", "1h"):
        x = G[f"alarm_only_{a}"]
        L.append(f"| alarm only, {a} (no limit) | {100 * x['value_lo']:.1f}-{100 * x['value_hi']:.1f}% | | | {100 * x['event_lo']:.1f}-{100 * x['event_hi']:.1f}% | | | | | | |")
    L += ["", "## Delay on held-out traffic (origin 1 / origin 2)", "",
          "| design | delayed (bucket) | max over bridges | transfers delayed | binding episodes per bridge-month | reviews per bridge-month | reviewed value | total delayed incl. review | wait per dollar (h): no review wait / review 1 h / 6 h / 24 h |",
          "|---|---|---|---|---|---|---|---|---|"]
    for name in [f"bucket {k} m=1.5" for k in D_FITS] + [MAIN["review"], MAIN["review100"]]:
        for o in ORIGINS:
            d = G[name].get(f"test_{o}")
            if not d:
                continue
            L.append(f"| {name} ({o}) | {100 * d['delayed_share']:.1f}% | {100 * d['delayed_share_max']:.0f}% | {d['delayed_n']} of {d['test_n']} | "
                     f"{d['episodes_per_bridge_month']:.1f} | {d['reviews_per_bridge_month']:.1f} | {100 * d['review_share']:.1f}% | {100 * d['total_delayed_share']:.1f}% | "
                     f"{d['hours_per_dollar']:.3f} / {d['hours_per_dollar_review1h']:.3f} / {d['hours_per_dollar_review6h']:.3f} / {d['hours_per_dollar_review24h']:.3f} |")
    L += ["", f"Variant without releases of uncertain ownership (dropped {out['variant_outsized']['dropped']}): "
          + "; ".join(f"{k} {100 * v['loss']['value']:.1f}% by value" for k, v in out["variant_outsized"]["aggregate"].items()), "",
          "Fit-window sensitivity (bucket and review fitted on 60 or 120 days ending 30 days before the failure): "
          + "; ".join(f"{w}: " + ", ".join(f"{k} {100 * v['value']:.1f}% (delayed {100 * (v['delayed_share'] or 0):.1f}%)" for k, v in x.items())
                      for w, x in out["window_sensitivity"].items())]
    open(os.path.join(HERE, "results", "replay_perbridge.md"), "w", encoding="utf-8").write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
