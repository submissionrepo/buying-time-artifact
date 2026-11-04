"""Check analysis_core against brute-force discrete simulations (exact integers)."""
import itertools, math, random, sys
sys.path.insert(0, ".")
import analysis_core as ac


def brute_bucket_delays(arrivals, b, r, T):
    # discrete slots; tokens refill by r at the start of each slot after slot 0 (cap b); FIFO fluid by integer units
    queue = []  # list of [request_index, remaining]
    tokens = b
    release_slot = {}
    for t in range(T):
        if t > 0:
            tokens = min(b, tokens + r) if not queue else tokens + r  # with backlog, tokens are used immediately
        for idx, v in arrivals.get(t, []):
            queue.append([idx, v, t])
        while queue and tokens > 0:
            take = min(tokens, queue[0][1])
            queue[0][1] -= take
            tokens -= take
            if queue[0][1] == 0:
                release_slot[queue[0][0]] = t
                queue.pop(0)
        if not queue:
            tokens = min(tokens, b)
    return release_slot


def main():
    rng = random.Random(7)
    fails = 0
    cases = 0
    for trial in range(3000):
        b = rng.randint(1, 4); r = rng.randint(1, b)  # discrete comparison needs r <= b
        n = rng.randint(1, 5)
        times = sorted(rng.randint(0, 6) for _ in range(n))
        vals = [rng.randint(1, 6) for _ in range(n)]
        arrivals = {}
        for k, (t, v) in enumerate(zip(times, vals)):
            arrivals.setdefault(t, []).append((k, v))
        rel = brute_bucket_delays(arrivals, b, r, 60)
        # continuous-time closed form with refill at rate r per slot; discrete tokens arrive at slot starts,
        # so compare release slots: continuous release time ceil'd to the slot where the last unit is available
        st = None
        A_before = 0; m = math.inf
        for k, (t, v) in enumerate(zip(times, vals)):
            m = min(m, A_before + b - r * t)
            y = A_before + v
            cont = max(t, (y - m) / r)
            want = math.ceil(cont - 1e-12)
            cases += 1
            if rel.get(k) != want:
                fails += 1
                if fails <= 3:
                    print("mismatch", b, r, list(zip(times, vals)), k, rel.get(k), want)
            A_before = y
    # envelope and hull sanity
    for trial in range(500):
        n = rng.randint(1, 8)
        times = sorted(rng.uniform(0, 100) for _ in range(n))
        vals = [rng.uniform(0, 10) for _ in range(n)]
        for u in (1, 5, 20, 50):
            e = ac.envelope_events(times, vals, u)
            brute = max(sum(v for t, v in zip(times, vals) if s <= t < s + u) for s in times)
            cases += 1
            if abs(e - brute) > 1e-9:
                fails += 1
    print({"cases": cases, "failures": fails})
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
