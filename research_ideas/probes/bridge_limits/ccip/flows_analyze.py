"""Stage C: window envelopes of CCIP token-lane flows against the token-pool buckets.

Inputs  ccip/selection.json; data/ccip/derived/{transfers.csv.gz, lanes_current.csv, lanes_history.csv,
        param_changes_refined.json, ranking_meta.json, prices_current.json}; DefiLlama price cache in
        data/ccip/prices/ (hourly and daily series, no network access here); data/ccip/messages_lane/*/ and
        messages_all/ (coverage check); optionally data/ccip/onchain/amendments.json (bucket settings read from
        the pools' own state and event logs by onchain_checks.py, which override the documented series where
        they disagree).
Output  data/ccip/derived/flows_results.json

Definitions (token units, amounts as sent; times UTC seconds):
  E(u)    largest amount sent in a half-open window [s, s+u) (analysis_core.envelope_events); E(0+) is the
          largest total sent within one second.
  Zero-delay condition for a bucket (b, r) that starts full: b + r u >= E(u) for every u > 0.  It is
          equivalent to b + r (t_j - t_i) >= A[i..j] for every pair of transfer times t_i <= t_j, where A[i..j]
          is the amount sent at times in [t_i, t_j].  The smallest failing window is the smallest gap t_j - t_i
          over the violating pairs (the condition fails for every u slightly above it); computed exactly over
          all pairs.  The pair points also give E(u) exactly (running maximum over gaps < u).
  Smallest zero-delay response at d: min of b + r d over buckets that meet the condition = upper concave hull
          of the pair staircase at d (analysis_core.best_bucket on the exact points, Proposition 7).
  Outflow bound beta(d) = b + r d (analysis_core.beta_bucket): the most a full bucket lets out within d;
          reported relative to E(d).
Replays (bucket full at the start of the stream and whenever it is switched on; a parameter change keeps the
token level, capped at the new capacity, as in RateLimiter._setTokenBucketConfig):
  reject  the rule a CCIP pool applies: a transfer larger than the tokens available is refused and consumes
          nothing (RateLimiter._consume reverts).  Episode: maximal interval that starts with a refusal and ends
          when the bucket is next full.
  FIFO    a transfer larger than the tokens available waits, first in first out, until refills cover it
          (Lindley recursion X_j = max(-b, X_{j-1} - r dt) + a_j; cross-checked against
          analysis_core.token_bucket_fifo).  Episode: busy period of the backlog.
Sides: outbound = source pool's bucket on send times; inbound = destination pool's bucket on execution
(receipt) times, send time where no receipt is recorded.
Buckets: "current" = lanes.json of the last commit before access; "in force" = monthly snapshots with change
dates refined by refine_param_dates.py (a loosening change applied at the start of its date bracket, a
tightening change at its end), amended by on-chain readings where available.

Run: python -I flows_analyze.py
"""
import collections
import datetime as dt
import glob
import gzip
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(1, os.path.dirname(HERE))  # analysis_core.py lives in the parent directory
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import analysis_core as ac  # noqa: E402
import ccip_common as cc  # noqa: E402

U_REPORT = [("1 min", 60), ("10 min", 600), ("1 h", 3600), ("6 h", 21600), ("24 h", 86400), ("7 d", 604800)]
D_REPORT = [("10 min", 600), ("1 h", 3600), ("6 h", 21600), ("24 h", 86400)]
TOL = 1e-9  # relative tolerance for comparisons with the bucket (amounts equal to the capacity pass)
PRICE_PREV_MAX = 36 * 3600  # use the last price at or before t if it is at most this old, else the nearest


def fmt_ts(t):
    if t is None or (isinstance(t, float) and not math.isfinite(t)):
        return None
    return dt.datetime.fromtimestamp(int(t), dt.timezone.utc).strftime("%Y-%m-%d %H:%M")


def iso_ts(s):
    return int(dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp())


# ------------------------------------------------------------------ prices (DefiLlama cache only)

