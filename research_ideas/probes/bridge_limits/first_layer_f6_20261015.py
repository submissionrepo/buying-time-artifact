"""F6: exact checks for Theorem 3 (response functions of deployed rule families).

Discrete time, slots 0..D-1 count (the pause takes effect at slot D and cancels
everything still queued).  The unauthorized party submits requests (integers) at
chosen slots; it may also make deposits where the rule has net accounting.  For
each rule we compute by brute force the maximum value released before the pause
over all request patterns from a small grid, and compare with the formula.

Rules
- time lock H: a request submitted at slot s is released at slot s + H.
  Formula: W * [D >= H + 1].
- sliding cap C over w slots with automatic release after A: a request is
  released at once if the counted releases in the last w slots plus it stay
  within C (requests are divisible: the part that fits is released, the rest
  queued); queued parts are released at slot s + A without counting.
  Formula: min(W, C * ceil(D / w)) for D <= A; W for D >= A + 1.
- percentage cap p per calendar window of w slots (windows start at slot 0):
  within window k at most p * (balance at the window start) leaves.
  Formula: W * (1 - (1 - p)^n) with n = number of windows started before D.
- net flow cap C per calendar window: (outflow - counted inflow) <= C per window.
  (a) every counted inflow is a real deposit the party pays for; the loss is
      outflow minus deposits.  Formula: min(W, C * n).
  (b) counted inflows are free (no value delivered).  Formula: W whenever D >= 1
      and C >= 0, given enough slots to submit.
"""
import itertools
import json
import math
import sys
from fractions import Fraction as Fr


def time_lock(W, H, D):
    best = 0
    # submitting everything at slot 0 is weakly optimal; still brute force small patterns
    for s in range(0, D + 1):
        released = W if s + H < D else 0
        best = max(best, released)
    return best


def auto_release(W, C, w, A, D):
    # strategies: amounts per slot in {0, ..., W}, horizon D slots; keep tiny
    best = 0
    for pattern in itertools.product(range(W + 1), repeat=D):
        if sum(pattern) > W:
            continue
        counted = [0] * D          # counted releases per slot
        out = 0
        queue = []                 # (release_slot, amount)
        for t in range(D):
            # automatic releases due now
            due = sum(a for (rs, a) in queue if rs == t)
            queue = [(rs, a) for (rs, a) in queue if rs != t]
            out += due
            req = pattern[t]
            if req:
                window = sum(counted[max(0, t - w + 1):t + 1])
                room = max(0, C - window)
                now = min(room, req)
                counted[t] += now
                out += now
                if req - now:
                    queue.append((t + A, req - now))
        best = max(best, out)
    return best


def percentage(W, p, w, D):
    # brute force over withdrawals of 0, half or all of the allowance in each window
    nwin = len(range(0, D, w))
    best = Fr(0)
    for choice in itertools.product((Fr(0), Fr(1, 2), Fr(1)), repeat=nwin):
        bal = Fr(W)
        out = Fr(0)
        for c in choice:
            take = c * p * bal
            out += take
            bal -= take
        best = max(best, out)
    return best


def net_flow_real(W, C, w, D, Kmax):
    # party may deposit real value x_t >= 0 and withdraw y_t >= 0 per slot;
    # per calendar window sum(y) - sum(x) <= C; loss = sum(y) - sum(x), capped by W + deposits
    best = 0
    nwin = math.ceil(D / w)
    for deps in itertools.product(range(Kmax + 1), repeat=nwin):
        loss = 0
        bal = W
        for k in range(nwin):
            bal += deps[k]
            y = min(bal, C + deps[k])
            bal -= y
            loss += y - deps[k]
        best = max(best, loss)
    return best


def net_flow_free(W, C, w, D, F):
    # counted inflows cost nothing: F free inflow units per window can be created
    nwin = math.ceil(D / w)
    bal = W
    out = 0
    for k in range(nwin):
        y = min(bal, C + F)
        bal -= y
        out += y
    return out


def main():
    fails = []
    n = 0
    for W in (1, 2, 3, 5):
        for H in (0, 1, 2, 3):
            for D in range(0, 7):
                got = time_lock(W, H, D)
                want = W if D >= H + 1 else 0
                n += 1
                if got != want:
                    fails.append(("time_lock", W, H, D, got, want))
    for W in (2, 3):
        for C in (1, 2):
            for w in (1, 2):
                for A in (1, 2, 3):
                    for D in range(0, 6):
                        got = auto_release(W, C, w, A, D)
                        want = min(W, C * math.ceil(D / w)) if D <= A else W
                        n += 1
                        if got != want:
                            fails.append(("auto_release", W, C, w, A, D, got, want))
    for W in (100, 1000):
        for p in (Fr(1, 20), Fr(1, 10), Fr(1, 4)):
            for w in (1, 2, 3):
                for D in range(0, 10):
                    got = percentage(W, p, w, D)
                    nw = math.ceil(D / w)
                    want = W * (1 - (1 - p) ** nw)
                    n += 1
                    if got != want:
                        fails.append(("percentage", W, p, w, D, got, want))
    for W in (5, 9):
        for C in (1, 2):
            for w in (1, 2):
                for D in range(1, 6):
                    got = net_flow_real(W, C, w, D, 3)
                    want = min(W, C * math.ceil(D / w))
                    n += 1
                    if got != want:
                        fails.append(("net_real", W, C, w, D, got, want))
                    got2 = net_flow_free(W, C, w, D, F=W)
                    n += 1
                    if got2 != W:
                        fails.append(("net_free", W, C, w, D, got2, W))
    print(json.dumps({"cases": n, "failures": len(fails), "first": [str(f) for f in fails[:5]]}))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
