"""F8: exact check of Proposition 9 (value-weighting error of a global rule), 2026-10-16.

A global rule meters assets k = 1..K at weights w_k (common units per unit of asset k)
and lets at most beta common units out within the horizon.  Asset k has true unit value
v_k and available amount a_k (so the bridge's extractable value is W = sum v_k a_k);
an optional per-asset cap c_k limits the amount of asset k.  The failing party chooses
amounts x_k in [0, min(a_k, c_k)] with sum w_k x_k <= beta to maximize sum v_k x_k.

Claims checked exactly (fractions):
  (i)  without per-asset caps and with enough of the best asset
       (a_k* >= beta / w_k* for k* = argmax v_k / w_k): the optimum equals
       beta * max_k (v_k / w_k);
  (ii) in general the optimum equals the greedy fill in decreasing order of v_k / w_k
       (fractional knapsack), and it never exceeds
       min(W, sum_k v_k min(a_k, c_k), beta * max_k (v_k / w_k)).
The optimum is computed independently by enumerating the vertices of the feasible
polytope (each vertex has at most one fractional coordinate), not by the greedy rule.
"""
import itertools
import json
import sys
from fractions import Fraction as Fr


def vertex_opt(v, w, ub, beta):
    K = len(v)
    best = Fr(0)
    # vertices: each coordinate at 0 or ub, except at most one set by the budget constraint
    for frac in [None] + list(range(K)):
        for pattern in itertools.product((0, 1), repeat=K):
            x = [ub[k] if pattern[k] else Fr(0) for k in range(K)]
            if frac is not None:
                used = sum(w[k] * x[k] for k in range(K) if k != frac)
                rem = beta - used
                if rem < 0:
                    continue
                x[frac] = min(ub[frac], rem / w[frac])
            if sum(w[k] * x[k] for k in range(K)) <= beta and all(0 <= x[k] <= ub[k] for k in range(K)):
                best = max(best, sum(v[k] * x[k] for k in range(K)))
    return best


def greedy(v, w, ub, beta):
    order = sorted(range(len(v)), key=lambda k: v[k] / w[k], reverse=True)
    rem, val = beta, Fr(0)
    for k in order:
        take = min(ub[k], rem / w[k])
        val += v[k] * take
        rem -= w[k] * take
        if rem <= 0:
            break
    return val


def main():
    vals = [Fr(1), Fr(2), Fr(3)]
    weights = [Fr(1, 2), Fr(1), Fr(2)]
    amounts = [Fr(1), Fr(3)]
    caps = [None, Fr(1), Fr(2)]
    betas = [Fr(1), Fr(5, 2), Fr(6)]
    n = 0
    fails = []
    for K in (1, 2, 3):
        for v in itertools.product(vals, repeat=K):
            for w in itertools.product(weights, repeat=K):
                for a in itertools.product(amounts, repeat=K):
                    for c in itertools.product(caps, repeat=K):
                        ub = [a[k] if c[k] is None else min(a[k], c[k]) for k in range(K)]
                        for beta in betas:
                            opt = vertex_opt(v, w, ub, beta)
                            g = greedy(v, w, ub, beta)
                            W = sum(v[k] * a[k] for k in range(K))
                            bound = min(W, sum(v[k] * ub[k] for k in range(K)), beta * max(v[k] / w[k] for k in range(K)))
                            n += 1
                            if opt != g or opt > bound:
                                fails.append(("ii", v, w, a, c, beta, opt, g, bound))
                            kstar = max(range(K), key=lambda k: v[k] / w[k])
                            if all(x is None for x in c) and a[kstar] >= beta / w[kstar]:
                                if opt != beta * v[kstar] / w[kstar]:
                                    fails.append(("i", v, w, a, beta, opt))
    print(json.dumps({"cases": n, "failures": len(fails), "first": [str(f) for f in fails[:3]]}))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