def price_series(coin):
    """Merged hourly and daily DefiLlama points cached by ccip_common.chart_prices."""
    pts = {}
    for period in ("1d", "1h"):  # hourly points override daily ones at the same timestamp
        fn = os.path.join(cc.PRICE_CACHE, "".join(ch if ch.isalnum() or ch in "_.-" else "_"
                                                  for ch in f"{coin}_{period}.json"))
        if os.path.exists(fn):
            js = cc.load_json(fn)
            pts.update({int(k): float(v) for k, v in js["points"].items()})
    if not pts:
        return None
    k = np.array(sorted(pts), dtype=np.int64)
    return k, np.array([pts[x] for x in k])


def price_at(series, ts):
    """Price for each time in ts: last point at or before t if at most PRICE_PREV_MAX old, else the nearest
    point on either side.  Returns (price, |distance| in seconds)."""
    k, v = series
    ts = np.asarray(ts, dtype=np.int64)
    i = np.searchsorted(k, ts, side="right") - 1
    prev_ok = (i >= 0) & (ts - k[np.clip(i, 0, len(k) - 1)] <= PRICE_PREV_MAX)
    ip = np.clip(i, 0, len(k) - 1)
    inext = np.clip(i + 1, 0, len(k) - 1)
    d_prev = np.where(i >= 0, ts - k[ip], np.iinfo(np.int64).max)
    d_next = np.where(i + 1 < len(k), k[inext] - ts, np.iinfo(np.int64).max)
    use_next = (~prev_ok) & (d_next < d_prev)
    idx = np.where(use_next, inext, ip)
    dist = np.where(use_next, d_next, d_prev)
    return v[idx], dist


# ------------------------------------------------------------------ envelopes and the zero-delay condition

def envelope(t, a, us):
    """[(E(u), window start)] for half-open windows [s, s+u), s at a transfer time (vectorized)."""
    n = len(t)
    S = np.concatenate([[0.0], np.cumsum(a)])
    idx = np.arange(n)
    out = []
    for u in us:
        j = np.searchsorted(t, t + u, side="left")
        w = S[j] - S[idx]
        k = int(np.argmax(w))
        out.append((float(w[k]), int(t[k])))
    return out


def group_times(t, a):
    """Unique times and the total amount at each."""
    T, inv = np.unique(t, return_inverse=True)
    A = np.zeros(len(T))
    np.add.at(A, inv, a)
    return T, A


def pair_staircase(t, a):
    """Exact E as a staircase: gaps g_k (increasing) and E(g_k+) = largest amount over pairs with gap <= g_k,
    keeping only the gaps where the running maximum increases.  E(u) = value at the largest g_k < u."""
    T, A = group_times(t, a)
    P = np.concatenate([[0.0], np.cumsum(A)])
    best = {}
    m = len(T)
    gaps_all, amts_all = [], []
    for i in range(m):
        g = T[i:] - T[i]
        s = P[i + 1:] - P[i]
        # within one starting point, keep only the running-maximum records along increasing gaps
        rm = np.maximum.accumulate(s)
        keep = np.concatenate([[True], rm[1:] > rm[:-1]])
        gaps_all.append(g[keep])
        amts_all.append(rm[keep])
    g = np.concatenate(gaps_all)
    s = np.concatenate(amts_all)
    o = np.lexsort((-s, g))
    g, s = g[o], s[o]
    rm = np.maximum.accumulate(s)
    keep = np.concatenate([[True], rm[1:] > rm[:-1]])
    del best
    return g[keep].astype(float), rm[keep]


def E_from_staircase(stair, u):
    g, e = stair
    k = np.searchsorted(g, u, side="left") - 1  # largest gap strictly below u
    return float(e[k]) if k >= 0 else 0.0


def smallest_failing_gap(t, a, b, r):
    """Smallest gap t_j - t_i over pairs with A[i..j] > b + r (t_j - t_i); None if the condition holds.
    Also returns the amount and start time of that pair."""
    T, A = group_times(t, a)
    P = np.concatenate([[0.0], np.cumsum(A)])
    best = None
    for i in range(len(T)):
        g = T[i:] - T[i]
        if best is not None and g.size and g[0] >= best[0]:
            continue
        s = P[i + 1:] - P[i]
        viol = s > (b + r * g) * (1 + TOL)
        if viol.any():
            j = int(np.argmax(viol))
            if best is None or g[j] < best[0]:
                best = (float(g[j]), float(s[j]), int(T[i]))
    return best


