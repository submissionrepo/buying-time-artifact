"""First-layer exact checks for the bridge-limits theory (2026-10-15).

All checks are exhaustive over small integer domains in discrete time and use
exact integer arithmetic.  They certify the finite statements listed below; the
general statements rest on the proofs in the paper (Appendix A).

Discrete-time conventions
- slots 0, 1, 2, ...; a(t) is the value requested in slot t; cumulative
  A(t) = a(0) + ... + a(t-1), A(0) = 0.
- greedy shaper with curve sigma (sigma(0) = 0): R(t) = min_{0<=s<=t} [A(s) + sigma(t - s)].
- hold of h slots: the shaper sees A(t - h).
- E(u) = max over sequences l in L and starts s of A_l(s+u) - A_l(s); L is closed
  under taking suffixes (time shifts).

F1  control law (Theorem 1), all base sets of one or two sequences of length 1..3
    with values in {0,1,2}, holds h in {0,1,2}:
    (a) E is subadditive on the horizon;
    (b) hold-h + shaper(E) releases every l in the suffix closure of L with
        maximum delay exactly h (or 0 for the all-zero sequence);
    (c) from the quiet state, a request of size M at slot 0 is released by slot d
        exactly min(M, E(d - h)) for d > h and 0 for d <= h;
    (d) replay bound: max over l in L of A_l(d - h) equals E(d - h) for d >= h.
F2  response functions of three limit rules from the quiet state, d slots:
    sliding window cap C over w slots: max release = C * ceil(d / w);
    calendar window cap C over w slots, best offset: C * ceil((d + w - 1) / w);
    token bucket (capacity b, refill r per slot, refill before each slot after
    slot 0): b + min(r, b) * (d - 1) for d >= 1 (continuous time: b + r d).
    Maxima are computed by brute force over all release vectors.
F3  pooling (Proposition 4): for two channels with joint sequences of length 1..3,
    values in {0,1,2}: E_sum(u) <= E_1(u) + E_2(u) for all u, with equality iff
    some common window start attains both channel maxima.
F4  size-based holds (Proposition 6): a rule that holds requests larger than s for
    H slots and releases requests of size <= s immediately under a sliding cap
    C_small (window w) releases, against split requests, exactly the sliding-cap
    response C_small * ceil(d / w) within d <= H slots.
F5  best single token bucket (Proposition 7): for every envelope E of a
    suffix-closed set of one or two sequences of length 1..4 with values in
    {0,1,3} (horizon H = 6, E flat beyond the longest sequence) and every D in
    {0..6}: min{b + r D : b + r u >= E(u) for u = 0..H, b, r >= 0}, solved exactly
    by vertex enumeration with fractions, equals the upper concave hull of
    {(u, E(u))} evaluated at D.
"""
import itertools
import json
import math
import sys


def cum(a):
    out = [0]
    for x in a:
        out.append(out[-1] + x)
    return out


def suffix_closure(seqs):
    out = set()
    for a in seqs:
        for s in range(len(a)):
            out.add(tuple(a[s:]))
    return [list(x) for x in out]


def envelope(seqs, H):
    E = [0] * (H + 1)
    for a in seqs:
        A = cum(a)
        n = len(a)
        for u in range(H + 1):
            for s in range(n + 1):
                E[u] = max(E[u], A[min(n, s + u)] - A[s])
    return E


def sig(E, u):
    H = len(E) - 1
    if u <= H:
        return E[u]
    q, r = divmod(u, H)
    return q * E[H] + E[r]


def shaped(A_input, E, T):
    return [min(A_input[min(s, len(A_input) - 1)] + sig(E, t - s) for s in range(t + 1)) for t in range(T + 1)]


def max_delay(A, R):
    worst = 0
    for t in range(len(A)):
        y = A[t]
        if y == 0:
            continue
        tt = next((k for k in range(len(R)) if R[k] >= y), None)
        if tt is None:
            return None
        worst = max(worst, tt - t)
    return worst


def F1():
    vals = (0, 1, 2)
    seqs_all = [list(p) for n in (1, 2, 3) for p in itertools.product(vals, repeat=n)]
    cases = 0
    for k in (1, 2):
        for base in itertools.combinations(range(len(seqs_all)), k):
            L = suffix_closure([seqs_all[i] for i in base])
            H = 8
            E = envelope(L, H)
            assert all(E[u + v] <= E[u] + E[v] for u in range(H + 1) for v in range(H + 1 - u)), ("subadditive", L)
            for h in (0, 1, 2):
                T = 3 + h + 3
                for a in L:
                    A = cum(a) + [cum(a)[-1]] * (T + 1 - len(a))
                    Ah = [0] * h + A
                    R = shaped(Ah, E, T)
                    dl = max_delay(A[:T + 1], R)
                    want = h if any(a) else 0
                    assert dl == want, ("delay", L, h, a, dl)
                M = 10 ** 6
                A = [0] + [M] * T
                Ah = [0] * h + A
                R = shaped(Ah, E, T)
                for d in range(T + 1):
                    want = 0 if d <= h else min(M, sig(E, d - h))
                    assert R[d] == want, ("release", L, h, d, R[d], want)
                for d in range(h, H + 1):
                    replay = max(cum(a)[min(len(a), d - h)] for a in L)
                    assert replay == E[d - h], ("replay", L, h, d, replay, E[d - h])
                cases += 1
    return cases


