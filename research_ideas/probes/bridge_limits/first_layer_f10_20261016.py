"""F10: results of the paper (route cuts, timelocked control, net flow across both
sides, the bucket for uncertain response times), 2026-10-16.

Discrete slots 0..T-1; a curve f(d) is the value released in slots 0..d-1.  A token bucket
(b, r) starts full, refills r (capped at b) before every slot after the first, and has the
curve beta(d) = b + min(r, b)(d - 1) for d >= 1.

  (a) Theorem 4.1(ii) and Corollary 4.2: two channels, each with its own bucket, in series
      with a pooled bucket that both channels' releases pass.  Over every injection pattern
      (amounts 0..2 per channel and slot, T = 4), the total released within d never exceeds
      min{W, beta_pool(d), beta_1(d) + beta_2(d)}, and a failure confined to channel 1 never
      exceeds min{W, beta_pool(d), beta_1(d)}.  Bursts attain the cut bound when the pooled
      bucket is loose.
  (b) Proposition 4.4: a bucket whose party can lift it by an announcement that takes effect
      T slots later (the response cancels it before then).  Over every announcement slot and
      injection pattern, the most released within d is min{W, beta(d)} for d <= T and W for
      d > T.
  (c) Proposition 5.3(ii): a bucket on side A that adds every deposit on A to its tokens, and
      a bucket on side B that pays the deposits back from the next slot on.  The party starts
      with nothing and may, in each slot, deposit x <= holdings + y and release y <= tokens + x
      on A (it can redeposit what it releases in the same slot, which covers any number of
      cycles within the slot).  Over every strategy (amounts up to a budget, T = 3), its net
      take within d (holdings on A plus payouts received on B) never exceeds
      min{W_A + W_B, beta_A(d) + beta_B(d)}, and reaches min{W_A, beta_A(d)} +
      min{W_B, beta_B(d - 1)}: the bound up to one slot of payout delay.
  (d) Proposition 7.4: for every envelope of F5's domain and every mean response time mu in
      {1/2, 3/2, 7/3, 5/2, 11/4, 13/3}, the smallest E_G[b + rD] = b + r mu over buckets with
      b + ru >= E(u) for all u equals the least concave majorant of E at mu (exact rational LP
      by vertex enumeration against an independently computed hull).
Exact integers and fractions throughout.  Prints a JSON summary; exits nonzero on a failure.
"""
import itertools
import json
import sys
from fractions import Fraction as Fr

INF = 10 ** 9


def beta_bucket(b, r, d):
    return 0 if d <= 0 else b + min(r, b) * (d - 1)


def bucket_step(tokens, b, r, t):
    return tokens if t == 0 else min(b, tokens + r)


# ------------------------------------------------------------------ (a) route cuts
def run_two_channels(inj1, inj2, p1, p2, pp):
    """Per-slot releases of channel buckets p1, p2 in series with a pooled bucket pp."""
    T = len(inj1)
    tok = [p1[0], p2[0], pp[0]]
    back = [0, 0, 0]
    out = []
    for t in range(T):
        tok[0] = bucket_step(tok[0], p1[0], p1[1], t)
        tok[1] = bucket_step(tok[1], p2[0], p2[1], t)
        tok[2] = bucket_step(tok[2], pp[0], pp[1], t)
        rel = []
        for k, inj in ((0, inj1), (1, inj2)):
            back[k] += inj[t]
            x = min(tok[k], back[k])
            tok[k] -= x
            back[k] -= x
            rel.append(x)
        back[2] += rel[0] + rel[1]
        y = min(tok[2], back[2])
        tok[2] -= y
        back[2] -= y
        out.append(y)
    return out


def check_a():
    T, cases, tight = 4, 0, 0
    params = [(1, 1), (2, 1), (3, 2), (2, 2)]
    pools = [(1, 1), (3, 1), (4, 2), (100, 100)]
    pats = list(itertools.product(range(3), repeat=T))
    for p1, p2, pp in itertools.product(params, params, pools):
        for W in (3, 6, 100):
            best = [0] * (T + 1)
            best1 = [0] * (T + 1)
            for i1 in pats:
                for i2 in pats:
                    if sum(i1) + sum(i2) > W:
                        continue
                    rel = run_two_channels(i1, i2, p1, p2, pp)
                    c = 0
                    for d in range(1, T + 1):
                        c += rel[d - 1]
                        best[d] = max(best[d], c)
                        if sum(i2) == 0:
                            best1[d] = max(best1[d], c)
                    cases += 1
            for d in range(1, T + 1):
                bnd = min(W, beta_bucket(*pp, d), beta_bucket(*p1, d) + beta_bucket(*p2, d))
                bnd1 = min(W, beta_bucket(*pp, d), beta_bucket(*p1, d))
                assert best[d] <= bnd, ("cut bound", p1, p2, pp, W, d, best[d], bnd)
                assert best1[d] <= bnd1, ("confined bound", p1, p2, pp, W, d, best1[d], bnd1)
                if pp == (100, 100) and W == 100 and best[d] == bnd:
                    tight += 1
    return cases, tight