def best_response(stair, E0, d):
    pts = [(0.0, float(E0))] + list(zip(map(float, stair[0]), map(float, stair[1])))
    return ac.best_bucket(pts, float(d))[2]


# ------------------------------------------------------------------ replays

def replay(t, a, params, usd=None):
    """Token bucket on a stream.  params = [(t_from, state, b, r)] sorted by t_from, state in
    {'unknown', 'disabled', 'enabled'}; the first entry starts at -inf.  Returns reject- and FIFO-model
    statistics, episodes and the transfers that exceed the tokens available."""
    n = len(t)
    usd = np.zeros(n) if usd is None else usd
    tf = [p[0] for p in params]
    pi = 0
    _, state, b, r = params[0]
    T = b if state == "enabled" else 0.0       # reject model: tokens available
    X = -b if state == "enabled" else 0.0      # FIFO model: backlog minus tokens
    last = None
    st = collections.Counter()
    val = collections.Counter()
    rej_eps, fifo_eps = [], []
    cur_rej, cur_fifo = None, None
    waits, flagged = [], []
    fills = np.full(n, np.nan)  # share of capacity drawn after each transfer (FIFO), NaN without a bucket
    max_fill, max_fill_t = 0.0, None
    busy = 0.0

    def advance(t_to):
        """Refill the bucket and clear the backlog under the current parameters from `last` to t_to;
        close finished episodes."""
        nonlocal T, X, cur_rej, cur_fifo, busy
        if last is None or state != "enabled":
            return
        dtc = t_to - last
        if dtc < 0:
            return
        if cur_rej is not None:
            t_full = last + (b - T) / r if r > 0 else math.inf
            if t_full <= t_to:
                cur_rej["end"] = t_full
                rej_eps.append(cur_rej)
                cur_rej = None
        if X > 0:
            t_clear = X / r if r > 0 else math.inf
            busy += min(dtc, t_clear)
            if cur_fifo is not None and t_clear <= dtc:
                cur_fifo["end"] = last + t_clear
                fifo_eps.append(cur_fifo)
                cur_fifo = None
        T = min(b, T + r * dtc)
        X = max(-b, X - r * dtc)

    for j in range(n):
        tj, aj, uj = float(t[j]), float(a[j]), float(usd[j])
        while pi + 1 < len(params) and tf[pi + 1] <= tj:
            tc = tf[pi + 1]
            if last is not None and tc > last:
                advance(tc)
                last = tc
            pi += 1
            _, st2, b2, r2 = params[pi]
            if st2 == "enabled":
                if state == "enabled":
                    T, X = min(T, b2), max(X, -b2)
                else:
                    T, X = b2, -b2
            else:
                # switched off (or unknown): backlog released, episodes closed at the change
                for ep, lst in ((cur_rej, rej_eps), (cur_fifo, fifo_eps)):
                    if ep is not None:
                        ep["end"] = tc
                        lst.append(ep)
                cur_rej, cur_fifo = None, None
                T, X = 0.0, 0.0
            state, b, r = st2, b2, r2
        if state == "unknown":
            st["n_unknown"] += 1
            val["unknown"] += aj
            last = tj
            continue
        if state == "disabled" or b <= 0:
            st["n_disabled"] += 1
            val["disabled"] += aj
            last = tj
            continue
        advance(tj)
        last = tj
        st["n_under"] += 1
        val["under"] += aj
        val["under_usd"] += uj
        # FIFO
        X = X + aj
        fill = (X + b) / b
        fills[j] = fill
        if fill > max_fill:
            max_fill, max_fill_t = fill, tj
        if X > TOL * b:
            st["fifo_n"] += 1
            val["fifo"] += aj
            val["fifo_usd"] += uj
            w = X / r if r > 0 else math.inf
            waits.append((w, aj))
            if cur_fifo is None:
                cur_fifo = {"start": tj, "n": 0, "value": 0.0, "usd": 0.0}
            cur_fifo["n"] += 1
            cur_fifo["value"] += aj
            cur_fifo["usd"] += uj
        # reject
        if aj > b * (1 + TOL):
            st["n_gt_capacity"] += 1
        if aj <= T * (1 + TOL) + 1e-12:
            T = max(0.0, T - aj)
        else:
            st["rej_n"] += 1
            val["rej"] += aj
            val["rej_usd"] += uj
            if cur_rej is None:
                cur_rej = {"start": tj, "n": 0, "value": 0.0, "usd": 0.0}
            cur_rej["n"] += 1
            cur_rej["value"] += aj
            cur_rej["usd"] += uj
            flagged.append({"t": int(tj), "utc": fmt_ts(tj), "amount": aj, "usd": uj,
                            "tokens_available": T, "capacity": b, "rate": r})
    # close open episodes at the end of the data
    if state == "enabled" and last is not None:
        if cur_rej is not None:
            cur_rej["end"] = last + (b - T) / r if r > 0 else math.inf
            rej_eps.append(cur_rej)
        if X > 0:
            busy += X / r if r > 0 else 0.0
            if cur_fifo is not None:
                cur_fifo["end"] = last + X / r if r > 0 else math.inf
                fifo_eps.append(cur_fifo)
    for lst in (rej_eps, fifo_eps):
        for ep in lst:
            ep["start_utc"], ep["end_utc"] = fmt_ts(ep["start"]), fmt_ts(ep["end"])
            ep["hours"] = (ep["end"] - ep["start"]) / 3600 if math.isfinite(ep["end"]) else None
    wv = [w for w, _ in waits]
    out = {
        "n_unknown": st["n_unknown"], "value_unknown": val["unknown"],
        "n_disabled": st["n_disabled"], "value_disabled": val["disabled"],
        "n_under_bucket": st["n_under"], "value_under_bucket": val["under"], "usd_under_bucket": val["under_usd"],
        "max_fill": max_fill, "max_fill_utc": fmt_ts(max_fill_t),
        "n_larger_than_capacity": st["n_gt_capacity"],
        "reject_n": st["rej_n"], "reject_value": val["rej"], "reject_usd": val["rej_usd"],
        "reject_episodes": len(rej_eps),
        "fifo_n": st["fifo_n"], "fifo_value": val["fifo"], "fifo_usd": val["fifo_usd"],
        "fifo_episodes": len(fifo_eps),
        "fifo_max_wait_h": (max(wv) / 3600) if wv else 0.0,
        "fifo_median_wait_h": (float(np.median(wv)) / 3600) if wv else 0.0,
        "fifo_backlogged_h": busy / 3600,
        "reject_episode_list": rej_eps, "fifo_episode_list": fifo_eps,
        "flagged": flagged,
        "_fills": fills,  # removed before writing; used for per-period statistics
    }
    return out


