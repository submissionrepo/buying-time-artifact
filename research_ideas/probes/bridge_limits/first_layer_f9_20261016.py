"""F9: placement (Theorem 2) with several downstream rules in tandem, 2026-10-16.

Discrete slots 0..T-1.  Cumulative curves are indexed by the number of slots d:
f(d) is the value released in slots 0..d-1, so f(0) = 0.  A stage maps per-slot
inflow to per-slot release; stages in tandem act within the same slot.
  bucket (b, r): tokens start at b and refill r (capped at b) before every slot
      after the first; curve b + min(r, b)(d - 1) for d >= 1;
  window (C, w): greedy sliding cap, any w consecutive slots release at most C;
      curve C ceil(d / w);
  hold H: every request leaves exactly H slots after it arrives; curve
      delta_H(d) = 0 for d <= H and +infinity for d > H.
The failing party injects at most W in total.  Theorem 2 (corrected form):
  L_i(d) <= min{W, (beta_1 (x) ... (x) beta_k)(d)} <= min{W, min_j beta_j(d)},
with (x) the min-plus convolution over the rules at stage i or downstream that the
failing party does not control.  The first inequality is an equality for greedy
time-invariant shapers and holds (inject W at once); the second is an equality for
concave curves and can be strict for crossing staircase curves.

Checks (exact integers):
  (a) bucket tandems of 2-3 stages: the release of a burst equals the smallest
      single curve at every d (concave curves);
  (b) tandems of 2-3 stages mixing buckets, windows and holds, every order: the
      release of a burst equals the discrete min-plus convolution of the stage
      curves, capped at W (W large and W small);
  (c) window tandems: the release never exceeds the smallest single curve; cases
      where it is strictly smaller are counted and the first ones reported (they
      refute the earlier form "equal to the tightest rule");
  (d) two-stage tandems, every injection pattern over 5 slots with amounts 0..3 and
      total <= W: the release equals the min-plus convolution of the input with the
      two curves and never exceeds min{W, convolution of the curves}; the burst W at
      slot 0 attains that bound at every d;
  (e) pipelines of 3 stages, each stage with no rule or one rule that is either
      independent or controlled (switched off) by the failing party: injection at
      stage i releases min{W, convolution over the independent rules at stages >= i},
      and W at once when there is none.  Named instance (Corollary 2.1): a lock-mint
      bridge whose only rule sits at source escrow release; a failure injected at the
      destination mint releases W at once, a failure injected at escrow release is
      held to the bucket curve.
"""
import itertools
import json
import sys

INF = 10 ** 12


def bucket_stage(inflow, b, r):
    out, tokens, backlog = [], b, 0
    for t, x in enumerate(inflow):
        if t > 0:
            tokens = min(b, tokens + r)
        backlog += x
        rel = min(tokens, backlog)
        tokens -= rel
        backlog -= rel
        out.append(rel)
    return out


def window_stage(inflow, C, w):
    out, backlog = [], 0
    for t, x in enumerate(inflow):
        backlog += x
        used = sum(out[max(0, t - w + 1):t])
        rel = min(backlog, max(0, C - used))
        backlog -= rel
        out.append(rel)
    return out


def hold_stage(inflow, H):
    return [inflow[t - H] if t >= H else 0 for t in range(len(inflow))]


def run(stage, inflow):
    kind, p = stage
    if kind == "bucket":
        return bucket_stage(inflow, *p)
    if kind == "window":
        return window_stage(inflow, *p)
    return hold_stage(inflow, p[0])