# ------------------------------------------------------------------ (b) timelocked control
def check_b():
    cases = 0
    for b, r in [(1, 1), (2, 1), (3, 2)]:
        for Tl in (1, 2, 3):
            for W in (4, 9):
                T = 5
                best = [0] * (T + 1)
                for ann in range(T):               # slot of the announcement
                    eff = ann + Tl                 # first slot without the limit
                    for inj in itertools.product(range(W + 1), repeat=2):
                        if sum(inj) > W:
                            continue
                        backlog, tokens, c = 0, b, 0
                        for t in range(T):
                            tokens = bucket_step(tokens, b, r, t)
                            backlog += inj[t] if t < 2 else 0
                            if t >= eff:
                                x = backlog
                            else:
                                x = min(tokens, backlog)
                                tokens -= x
                            backlog -= x
                            c += x
                            best[t + 1] = max(best[t + 1], c)
                            cases += 1
                for d in range(1, T + 1):
                    want = min(W, beta_bucket(b, r, d)) if d <= Tl else W
                    assert best[d] == want, ("timelock", b, r, Tl, W, d, best[d], want)
    return cases


# ------------------------------------------------------------------ (c) net flow across both sides
def check_c():
    """One (deposit, release) pair per slot with the deposit credited first and the release
    allowed to feed the deposit: this is the same as any number of release-deposit cycles in
    the slot, so it also covers rules that cap the credited tokens at b_A.  Side A's escrow
    holds W_A and side B's W_B; W = W_A + W_B."""
    cases = 0
    for (bA, rA), (bB, rB) in itertools.product([(1, 1), (2, 1), (2, 2)], [(1, 1), (2, 1), (2, 2)]):
        for WA, WB in ((3, 2), (40, 40)):
            T = 3
            best = [0] * (T + 1)
            budget = 6

            def dfs(t, tokA, tokB, hold, queue, paid, escrow_out):
                nonlocal cases
                if t == T:
                    return
                tokA = bucket_step(tokA, bA, rA, t)
                tokB = bucket_step(tokB, bB, rB, t)
                pay = min(tokB, queue, WB - paid)          # B pays deposits queued in earlier slots
                tokB2, queue2, paid2 = tokB - pay, queue - pay, paid + pay
                for x in range(budget + 1):
                    for y in range(budget + 1):
                        if x > hold + y or y > tokA + x:
                            continue
                        out = escrow_out + y - x           # net value that left A's escrow
                        if out > WA:
                            continue
                        h2 = hold + y - x
                        best[t + 1] = max(best[t + 1], h2 + paid2)
                        cases += 1
                        dfs(t + 1, tokA + x - y, tokB2, h2, queue2 + x, paid2, out)

            dfs(0, bA, bB, 0, 0, 0, 0)
            for d in range(1, T + 1):
                up = min(WA + WB, beta_bucket(bA, rA, d) + beta_bucket(bB, rB, d))
                low = min(WA, beta_bucket(bA, rA, d)) + min(WB, beta_bucket(bB, rB, d - 1))
                assert best[d] <= up, ("netflow bound", bA, rA, bB, rB, WA, WB, d, best[d], up)
                assert best[d] >= low, ("netflow attained", bA, rA, bB, rB, WA, WB, d, best[d], low)
    return cases


# ------------------------------------------------------------------ (d) bucket for uncertain response times
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


def check_d():
    vals = (0, 1, 3)
    seqs_all = [list(p) for n in (1, 2, 3, 4) for p in itertools.product(vals, repeat=n)]
    H = 6
    mus = [Fr(1, 2), Fr(3, 2), Fr(7, 3), Fr(5, 2), Fr(11, 4), Fr(13, 3)]
    cases, seen = 0, set()
    for k in (1, 2):
        for base in itertools.combinations(range(len(seqs_all)), k):
            E = tuple(envelope(suffix_closure([seqs_all[i] for i in base]), H))
            if E in seen:
                continue
            seen.add(E)
            pts = [(Fr(u), Fr(E[u])) for u in range(H + 1)]
            cands = [(Fr(max(E)), Fr(0))]
            for (u1, e1), (u2, e2) in itertools.combinations(pts, 2):
                r = (e2 - e1) / (u2 - u1)
                b = e1 - r * u1
                if r >= 0 and b >= 0:
                    cands.append((b, r))
            feas = [(b, r) for (b, r) in cands if all(b + r * u >= e for (u, e) in pts)]
            for mu in mus:
                lp = min(b + r * mu for (b, r) in feas)
                hull = max([e1 + (e2 - e1) * (mu - u1) / (u2 - u1)
                            for (u1, e1) in pts for (u2, e2) in pts if u1 <= mu <= u2 and u1 < u2])
                assert lp == hull, ("mean bucket", E, mu, lp, hull)
                cases += 1
    return cases


if __name__ == "__main__":
    a_cases, a_tight = check_a()
    out = {"a_route_cut_cases": a_cases, "a_cut_attained": a_tight, "b_timelock_cases": check_b(),
           "c_netflow_cases": check_c(), "d_mean_bucket_cases": check_d(), "failures": 0}
    print(json.dumps(out))
    sys.exit(0)