def check_against_core(t, a, b, r, rep):
    """Constant bucket: compare the FIFO replay with analysis_core.token_bucket_fifo (min-plus closed form)."""
    t0 = float(t[0])
    s = ac.token_bucket_fifo([float(x) - t0 for x in t], [float(x) for x in a], b, r)
    ok = (s.delayed_count == rep["fifo_n"]
          and abs(s.max_delay / 3600 - rep["fifo_max_wait_h"]) <= 1e-6 * max(1.0, rep["fifo_max_wait_h"]))
    return {"core_delayed_count": s.delayed_count, "core_max_delay_h": s.max_delay / 3600,
            "core_value_weighted_delay_h": s.value_weighted_delay / 3600, "agrees": bool(ok)}


# ------------------------------------------------------------------ bucket series

def param_series(hist, refined, amend, src, dst, token, side):
    """Bucket in force for lane src -> dst as [(t_from, state, b, r)] in token units, first entry at -inf
    ('unknown' before the lane's first record).  side 'out': source pool outbound (out_* columns of history
    row (src, dst)); side 'in': destination pool inbound lanes[dst][src].in (in_* columns of the same row).
    On-chain amendments (list of {from, to, enabled, b, r}) replace the documented value on [from, to)."""
    h = hist[(hist.src == src) & (hist.dst == dst) & (hist.token == token)].sort_values("commit_date")
    eff = refined.get(f"{src}|{dst}|{token}|{side}", {})
    out, prev = [], None
    for _, x in h.iterrows():
        if side == "out":
            val = (bool(x.out_enabled), float(x.out_cap), float(x.out_rate))
        else:
            if pd.isna(x.in_cap):
                continue
            val = (bool(x.in_enabled), float(x.in_cap), float(x.in_rate))
        if prev is not None and val == prev:
            continue
        t_from = eff.get(x.snapshot)
        if t_from is None:
            t_from = iso_ts(x.commit_date)
        out.append((float(t_from), "enabled" if val[0] else "disabled", val[1], val[2]))
        prev = val
    series = [(-math.inf, "unknown", 0.0, 0.0)] + out
    for am in amend.get(f"{src}|{dst}|{token}|{side}", []):
        series = splice(series, float(am["from"]), float(am["to"]),
                        ("enabled" if am["enabled"] else "disabled", float(am["b"]), float(am["r"])))
    return series


