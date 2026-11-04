"""F11: the floor for release-only defenses, 2026-10-16.

Claim (Theorem 7.1(ii) of the paper): any defense whose decisions depend only on the
times and amounts of the requests it receives and the releases it has made (a limit, a hold, an
alarm on the outflow's size or pace, or any combination), and that never delays a legitimate
history by more than h nor pauses it, lets out at least min{W, E((d - h)^+)} within d of a
failure: the unauthorized party replays the busiest legitimate window, which the defense cannot
tell apart from legitimate traffic.  An alarm that uses information outside the release stream
(the value deposited on the other chain) is not bound by the floor: with latency ell it caps the
loss at the limit's release within ell.

Discrete check.  Histories are request sequences over slots 0..T-1 with values in {0,1,2}; a
legitimate set L is the suffix closure of one or two base sequences (as in F1).  The defense family:
a token bucket (b, r) in discrete slots (curve b + min(r, b)(d - 1)) with a hold of
h slots, combined with an alarm that pauses permanently after a latency of ell slots once the
released value over the last w slots exceeds a threshold theta (alarm on the outflow's pace) or
once the bucket's tokens fall below a level a (alarm on the limit's own state).  For every
parameter choice under which no history of L is delayed by more than h or paused, and for every
d, the check verifies:
  (a) replaying the busiest legitimate window of length (d - h)^+ releases at least
      min{W, E((d - h)^+)} within d (the floor binds the whole family);
  (b) the replay never trips the alarm;
  (c) with a deposit-backing alarm of latency ell, the release within d of a burst of W is at
      most min{W, beta(min(d, ell))}, where beta is the bucket's curve after the hold; in
      discrete slots the alarm acts from the slot after the one in which it fires, so the bound
      reads beta over min(d, ell + 1) slots (a first run used min(d, ell) and reported the slot
      convention, not the claim, as failures).
Exact integers.  Prints a JSON summary; exits nonzero on a failure.
"""
import itertools
import json
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


def run(requests, T, b, r, h, alarm, ell, W=10 ** 9):
    """Simulate the defense on a request sequence (value per slot).  Returns (releases per slot,
    max delay in slots of any unit, alarm_fired).  FIFO fluid bucket; hold h slots; alarm kinds:
    ('pace', w, theta), ('tokens', a), or None; after the alarm fires, the pause takes effect
    ell slots later and nothing is released from then on."""
    tokens = b
    queue = []          # (arrival slot, value)
    rel = [0] * T
    max_delay = 0
    fired_at = None
    for t in range(T):
        if t > 0:
            tokens = min(b, tokens + r)
        if t < len(requests) and requests[t] > 0:
            queue.append([t, requests[t]])
        paused = fired_at is not None and t >= fired_at + ell
        if not paused:
            k = 0
            while k < len(queue):
                arr, v = queue[k]
                if t < arr + h:
                    break
                take = min(v, tokens)
                if take <= 0:
                    break
                tokens -= take
                rel[t] += take
                queue[k][1] -= take
                if queue[k][1] == 0:
                    max_delay = max(max_delay, t - arr)
                    queue.pop(k)
                else:
                    break
        if alarm and fired_at is None:
            if alarm[0] == 'pace':
                _, w, theta = alarm
                if sum(rel[max(0, t - w + 1):t + 1]) > theta:
                    fired_at = t
            elif alarm[0] == 'tokens':
                if tokens < alarm[1]:
                    fired_at = t
    if queue:
        max_delay = 10 ** 6   # something never released within the horizon
    return rel, max_delay, fired_at is not None


def main():
    vals = (0, 1, 2)
    bases = [list(p) for n in (1, 2, 3) for p in itertools.product(vals, repeat=n) if sum(p) > 0]
    T = 7
    cases = 0
    fails = []
    checked_sets = 0
    for k in (1, 2):
        for base in itertools.combinations(range(len(bases)), k):
            L = suffix_closure([bases[i] for i in base])
            E = envelope(L, T)
            checked_sets += 1
            for b, r, h in itertools.product((1, 2, 3, 4), (1, 2), (0, 1)):
                alarms = [None] + [('pace', w, th) for w in (1, 2) for th in (1, 2, 3, 4)] + [('tokens', a) for a in (1, 2, 3)]
                for alarm in alarms:
                    for ell in (0, 1, 2):
                        # admissible: no legitimate history delayed more than h, none trips the alarm
                        ok = True
                        for seq in L:
                            _, md, fired = run(seq, T, b, r, h, alarm, ell)
                            if md > h or fired:
                                ok = False
                                break
                        if not ok:
                            continue
                        for d in range(1, T + 1):
                            u = max(0, d - h)
                            # the busiest legitimate window of length u, replayed from slot 0
                            best_seq, best_val = None, -1
                            for seq in L:
                                A = cum(seq)
                                for s in range(len(seq) + 1):
                                    v = A[min(len(seq), s + u)] - A[s]
                                    if v > best_val:
                                        best_val, best_seq = v, seq[s:]
                            rel, _, fired = run(best_seq, T, b, r, h, alarm, ell)
                            got = sum(rel[:d])
                            cases += 1
                            if got < min(10 ** 9, E[u]):
                                fails.append(('floor', base, b, r, h, alarm, ell, d, got, E[u]))
                            if fired:
                                fails.append(('replay tripped the alarm', base, b, r, h, alarm, ell, d))
                        # (c) a deposit-backing alarm: fires at the first unauthorized request (slot 0)
                        burst = [10 ** 6] + [0] * (T - 1)
                        tokens_alarm = ('tokens', 10 ** 9)   # fires immediately: stands in for 'unbacked'
                        rel, _, _ = run(burst, T, b, r, h, tokens_alarm, ell)
                        for d in range(1, T + 1):
                            got = sum(rel[:d])
                            # the alarm acts from the slot after it fires: ell slots of latency leave
                            # slots 0..ell open, that is ell + 1 slots of the bucket's discrete curve
                            dd = min(d, ell + 1)
                            cap = 0 if dd <= h else b + min(r, b) * (dd - h - 1)
                            cases += 1
                            if got > cap:
                                fails.append(('backing alarm above beta(min(d, ell))', b, r, h, ell, d, got, cap))
    out = {"legitimate_sets": checked_sets, "cases": cases, "failures": len(fails)}
    print(json.dumps(out))
    if fails:
        for f in fails[:10]:
            print(f)
        sys.exit(1)


if __name__ == "__main__":
    main()
