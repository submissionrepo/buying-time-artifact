"""Core analysis functions for the bridge withdrawal-limits paper.

Everything works on value streams in a common unit (USD): either event lists
(time in seconds, value) or fixed-width bins.  Functions are exact on the input
they receive; floating point only enters through the input values.

Notation follows the paper:
E(u)      empirical window envelope of a stream (max value in any window of length u)
beta(d)   compromise response of a rule (max unauthorized release within d)
"""
from __future__ import annotations

import bisect
import math
from collections import deque
from dataclasses import dataclass
from typing import Iterable, Sequence


# ---------------------------------------------------------------- envelopes

def envelope_events(times: Sequence[float], values: Sequence[float], u: float) -> float:
    """Max total value of events with time in [s, s + u) over all s (two pointers).

    Events at identical times are summed.  Windows are half open, so u = 0 gives 0;
    the largest single event is envelope at u -> 0+, returned by largest_event().
    """
    if u <= 0 or not times:
        return 0.0
    order = sorted(range(len(times)), key=lambda i: times[i])
    t = [times[i] for i in order]
    v = [values[i] for i in order]
    best = 0.0
    acc = 0.0
    j = 0
    for i in range(len(t)):
        acc += v[i]
        while t[j] <= t[i] - u:
            acc -= v[j]
            j += 1
        best = max(best, acc)
    return best


def largest_event(values: Sequence[float]) -> float:
    return max(values) if values else 0.0


def envelope_bins(bins: Sequence[float], k: int) -> float:
    """Max sum over k consecutive bins (k >= 1)."""
    if k <= 0 or not bins:
        return 0.0
    k = min(k, len(bins))
    acc = sum(bins[:k])
    best = acc
    for i in range(k, len(bins)):
        acc += bins[i] - bins[i - k]
        best = max(best, acc)
    return best


def subbin_bounds(E_bin: float, k: int) -> tuple[float, float]:
    """Bounds on the envelope at a window of 1/k of a bin from the one-bin envelope:
    E(bin/k) lies in [E(bin)/k, E(bin)] by monotonicity and subadditivity."""
    return E_bin / k, E_bin


def envelope_quantile_bins(bins: Sequence[float], k: int, q: float) -> float:
    """q-quantile of the k-bin rolling sum (a percentile envelope, not a worst case)."""
    if k <= 0 or len(bins) < k:
        return 0.0
    sums = []
    acc = sum(bins[:k])
    sums.append(acc)
    for i in range(k, len(bins)):
        acc += bins[i] - bins[i - k]
        sums.append(acc)
    sums.sort()
    idx = min(len(sums) - 1, max(0, int(math.ceil(q * len(sums))) - 1))
    return sums[idx]


# ---------------------------------------------------------------- concave hull and best bucket

def upper_concave_hull(points: Sequence[tuple[float, float]]) -> list[tuple[float, float]]:
    pts = sorted(set(points))
    hull: list[tuple[float, float]] = []
    for p in pts:
        while len(hull) >= 2:
            (x1, y1), (x2, y2) = hull[-2], hull[-1]
            # remove hull[-1] if it lies on or below the chord hull[-2] -> p
            if (y2 - y1) * (p[0] - x1) <= (p[1] - y1) * (x2 - x1):
                hull.pop()
            else:
                break
        hull.append(p)
    return hull


def hull_value(hull: Sequence[tuple[float, float]], x: float) -> float:
    if x <= hull[0][0]:
        return hull[0][1]
    for (x1, y1), (x2, y2) in zip(hull, hull[1:]):
        if x1 <= x <= x2:
            return y1 + (y2 - y1) * (x - x1) / (x2 - x1)
    return hull[-1][1]


def best_bucket(points: Sequence[tuple[float, float]], D: float) -> tuple[float, float, float]:
    """Smallest b + r D over buckets with b + r u >= E(u) at the given points (Proposition 7).
    Returns (b, r, value).  points: (u, E(u)) including (0, E(0+))."""
    hull = upper_concave_hull(points)
    val = hull_value(hull, D)
    # supporting line: slope of the hull segment containing D (right segment at a vertex)
    r = 0.0
    for (x1, y1), (x2, y2) in zip(hull, hull[1:]):
        if x1 <= D < x2:
            r = (y2 - y1) / (x2 - x1)
            break
    b = val - r * D
    return b, r, val


# ---------------------------------------------------------------- rule simulations on legitimate streams

@dataclass
class ShaperStats:
    delayed_value: float      # value released later than requested
    delayed_count: int
    max_delay: float          # seconds
    value_weighted_delay: float  # sum(value * delay) / sum(value)