def splice(series, t0, t1, val):
    """Replace the series on [t0, t1) by val; the setting in force at t1 resumes at t1."""
    def at(tq):
        cur = series[0]
        for p in series:
            if p[0] <= tq:
                cur = p
        return cur
    resume = at(t1)
    out = [p for p in series if p[0] < t0 or p[0] >= t1]
    out.append((t0,) + val)
    if not any(p[0] == t1 for p in out):
        out.append((t1,) + resume[1:])
    out.sort(key=lambda p: p[0])
    # merge consecutive identical settings
    merged = []
    for p in out:
        if merged and merged[-1][1:] == p[1:]:
            continue
        merged.append(p)
    return merged


def regimes(series, t_end):
    """[(t_from, t_to, state, b, r)] for the entries after -inf."""
    out = []
    for k, p in enumerate(series):
        if p[0] == -math.inf:
            continue
        t_to = series[k + 1][0] if k + 1 < len(series) else t_end
        out.append((p[0], t_to, p[1], p[2], p[3]))
    return out


# ------------------------------------------------------------------ coverage

def lane_crawl_counts(src, dst, tok, t_window0, lane=None):
    tag = lane or f"{src}__{dst}__{tok}".replace("*", "_api")
    d = os.path.join(cc.DATA, "messages_lane", tag)
    if not os.path.isdir(d):
        return None
    state = cc.load_json(os.path.join(d, "state.json"))
    n_all, n_win = 0, 0
    pages = sorted(glob.glob(os.path.join(d, "page_*.json.gz")))
    if not pages and "messages_in_global_window" in state:
        # artifact copy: the raw pages are not shipped; their counts were recorded in state.json
        n_all, n_win = state["messages"], state["messages_in_global_window"]
    for fn in pages:
        with gzip.open(fn, "rt", encoding="utf-8") as f:
            page = json.load(f)
        for m in page["body"].get("data", []):
            n_all += 1
            ts = int(dt.datetime.strptime(m["sendTimestamp"][:19], "%Y-%m-%dT%H:%M:%S").replace(
                tzinfo=dt.timezone.utc).timestamp())
            if ts >= t_window0:
                n_win += 1
    return {"pages": state["pages_done"], "messages": n_all, "messages_in_global_window": n_win,
            "stop_reason": state.get("stop_reason"), "done": state.get("done"),
            "newest": state.get("newest_ts"), "oldest": state.get("oldest_ts"),
            "crawled_utc": state.get("last_update_utc")}


# ------------------------------------------------------------------ main