def curve(stage, T):
    kind, p = stage
    c = [0]
    for d in range(1, T + 1):
        if kind == "bucket":
            b, r = p
            c.append(b + min(r, b) * (d - 1))
        elif kind == "window":
            C, w = p
            c.append(C * (-(-d // w)))
        else:
            c.append(0 if d <= p[0] else INF)
    return c


def conv(f, g):
    return [min(f[s] + g[d - s] for s in range(d + 1)) for d in range(len(f))]


def conv_all(curves):
    out = curves[0]
    for c in curves[1:]:
        out = conv(out, c)
    return out


def cumulative(flow):
    c = [0]
    for x in flow:
        c.append(c[-1] + x)
    return c


def tandem(stages, inflow):
    flow = inflow
    for s in stages:
        flow = run(s, flow)
    return cumulative(flow)


BUCKETS = [("bucket", p) for p in [(1, 1), (2, 1), (3, 2), (2, 3), (5, 3)]]
WINDOWS = [("window", p) for p in [(1, 1), (1, 2), (2, 2), (2, 3), (3, 2)]]
HOLDS = [("hold", (1,)), ("hold", (2,))]


def main():
    T = 8
    stats = {}
    fails = []

    # (a) bucket tandems equal the smallest single curve
    n = 0
    for k in (2, 3):
        for combo in itertools.product(BUCKETS, repeat=k):
            for W in (10 ** 6, 7):
                got = tandem(combo, [W] + [0] * (T - 1))
                curves = [curve(s, T) for s in combo]
                for d in range(1, T + 1):
                    n += 1
                    want = min(W, min(c[d] for c in curves))
                    if got[d] != want:
                        fails.append(("a", combo, W, d, got[d], want))
    stats["a_bucket_tandem_equals_min"] = n

    # (b) mixed tandems equal the min-plus convolution, every order
    n = 0
    mixed = BUCKETS + WINDOWS + HOLDS
    for k in (2, 3):
        for combo in itertools.product(mixed, repeat=k):
            cv = conv_all([curve(s, T) for s in combo])
            for W in (10 ** 6, 5):
                got = tandem(combo, [W] + [0] * (T - 1))
                for d in range(1, T + 1):
                    n += 1
                    if got[d] != min(W, cv[d]):
                        fails.append(("b", combo, W, d, got[d], min(W, cv[d])))
    stats["b_mixed_tandem_equals_convolution"] = n

    # (c) window tandems: never above the smallest curve; count strict cases
    n, strict, examples = 0, 0, []
    for k in (2, 3):
        for combo in itertools.product(WINDOWS, repeat=k):
            got = tandem(combo, [10 ** 6] + [0] * (T - 1))
            curves = [curve(s, T) for s in combo]
            for d in range(1, T + 1):
                n += 1
                m = min(c[d] for c in curves)
                if got[d] > m:
                    fails.append(("c", combo, d, got[d], m))
                elif got[d] < m:
                    strict += 1
                    if len(examples) < 4:
                        examples.append({"stages": [list(s[1]) for s in combo], "d": d,
                                         "released": got[d], "smallest_single_curve": m})
    stats["c_window_tandem_cases"] = n
    stats["c_strictly_below_smallest_curve"] = strict

    # (d) every injection pattern, two-stage tandems
    n = 0
    Td, W = 5, 6
    small = [("bucket", (2, 1)), ("bucket", (3, 2)), ("window", (1, 1)), ("window", (2, 2)),
             ("window", (2, 3)), ("hold", (1,))]
    patterns = [p for p in itertools.product(range(4), repeat=Td) if sum(p) <= W]
    for combo in itertools.product(small, repeat=2):
        curves = [curve(s, Td) for s in combo]
        cv = conv_all(curves)
        bound = [min(W, x) for x in cv]
        burst = tandem(combo, [W] + [0] * (Td - 1))
        for d in range(1, Td + 1):
            n += 1
            if burst[d] != bound[d]:
                fails.append(("d-burst", combo, d, burst[d], bound[d]))
        for p in patterns:
            got = tandem(combo, list(p))
            io = conv_all([cumulative(p)] + curves)
            for d in range(1, Td + 1):
                n += 1
                if got[d] != io[d] or got[d] > bound[d]:
                    fails.append(("d", combo, p, d, got[d], io[d], bound[d]))
    stats["d_patterns"] = len(patterns)
    stats["d_cases"] = n

    # (e) pipelines with independent and controlled rules
    n = 0
    options = [None] + [(s, ctl) for s in [("bucket", (2, 1)), ("window", (2, 2)), ("hold", (1,))]
                        for ctl in (False, True)]
    for pipe in itertools.product(options, repeat=3):
        for i in range(3):
            for W in (10 ** 6, 5):
                # simulation: the request enters at stage i; controlled rules are switched off
                flow = [W] + [0] * (T - 1)
                for j in range(i, 3):
                    if pipe[j] is not None and not pipe[j][1]:
                        flow = run(pipe[j][0], flow)
                got = cumulative(flow)
                active = [curve(pipe[j][0], T) for j in range(i, 3) if pipe[j] is not None and not pipe[j][1]]
                want = [0] + [W] * T if not active else [min(W, x) for x in conv_all(active)]
                for d in range(1, T + 1):
                    n += 1
                    if got[d] != want[d]:
                        fails.append(("e", pipe, i, W, d, got[d], want[d]))
    # Corollary 2.1 instance: forward pipeline (lock event, verification, destination mint) has
    # no rule; reverse pipeline (burn event, verification, source escrow release) has a bucket.
    forward = [None, None, None]
    reverse = [None, None, (("bucket", (2, 1)), False)]
    W = 9
    mint_fail = cumulative([W] + [0] * (T - 1))  # injected at forward stage 3: nothing downstream
    escrow_fail = tandem([reverse[2][0]], [W] + [0] * (T - 1))
    for d in range(1, T + 1):
        n += 2
        if mint_fail[d] != W:
            fails.append(("e-mint", d, mint_fail[d]))
        if escrow_fail[d] != min(W, curve(("bucket", (2, 1)), T)[d]):
            fails.append(("e-escrow", d, escrow_fail[d]))
    assert all(x is None for x in forward)
    stats["e_pipeline_cases"] = n

    stats["cases"] = sum(v for k, v in stats.items() if k.endswith("cases") or k.startswith(("a_", "b_")))
    print(json.dumps({"stats": stats, "failures": len(fails), "first_failures": [str(f) for f in fails[:3]],
                      "strict_examples": examples}))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