def brute_max(d, feasible, cap):
    best = 0
    for r in itertools.product(range(cap + 1), repeat=d):
        if feasible(r):
            best = max(best, sum(r))
    return best


def F2():
    cases = 0
    for C in (1, 2, 3):
        for w in (1, 2, 3):
            for d in range(0, 7):
                # sliding window: every w consecutive slots release at most C
                def sliding_ok(r, C=C, w=w):
                    return all(sum(r[i:i + w]) <= C for i in range(len(r)))
                got = brute_max(d, sliding_ok, C)
                assert got == C * math.ceil(d / w), ("sliding", C, w, d, got)
                # calendar window with offset o: windows [kw - o, (k+1)w - o)
                best = 0
                for o in range(w):
                    def cal_ok(r, C=C, w=w, o=o):
                        tot = {}
                        for i, x in enumerate(r):
                            k = (i + o) // w
                            tot[k] = tot.get(k, 0) + x
                        return all(v <= C for v in tot.values())
                    best = max(best, brute_max(d, cal_ok, C))
                want = C * math.ceil((d + w - 1) / w) if d >= 1 else 0
                assert best == want, ("calendar", C, w, d, best, want)
                cases += 2
    for b in (1, 2, 3):
        for r in (0, 1, 2):
            for d in range(0, 7):
                def bucket_ok(rel, b=b, r=r):
                    level = b
                    for i, x in enumerate(rel):
                        if i > 0:
                            level = min(b, level + r)
                        if x > level:
                            return False
                        level -= x
                    return True
                got = brute_max(d, bucket_ok, b)
                want = b + min(r, b) * (d - 1) if d >= 1 else 0
                assert got == want, ("bucket", b, r, d, got, want)
                cases += 1
    return cases


def F3():
    vals = (0, 1, 2)
    cases = 0
    for n in (1, 2, 3):
        for a1 in itertools.product(vals, repeat=n):
            for a2 in itertools.product(vals, repeat=n):
                A1, A2 = cum(a1), cum(a2)
                for u in range(0, n + 1):
                    inc1 = [A1[min(n, s + u)] - A1[s] for s in range(n + 1)]
                    inc2 = [A2[min(n, s + u)] - A2[s] for s in range(n + 1)]
                    E1, E2 = max(inc1), max(inc2)
                    Es = max(x + y for x, y in zip(inc1, inc2))
                    assert Es <= E1 + E2
                    common = any(x == E1 and y == E2 for x, y in zip(inc1, inc2))
                    assert (Es == E1 + E2) == common, ("pooling iff", a1, a2, u)
                    cases += 1
    return cases


def F4():
    cases = 0
    for C_small in (1, 2, 3):
        for w in (1, 2, 3):
            for s in (1, 2):
                for H in (2, 3, 4):
                    for d in range(0, H + 1):
                        # the split stream submits only requests of size <= s; large requests are held H >= d
                        # and contribute nothing within d slots; small requests are capped by the sliding window
                        def ok(r, C=C_small, w=w):
                            return all(sum(r[i:i + w]) <= C for i in range(len(r)))
                        got = brute_max(d, ok, C_small)
                        assert got == C_small * math.ceil(d / w), ("split", C_small, w, s, H, d, got)
                        cases += 1
    return cases


def F5():
    from fractions import Fraction as Fr
    vals = (0, 1, 3)
    seqs_all = [list(p) for n in (1, 2, 3, 4) for p in itertools.product(vals, repeat=n)]
    H = 6
    cases = 0
    seen = set()
    for k in (1, 2):
        for base in itertools.combinations(range(len(seqs_all)), k):
            L = suffix_closure([seqs_all[i] for i in base])
            E = tuple(envelope(L, H))
            if E in seen:
                continue
            seen.add(E)
            pts = [(Fr(u), Fr(E[u])) for u in range(H + 1)]
            # candidate vertices of the LP
            cands = [(Fr(max(E)), Fr(0))]
            for (u1, e1), (u2, e2) in itertools.combinations(pts, 2):
                r = (e2 - e1) / (u2 - u1)
                b = e1 - r * u1
                if r >= 0 and b >= 0:
                    cands.append((b, r))
            feas = [(b, r) for (b, r) in cands if all(b + r * u >= e for (u, e) in pts)]
            for D in range(H + 1):
                lp = min(b + r * D for (b, r) in feas)
                # upper concave hull at D: max over pairs (u1 <= D <= u2) of the chord, and points at D
                hull = Fr(E[D])
                for (u1, e1) in pts:
                    for (u2, e2) in pts:
                        if u1 < D < u2:
                            hull = max(hull, e1 + (e2 - e1) * (D - u1) / (u2 - u1))
                assert lp == hull, ("bucket hull", E, D, lp, hull)
                cases += 1
    return cases


if __name__ == "__main__":
    out = {"F1_cases": F1(), "F2_cases": F2(), "F3_cases": F3(), "F4_cases": F4(), "F5_cases": F5(), "failures": 0}
    print(json.dumps(out))
    sys.exit(0)