def side_block(tt, aa, uu, stair, E0, bk, price_now, label):
    """Zero-delay check, outflow bound and replay for one constant bucket."""
    b, r = bk["b"], bk["r"]
    res = {"b": b, "r": r, "refill_s": (b / r) if r > 0 else None,
           "b_usd_now": b * price_now if price_now else None,
           "r_usd_per_h_now": r * 3600 * price_now if price_now else None}
    fail = smallest_failing_gap(tt, aa, b, r)
    res["zero_delay"] = fail is None
    res["first_fail_gap_s"] = None if fail is None else fail[0]
    res["first_fail_amount"] = None if fail is None else fail[1]
    res["first_fail_window_start"] = None if fail is None else fmt_ts(fail[2])
    res["fails_at_report_u"] = [lab for lab, u in U_REPORT if b + r * u < E_from_staircase(stair, u) * (1 - TOL)]
    res["beta"] = {lab: ac.beta_bucket(b, r, d) for lab, d in D_REPORT}
    res["beta_over_E"] = {lab: ac.beta_bucket(b, r, d) / E_from_staircase(stair, d) for lab, d in D_REPORT}
    res["beta_usd_now"] = {lab: v * price_now for lab, v in res["beta"].items()} if price_now else None
    rep = replay(tt, aa, [(-math.inf, "enabled", b, r)], uu)
    res["replay"] = rep
    res["core_check"] = check_against_core(tt, aa, b, r, rep)
    # consistency: exact pair condition <=> no FIFO exceedance for a bucket that starts full
    res["pair_vs_replay_consistent"] = bool((fail is None) == (rep["fifo_n"] == 0))
    return res


