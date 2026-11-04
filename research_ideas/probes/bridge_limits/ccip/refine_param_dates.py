"""Date the bucket changes of the selected token-lanes more precisely than the monthly snapshots.

For each selected lane and side (out = source pool outbound, in = destination pool inbound) and each
monthly snapshot whose raw value differs from the previous snapshot, bisect over the commits that
touched lanes.json between the two snapshot commits (data/ccip/lanes_history/commits.json) to find
the first commit carrying the new value.  The on-chain change lies in the bracket
(date of the last commit with the old value, date of the first commit with the new value].
The effective time used downstream is the end of the bracket that is more lenient to the observed
flow: the start for a loosening change, the end for a tightening change.

Writes data/ccip/derived/param_changes_refined.json.
Run: python -I refine_param_dates.py
"""
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ccip_common as cc  # noqa: E402
from fetch_lanes_history import raw_get  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
HIST = os.path.join(cc.DATA, "lanes_history")
_cache = {}


def lanes_at(sha):
    if sha in _cache:
        return _cache[sha]
    d = os.path.join(HIST, "by_sha", sha)
    p = os.path.join(d, "lanes.json")
    if not os.path.exists(p):
        os.makedirs(d, exist_ok=True)
        raw_get(sha, "lanes.json", p)
    _cache.clear()  # keep memory small: one parsed file at a time
    _cache[sha] = cc.load_json(p)
    return _cache[sha]


def raw_value(lanes, src, dst, tok, side):
    if side == "out":
        ent = (((lanes.get(src) or {}).get(dst) or {}).get("supportedTokens") or {}).get(tok)
        if ent is None:
            return None
        return cc.bucket((ent or {}).get("rateLimiterConfig"), "out")
    ent = (((lanes.get(dst) or {}).get(src) or {}).get("supportedTokens") or {}).get(tok)
    if ent is None:
        return None
    v = cc.bucket((ent or {}).get("rateLimiterConfig"), "in")
    return None if v[1] is None else v


def ts(iso):
    return int(dt.datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp())


def loosening(old, new):
    """True if the new bucket allows at least as much at every horizon (b and r both weakly up),
    or the bucket is switched off."""
    if old is None or new is None:
        return False
    oe, ob, orr = old
    ne, nb, nr = new
    if not ne:
        return True
    if not oe:
        return False
    return nb >= ob and nr >= orr


def main():
    sel = cc.load_json(os.path.join(HERE, "selection.json"))
    manifest = cc.load_json(os.path.join(HIST, "manifest.json"))
    commits = cc.load_json(os.path.join(HIST, "commits.json"))["commits"]
    order = {c["sha"]: i for i, c in enumerate(commits)}
    snaps = [s for s in sorted(k for k in manifest if k != "current") + ["current"]
             if manifest[s].get("sha") in order]
    out_eff, brackets = {}, []
    for L in sel["lanes"]:
        src, dst, tok = L["src"], L["dst"], L["token"]
        for side in ("out", "in"):
            prev_s, prev_v = None, None
            for s in snaps:
                v = raw_value(lanes_at(manifest[s]["sha"]), src, dst, tok, side)
                if prev_s is not None and v != prev_v and v is not None:
                    lo, hi = order[manifest[prev_s]["sha"]], order[manifest[s]["sha"]]
                    # invariant: commit lo has a value != v, commit hi has v
                    while hi - lo > 1:
                        mid = (lo + hi) // 2
                        if raw_value(lanes_at(commits[mid]["sha"]), src, dst, tok, side) == v:
                            hi = mid
                        else:
                            lo = mid
                    t_lo, t_hi = ts(commits[lo]["date"]), ts(commits[hi]["date"])
                    loose = loosening(prev_v, v)
                    eff = t_lo if loose else t_hi
                    out_eff.setdefault(f"{src}|{dst}|{tok}|{side}", {})[s] = eff
                    brackets.append({"lane": f"{src}->{dst} {tok}", "side": side, "snapshot": s,
                                     "old_raw": prev_v, "new_raw": v,
                                     "after": commits[lo]["date"], "by": commits[hi]["date"],
                                     "loosening": loose,
                                     "applied_at": dt.datetime.fromtimestamp(eff, dt.timezone.utc).isoformat()})
                    print(brackets[-1], flush=True)
                prev_s, prev_v = s, v
    json.dump({"built_utc": cc.utcnow(), "effective": out_eff, "brackets": brackets},
              open(os.path.join(cc.DERIVED, "param_changes_refined.json"), "w", encoding="utf-8"), indent=1,
              default=str)


if __name__ == "__main__":
    main()
