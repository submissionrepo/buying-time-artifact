"""F7: exact checks for Theorem 3 (c') and (e) and Theorem 4 (regeneration), 2026-10-16.

(c') net-flow accounting with cost c per counted inflow unit.  Windows k = 1..n;
the party chooses counted inflow I_k >= 0 (integer) and outflow y_k >= 0 with
y_k - I_k <= C.  The escrow starts at W and receives c * I_k of real value per
window (c = 1: same-token deposit; c = 0: fabricated counted inflow); outflow
cannot exceed the escrow balance.  The party's net take is sum(y) - c sum(I).
Claim: max net take = min(W, C n) if c >= 1, and = W if c < 1 (given enough
inflow budget: up to ceil(W/(1-c)) + 1 counted units per window), computed
exactly by brute force over integer I_k, y_k.

(e) cumulative freeze theta: releases since the last review are capped at theta;
no automatic reset.  Claim: max release by any d >= 1 slot is min(W, theta),
by brute force over release vectors.

Theorem 4 (regeneration): a token bucket with r >= 1 per slot and an unbounded
horizon releases W; checked on a horizon long enough for the refill to cover W,
by an exact greedy simulation (releasing all available tokens each slot is optimal
for a token bucket): the max release reaches W exactly when d >= 1 + ceil((W - b)/r).
"""
import itertools
import json
import math
import sys
from fractions import Fraction as Fr


def net_flow_max(W, C, n, c, Imax):
    best = Fr(0)
    for I in itertools.product(range(Imax + 1), repeat=n):
        bal = Fr(W)
        take = Fr(0)
        for k in range(n):
            bal += c * I[k]
            y = min(bal, Fr(C + I[k]))
            # outflow is an integer amount in units; floor to keep integrality of releases
            y = Fr(math.floor(y))
            bal -= y
            take += y - c * I[k]
        best = max(best, take)
    return best


def freeze_max(W, theta, d):
    best = 0
    for r in itertools.product(range(theta + 2), repeat=d):
        if sum(r) <= theta:
            best = max(best, min(W, sum(r)))
    return best


def bucket_max(W, b, r, d):
    # discrete bucket from full; releases up to available each slot
    level = b
    out = 0
    for t in range(d):
        if t > 0:
            level = min(b, level + r)
        take = min(level, W - out)
        out += take
        level -= take
    return out


def main():
    fails = []
    n_cases = 0
    for W in (3, 5, 8):
        for C in (0, 1, 2):
            for n in (1, 2, 3):
                for c in (Fr(0), Fr(1, 2), Fr(1), Fr(3, 2)):
                    Imax = (math.ceil(W / (1 - c)) + 1) if c < 1 else W + 2  # enough counted inflow to exhaust W
                    got = net_flow_max(W, C, n, c, Imax=Imax)
                    want = Fr(min(W, C * n)) if c >= 1 else Fr(W)
                    n_cases += 1
                    if got != want:
                        fails.append(("net", W, C, n, str(c), str(got), str(want)))
    for W in (2, 4, 9):
        for theta in (1, 2, 3):
            for d in range(1, 6):
                got = freeze_max(W, theta, d)
                n_cases += 1
                if got != min(W, theta):
                    fails.append(("freeze", W, theta, d, got))
    for W in (5, 10, 17):
        for b in (1, 2, 4):
            for r in (1, 2, 3):
                if r > b:
                    continue
                need = 1 + math.ceil(max(0, W - b) / r)
                for d in range(1, need + 3):
                    got = bucket_max(W, b, r, d)
                    want = min(W, b + r * (d - 1))
                    n_cases += 1
                    if got != want or ((d >= need) != (got == W)):
                        fails.append(("regen", W, b, r, d, got, want, need))
    print(json.dumps({"cases": n_cases, "failures": len(fails), "first": [str(f) for f in fails[:5]]}))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