def main():
    sel = cc.load_json(os.path.join(HERE, "selection.json"))
    df = pd.read_csv(os.path.join(cc.DERIVED, "transfers.csv.gz"), compression="gzip",
                     dtype={"amount_raw": str, "src_sel": str, "dst_sel": str})
    cur = pd.read_csv(os.path.join(cc.DERIVED, "lanes_current.csv"))
    hist = pd.read_csv(os.path.join(cc.DERIVED, "lanes_history.csv"))
    rp = os.path.join(cc.DERIVED, "param_changes_refined.json")
    refined = cc.load_json(rp).get("effective", {}) if os.path.exists(rp) else {}
    ap = os.path.join(cc.DATA, "onchain", "amendments.json")
    amend_js = cc.load_json(ap) if os.path.exists(ap) else {"amendments": {}}
    amend = amend_js.get("amendments", {})
    meta = cc.load_json(os.path.join(cc.DERIVED, "ranking_meta.json"))
    coin_of = meta["coin_of"]
    prices_now = cc.load_json(os.path.join(cc.DERIVED, "prices_current.json"))
    gstate = cc.load_json(os.path.join(cc.DATA, "messages_all", "state.json"))
    t_win0 = iso_ts(gstate["oldest_ts"][:19] + "Z")
    t_end = iso_ts(cc.load_json(os.path.join(cc.DATA, "lanes_history", "manifest.json"))["current"]["accessed_utc"])

    keys = [(L["src"], L["dst"], L["token"]) for L in sel["lanes"]]
    kset = set(keys)
    sub = df[[k in kset for k in zip(df.src, df.dst, df.token)]]
    series_cache = {}
    results = []
    for (src, dst, tok), L in zip(keys, sel["lanes"]):
        d = sub[(sub.src == src) & (sub.dst == dst) & (sub.token == tok)].sort_values(["send_ts", "message_id"])
        t = d.send_ts.to_numpy(dtype=np.int64)
        a = d.amount.to_numpy(dtype=float)
        n = len(t)
        res = {"lane": L.get("lane"), "src": src, "dst": dst, "token": tok, "why": L.get("why"), "n": int(n)}
        # coverage: lane crawl against the global crawl inside the global window
        g_in = int(((d.origin == "global") & (d.send_ts >= t_win0)).sum())
        lc = lane_crawl_counts(src, dst, tok, t_win0, L.get("lane"))
        res["coverage"] = {"lane_crawl": lc, "global_crawl_in_window": g_in,
                           "transfers_in_window": int((d.send_ts >= t_win0).sum()),
                           "transfers_before_window": int((d.send_ts < t_win0).sum())}
        if n == 0:
            results.append(res)
            continue
        rt = d.receipt_ts.fillna(d.send_ts).to_numpy(dtype=np.int64)
        res.update({"first": fmt_ts(t[0]), "last": fmt_ts(t[-1]), "span_days": (t[-1] - t[0]) / 86400,
                    "total": float(a.sum()), "max_single": float(a.max()), "median_single": float(np.median(a)),
                    "status_counts": dict(collections.Counter(d.status)),
                    "n_no_receipt": int(d.receipt_ts.isna().sum()),
                    "receipt_delay_s": {"p50": float(np.median(rt - t)), "p99": float(np.percentile(rt - t, 99)),
                                        "max": float((rt - t).max())}})
        # prices
        coin = coin_of.get(tok)
        ps = price_series(coin) if coin else None
        pnow = (prices_now["prices"].get(tok) or {}).get("usd")
        res["price"] = {"coin": coin, "now_usd": pnow, "now_source": prices_now["source"],
                        "now_accessed_utc": prices_now["accessed_utc"]}
        if ps is not None:
            p, dist = price_at(ps, t)
            usd = a * p
            res["price"].update({"n_points": int(len(ps[0])), "first_point": fmt_ts(ps[0][0]),
                                 "last_point": fmt_ts(ps[0][-1]),
                                 "share_value_price_gt_36h": float((usd * (dist > PRICE_PREV_MAX)).sum() / usd.sum()),
                                 "max_price_distance_h": float(dist.max() / 3600)})
            res["total_usd"], res["max_single_usd"] = float(usd.sum()), float(usd.max())
        else:
            usd = np.zeros(n)
        o = np.argsort(rt, kind="stable")
        streams = {"out": (t, a, usd), "in": (rt[o], a[o], usd[o])}
        # envelopes
        for side in ("out", "in"):
            tt, aa, uu = streams[side]
            stair = pair_staircase(tt, aa)
            E0 = float(group_times(tt, aa)[1].max())
            env = envelope(tt, aa, [u for _, u in U_REPORT])
            Eu = {lab: {"E": e, "start": fmt_ts(s0)} for (lab, _), (e, s0) in zip(U_REPORT, env)}
            # three computations of E(u) must agree: vectorized, exact staircase, analysis_core
            agree = all(abs(E_from_staircase(stair, u) - Eu[lab]["E"]) <= 1e-9 * max(1.0, Eu[lab]["E"])
                        for lab, u in U_REPORT)
            core = all(abs(ac.envelope_events(list(map(float, tt)), list(map(float, aa)), float(u)) - Eu[lab]["E"])
                       <= 1e-9 * max(1.0, Eu[lab]["E"]) for lab, u in U_REPORT)
            blk = {"E0": E0, "E": Eu, "E_checks_agree": bool(agree and core),
                   "E_usd": {lab: envelope(tt, uu, [u])[0][0] for lab, u in U_REPORT} if ps is not None else None,
                   "E0_usd": float(group_times(tt, uu)[1].max()) if ps is not None else None,
                   "best_zero_delay": {lab: best_response(stair, E0, u) for lab, u in D_REPORT},
                   "n_stair_points": int(len(stair[0]))}
            series_cache[(src, dst, tok, side)] = (stair, E0)
            res[f"{side}_env"] = blk
        # current buckets
        c = cur[(cur.src == src) & (cur.dst == dst) & (cur.token == tok)]
        cb = {}
        if len(c):
            c = c.iloc[0]
            cb["out"] = {"enabled": bool(c.out_enabled), "b": float(c.out_cap), "r": float(c.out_rate),
                         "status": c.status, "pool_version": c.src_pool_version}
            if not pd.isna(c.in_cap):
                cb["in"] = {"enabled": bool(c.in_enabled), "b": float(c.in_cap), "r": float(c.in_rate),
                            "decimals_rule": c.in_decimals_rule, "pool_version": c.dst_pool_version}
        res["current_bucket"] = cb
        for side in ("out", "in"):
            bk = cb.get(side)
            if not bk or not bk["enabled"] or bk["b"] <= 0:
                continue
            tt, aa, uu = streams[side]
            stair, E0 = series_cache[(src, dst, tok, side)]
            res[f"{side}_current"] = side_block(tt, aa, uu, stair, E0, bk, pnow, side)
        # buckets in force
        for side in ("out", "in"):
            ser = param_series(hist, refined, amend, src, dst, tok, side)
            ser_doc = param_series(hist, refined, {}, src, dst, tok, side)
            tt, aa, uu = streams[side]
            res[f"{side}_inforce_doc"] = replay(tt, aa, ser_doc, uu) if ser_doc else None
            rep_if = replay(tt, aa, ser, uu) if ser else None
            regs = []
            for (t0, t1, stt, b, r) in regimes(ser, max(t_end, int(tt[-1]) + 1)):
                m = (tt >= t0) & (tt < t1)
                amx = amend.get(f"{src}|{dst}|{tok}|{side}", [])
                source = "documentation"
                if amx:  # the on-chain window is the span of the amendment intervals
                    w0, w1 = min(float(x["from"]) for x in amx), max(float(x["to"]) for x in amx)
                    if t0 < w1 and t1 > w0:
                        if t0 >= w0 and t1 <= w1:
                            source = "pool state on chain"
                        elif t0 >= w0:
                            source = f"pool state on chain to {fmt_ts(w1)[:10]}, then documentation"
                        elif t1 <= w1:
                            source = f"documentation, pool state on chain from {fmt_ts(w0)[:10]}"
                        else:
                            source = f"documentation, pool state on chain {fmt_ts(w0)[:10]} to {fmt_ts(w1)[:10]}"
                rg = {"from": fmt_ts(t0), "to": fmt_ts(t1), "from_ts": t0, "to_ts": t1, "state": stt, "b": b,
                      "r": r, "refill_s": (b / r) if (stt == "enabled" and r > 0) else None,
                      "source": source,
                      "n": int(m.sum()), "value": float(aa[m].sum()), "usd": float(uu[m].sum())}
                if ps is not None and stt == "enabled":
                    p0, dist0 = price_at(ps, [int(max(t0, ps[0][0]))])
                    rg["price_from_usd"] = float(p0[0])
                    rg["price_from_distance_h"] = float(abs(t0 - max(t0, ps[0][0])) / 3600 + dist0[0] / 3600)
                    rg["b_usd_at_from"] = b * float(p0[0])
                    rg["r_usd_per_h_at_from"] = r * 3600 * float(p0[0])
                if pnow and stt == "enabled":
                    rg["b_usd_now"] = b * pnow
                    rg["r_usd_per_h_now"] = r * 3600 * pnow
                if stt == "enabled" and m.sum() > 0:
                    fail = smallest_failing_gap(tt[m], aa[m], b, r)
                    rg["zero_delay"] = fail is None
                    rg["first_fail_gap_s"] = None if fail is None else fail[0]
                    fl_ = rep_if["_fills"][m]
                    rg["max_fill"] = float(np.nanmax(fl_)) if np.isfinite(fl_).any() else None
                    rg["n_fill_ge_095"] = int((fl_ >= 0.95).sum())
                regs.append(rg)
            res[f"{side}_regimes"] = regs
            res[f"{side}_amended"] = bool(amend.get(f"{src}|{dst}|{tok}|{side}"))
            res[f"{side}_inforce"] = rep_if
        for k, v in res.items():  # drop the per-transfer arrays used above
            if isinstance(v, dict):
                v.pop("_fills", None)
                if isinstance(v.get("replay"), dict):
                    v["replay"].pop("_fills", None)
        results.append(res)
        oc = res.get("out_current") or {}
        oi = res.get("out_inforce") or {}
        print(f"{src}->{dst} {tok} n={n} {res['first'][:10]}..{res['last'][:10]} "
              f"cur: zero_delay={oc.get('zero_delay')} gap={oc.get('first_fail_gap_s')} rej={oc.get('replay', {}).get('reject_n')} "
              f"| inforce: rej={oi.get('reject_n')} eps={oi.get('reject_episodes')} fill={oi.get('max_fill')} "
              f"| Echk={res['out_env']['E_checks_agree']},{res['in_env']['E_checks_agree']} "
              f"core={oc.get('core_check', {}).get('agrees')} pair={oc.get('pair_vs_replay_consistent')}", flush=True)
    out = {"built_utc": cc.utcnow(), "selection_rule": sel.get("rule"), "global_window_start": fmt_ts(t_win0),
           "global_crawl_state": {k: gstate.get(k) for k in ("pages_done", "messages", "newest_ts", "oldest_ts",
                                                             "done", "last_update_utc")},
           "current_snapshot_accessed_utc": fmt_ts(t_end),
           "amendments_source": amend_js.get("source"), "results": results}
    with open(os.path.join(cc.DERIVED, "flows_results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1, default=str)


if __name__ == "__main__":
    main()