def token_bucket_fifo(times: Sequence[float], values: Sequence[float], b: float, r: float) -> ShaperStats:
    """FIFO fluid shaper with a token bucket (capacity b, refill r per second), full at the start.

    Min-plus closed form: with cumulative request y_i through request i and
    c_j = A(t_j-) + b - r t_j, the last unit of request i is released at
    max(t_i, (y_i - min_{j<=i} c_j) / r).  Requests at equal times are taken in
    input order.  r = 0 means no refill: a request is released only if it fits.
    """
    order = sorted(range(len(times)), key=lambda i: (times[i], i))
    A_before = 0.0
    m = math.inf
    delayed_value = 0.0
    delayed_count = 0
    max_delay = 0.0
    wsum = 0.0
    vsum = 0.0
    for i in order:
        t, v = times[i], values[i]
        m = min(m, A_before + b - r * t)
        y = A_before + v
        if r > 0:
            release = max(t, (y - m) / r)
        else:
            release = t if y <= m + 1e-12 else math.inf
        delay = release - t
        if delay > 1e-9:
            delayed_value += v
            delayed_count += 1
        max_delay = max(max_delay, delay)
        wsum += v * (delay if math.isfinite(delay) else 0.0)
        vsum += v
        A_before = y
    return ShaperStats(delayed_value, delayed_count, max_delay, wsum / vsum if vsum else 0.0)


def sliding_cap_usage(times: Sequence[float], values: Sequence[float], C: float, w: float) -> dict:
    """Usage of a sliding cap C over window w by a legitimate stream (no queueing):
    max and quantiles of the w-window sum, and the value that would exceed the cap
    if the cap had been binding (excess counted per event, greedy order)."""
    order = sorted(range(len(times)), key=lambda i: times[i])
    window = deque()
    acc = 0.0
    over_value = 0.0
    over_count = 0
    peak = 0.0
    for i in order:
        t, v = times[i], values[i]
        while window and window[0][0] <= t - w:
            acc -= window.popleft()[1]
        if acc + v > C + 1e-9:
            over_value += v
            over_count += 1
        else:
            window.append((t, v))
            acc += v
        peak = max(peak, acc)
    return {"peak_counted": peak, "over_value": over_value, "over_count": over_count}


# ---------------------------------------------------------------- compromise responses (Theorem 3)

def beta_bucket(b: float, r: float, d: float, W: float = math.inf) -> float:
    return min(W, b + r * d) if d > 0 else 0.0


def beta_sliding(C: float, w: float, d: float, W: float = math.inf) -> float:
    return min(W, C * math.ceil(d / w)) if d > 0 else 0.0


def beta_calendar(C: float, w: float, d: float, W: float = math.inf) -> float:
    return min(W, C * (math.ceil(d / w) + 1)) if d > 0 else 0.0


def beta_time_lock(H: float, d: float, W: float) -> float:
    return W if d >= H else 0.0


def beta_auto_release(base: float, A: float, d: float, W: float) -> float:
    """base: the underlying rule's response at d (for d < A)."""
    return W if d >= A else min(W, base)


def beta_percentage(p: float, w: float, d: float, W: float, calendar: bool = True) -> float:
    if d <= 0:
        return 0.0
    n = math.ceil(d / w) + (1 if calendar else 0)
    return W * (1.0 - (1.0 - p) ** n)


def expected_loss(beta_fn, lags: Iterable[float], W: float) -> float:
    lags = list(lags)
    return sum(min(W, beta_fn(D)) for D in lags) / len(lags) if lags else float("nan")


# ---------------------------------------------------------------- exact burstiness and best bucket

def burstiness(times: Sequence[float], values: Sequence[float], r: float) -> float:
    """Smallest bucket capacity B(r) that, with refill r per second and a full start,
    delays no request of the stream: B(r) = max over windows [t_i, t_j] of
    (requests in the window) - r (t_j - t_i), with single requests included (i = j).
    Exact, O(n log n) for the sort.  Requests at equal times are summed in order."""
    order = sorted(range(len(times)), key=lambda i: (times[i], i))
    best = 0.0
    run_min = math.inf   # min over i <= j of (A(t_i-) - r t_i)
    A = 0.0
    for i in order:
        t, v = times[i], values[i]
        run_min = min(run_min, A - r * t)
        A += v
        best = max(best, A - r * t - run_min)
    return best


def best_bucket_exact(times: Sequence[float], values: Sequence[float], D: float,
                      r_hi: float | None = None, iters: int = 200) -> tuple[float, float, float]:
    """min over r >= 0 of B(r) + r D (B convex in r), by golden-section search.
    Returns (b, r, value) with b = B(r)."""
    if r_hi is None:
        span = (max(times) - min(times)) if len(times) > 1 else 1.0
        r_hi = 2.0 * sum(values) / max(span, 1.0) + max(values) / max(D, 1.0)
    lo, hi = 0.0, r_hi
    g = (math.sqrt(5) - 1) / 2
    f = lambda r: burstiness(times, values, r) + r * D
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
    b = burstiness(times, values, r)
    # compare with the endpoints in case the minimum sits at r = 0
    b0 = burstiness(times, values, 0.0)
    if b0 <= b + r * D:
        return b0, 0.0, b0
    return b, r, b + r * D
