"""Build results/incidents.csv and results/incidents.md (2026-10-16).

Inputs
- incidents/curation.py: one record per event of the universe (data/incidents/universe.json) with the
  final field values, their sources, and a release-path specification. Facts come from the research
  notes in data/incidents/research/batch_*.json and from chain data.
- data/incidents/onchain_summary.json: release paths measured from chain data by
  incidents/02_onchain_timing.py, 03_onchain_bsc_tokenhub.py and 04_onchain_inflows.py.
  Raw rows (with hashes) stay in data/incidents/onchain/; this script reads only block numbers
  from them, to cite explorer block pages.

Definitions (also stated in results/incidents.md)
- A release is a unit of value leaving the bridge for good: an escrow release at its time; an
  unbacked mint at its time for the part not later redeemed against the escrow; a redeemed part at
  its escrow-release time.
- Anchor (first release) = the earliest time at which cumulative released value reaches 1% of the
  event's released value; smaller earlier transfers are reported as preliminary transfers.
- outflow_duration_s = last unauthorized release on the main chain minus the main chain's anchor
  (same 1% rule on the main chain's own releases). time_to_90pct_s = anchor to the time cumulative
  released value reaches 90% (complete paths only).
- detection_lag_s = operator's first public acknowledgment minus anchor; pause_lag_s = pause or halt
  minus anchor, filled only when the pause time is read from chain data or stated by the operator or
  a post-mortem. Times known only as an upper bound go to *_bound_s.
- Pooled share within h = sum_i A_i s_i(h) / sum_i A_i over the bridge set, A_i = amount_usd and
  s_i(h) = share of event i's released value released within h of its anchor. Where s_i(h) is not
  determined, the bounds [lo, hi] are carried and pooled.

Run: python -I incidents/05_build_dataset.py
"""
import csv
import datetime
import json
import pathlib
import statistics
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
DATA = ROOT / "data" / "incidents"
RESULTS = ROOT / "results"
sys.path.insert(0, str(HERE))
from curation import EVENTS, UNIVERSE_NOTE  # noqa: E402

HORIZONS = [("10m", 600), ("1h", 3600), ("6h", 21600), ("24h", 86400)]
HLABEL = {"10m": "10 min", "1h": "1 h", "6h": "6 h", "24h": "24 h"}
RB = {"pause": "pause", "acknowledgment": "ack.", "pause report": "pause report"}
ANCHOR_SHARE = 0.01
EXPLORER = {"Ethereum": "https://etherscan.io/block/{}", "BSC": "https://bscscan.com/block/{}",
            "Arbitrum": "https://arbiscan.io/block/{}", "Bitcoin": "https://mempool.space/block/{}",
            "Polygon": "https://polygonscan.com/block/{}", "Base": "https://basescan.org/block/{}"}
CHAIN_NAME = {"ethereum": "Ethereum", "bsc": "BSC", "bitcoin": "Bitcoin", "arbitrum": "Arbitrum",
              "polygon": "Polygon", "base": "Base", "avalanche": "Avalanche", "fantom": "Fantom"}


def ts_of(s):
    if s is None:
        return None
    s = s.replace("Z", "")
    if len(s) == 16:
        s += ":00"
    return int(datetime.datetime.fromisoformat(s).replace(tzinfo=datetime.timezone.utc).timestamp())


def iso(ts):
    return None if ts is None else datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


SUMMARY = json.loads((DATA / "onchain_summary.json").read_text())


def onchain_blocks(target):
    """(first_block, last_block, chain) of the selected rows of a target, for explorer citations."""
    f = DATA / "onchain" / f"{target}.json"
    if not f.exists():
        return None
    d = json.loads(f.read_text())
    rows = d.get("rows", [])
    if target.startswith("E16_bsc"):
        sel = rows
        chain = "BSC"
    else:
        sel = [r for r in rows if r.get("selected")]
        chain = CHAIN_NAME.get((d.get("config") or {}).get("chain", ""), None)
    if not sel:
        return None
    sel = sorted(sel, key=lambda r: (r["ts"], str(r.get("block"))))
    if chain is None:
        chain = CHAIN_NAME.get(sel[0].get("chain"), sel[0].get("chain"))
    return sel[0]["block"], sel[-1]["block"], chain


def build_path(ev):
    """Return (releases, coverage); a release is (t_from, t_to, usd, chain, side).

    Point releases have t_from == t_to. An interval release is value known to have left between
    t_from and t_to (e.g. several transactions with published times but unpublished amounts)."""
    spec = ev.get("path")
    if not spec:
        return [], None
    rel = []
    for item in spec.get("onchain", []):
        tid, chain, side = item["target"], item["chain"], item.get("side", "escrow")
        s = SUMMARY[tid]
        t0 = ts_of(s["first_release_utc"])
        scale = item.get("scale", 1.0)
        for entry in s["path"]:
            dt, usd = entry[0], entry[1]
            ch = entry[2] if len(entry) > 2 else chain
            rel.append((t0 + dt, t0 + dt, usd * scale, ch, side))
    for r in spec.get("releases", []):
        rel.append((ts_of(r[0]), ts_of(r[0]), r[1], r[2], r[3]))
    for r in spec.get("intervals", []):
        rel.append((ts_of(r[0]), ts_of(r[1]), r[2], r[3], r[4]))
    rel.sort(key=lambda x: (x[0], x[1]))
    return rel, spec.get("coverage", "complete")


def anchor_of(rel):
    """Earliest time at which cumulative value reaches ANCHOR_SHARE of the total.

    Interval releases enter at their earliest time, so the anchor is the earliest time consistent
    with the published intervals."""
    tot = sum(r[2] for r in rel)
    if not rel:
        return None
    if tot <= 0:
        return rel[0][0]
    cum = 0.0
    for r in sorted(rel, key=lambda x: x[0]):
        cum += r[2]
        if cum >= ANCHOR_SHARE * tot - 1e-9:
            return r[0]
    return rel[-1][0]


def share_bounds(rel, anchor, h, extra_unplaced=0.0):
    tot = sum(r[2] for r in rel) + extra_unplaced
    lo = sum(r[2] for r in rel if r[1] - anchor <= h) / tot
    hi = (sum(r[2] for r in rel if r[0] - anchor <= h) + extra_unplaced) / tot
    return lo, hi


def time_to_share(rel, anchor, q):
    """Time to reach share q, if the intervals determine it; else None."""
    def first_cross(key):
        tot = sum(r[2] for r in rel)
        cum = 0.0
        for r in sorted(rel, key=key):
            cum += r[2]
            if cum >= q * tot - 1e-9:
                return key(r)
        return None
    a = first_cross(lambda r: r[0])
    b = first_cross(lambda r: r[1])
    return (a - anchor) if (a is not None and a == b) else None


def derive(ev):
    out = {}
    rel, coverage = build_path(ev)
    out["path_coverage"] = coverage or ""
    main = ev.get("main_chain")
    if rel:
        anchor = anchor_of(rel)
        if ev.get("anchor_utc"):
            anchor = ts_of(ev["anchor_utc"])
        mrel = [r for r in rel if r[3] == main] or rel
        m_anchor = anchor_of(mrel)
        m_last = max(r[1] for r in mrel)
        out["first_release_ts"] = anchor
        out["last_release_ts"] = m_last
        out["outflow_duration_s"] = m_last - m_anchor
        pre = [r for r in rel if r[1] < anchor]
        out["preliminary_auto"] = (f"{len(pre)} transfer(s) totalling {sum(r[2] for r in pre):,.0f} USD, "
                                   f"from {anchor - pre[0][0]} s before the first release") if pre else ""
        if coverage == "complete":
            out["time_to_90pct_s"] = time_to_share(rel, anchor, 0.9)
            for lab, h in HORIZONS:
                out[f"share_{lab}"] = share_bounds(rel, anchor, h)
        else:
            # partial path: the measured legs carry their own times; the rest of the amount is unplaced
            amt = ev.get("amount_usd")
            meas = sum(r[2] for r in rel)
            rest = max(0.0, (amt or meas) - meas)
            for lab, h in HORIZONS:
                out[f"share_{lab}"] = share_bounds(rel, anchor, h, extra_unplaced=rest)
    else:
        first = ts_of(ev.get("first_release_utc"))
        last = ts_of(ev.get("last_release_utc"))
        m_first = ts_of(ev.get("main_first_release_utc")) or first
        out["first_release_ts"] = first
        out["last_release_ts"] = last
        out["outflow_duration_s"] = (last - m_first) if (last is not None and m_first is not None) else None
        span = ev.get("all_chains_span_s")
        for lab, h in HORIZONS:
            if span is not None and span <= h:
                out[f"share_{lab}"] = (1.0, 1.0)
            elif ev.get("share_bounds", {}).get(lab):
                out[f"share_{lab}"] = tuple(ev["share_bounds"][lab])
            else:
                out[f"share_{lab}"] = (0.0, 1.0)
    if ev.get("outflow_duration_override_s") is not None:
        out["outflow_duration_s"] = ev["outflow_duration_override_s"]
    a = out.get("first_release_ts")
    ack = ts_of(ev.get("ack_utc"))
    out["detection_lag_s"] = (ack - a) if (ack is not None and a is not None) else None
    ackb = ts_of(ev.get("ack_bound_utc"))
    out["detection_lag_bound_s"] = (ackb - a) if (ackb is not None and a is not None) else None
    al = ts_of(ev.get("alert_utc"))
    out["first_alert_lag_s"] = (al - a) if (al is not None and a is not None) else None
    p = ts_of(ev.get("pause_utc"))
    out["pause_lag_s"] = (p - a) if (p is not None and a is not None and ev.get("pause_basis") in ("onchain", "stated")) else None
    if ev.get("pause_lag_stated_s") is not None:
        out["pause_lag_s"] = ev["pause_lag_stated_s"]
    pb = ts_of(ev.get("pause_bound_utc"))
    out["pause_lag_bound_s"] = (pb - a) if (pb is not None and a is not None) else None
    # response delay: first documented response, i.e. the earliest of the pause (chain data or stated),
    # the operator's first public acknowledgment, and the first dated report that a pause was in place
    report = out["pause_lag_bound_s"] if not (out["detection_lag_s"] is None and out["detection_lag_bound_s"] is not None) else None
    cands = [(v, lab) for v, lab in ((out["pause_lag_s"], "pause"), (out["detection_lag_s"], "acknowledgment"),
                                     (report, "pause report")) if v is not None]
    if cands:
        out["response_delay_s"], out["response_basis"] = min(cands)
    else:
        out["response_delay_s"], out["response_basis"] = None, ""
    out["response_delay_bound_s"] = out["detection_lag_bound_s"] if out["response_delay_s"] is None else None
    if out["response_delay_bound_s"] is not None:
        out["response_basis"] = "upper bound"
    # on-chain citations
    cites = []
    for item in (ev.get("path") or {}).get("onchain", []):
        b = onchain_blocks(item["target"])
        if b:
            url = EXPLORER.get(b[2])
            blocks = f"{url.format(b[0])} to {url.format(b[1])}" if url else f"blocks {b[0]} to {b[1]} ({b[2]})"
            cites.append(f"onchain: {blocks} (data/incidents/onchain/{item['target']}.json)")
    out["onchain_cite"] = " ; ".join(cites)
    return out


def fmt_num(x, nd=0):
    if x is None or x == "":
        return ""
    if isinstance(x, float):
        return f"{x:.{nd}f}" if nd else f"{round(x):d}"
    return str(x)


COLUMNS = ["id", "name", "date", "scope", "in_bridge_set", "amount_usd", "amount_range", "amount_source",
           "failure_class", "failure_basis", "failure_class_source", "release_side", "release_shares",
           "release_side_source", "main_chain", "chains", "first_release_utc", "last_release_utc",
           "outflow_duration_s", "time_to_90pct_s", "outflow_source", "n_releases", "n_releases_source",
           "preliminary_transfers", "detection_lag_s", "ack_utc", "ack_channel", "detection_source",
           "detection_lag_bound_s", "first_alert_lag_s", "first_alert_by", "first_alert_source",
           "pause_lag_s", "pause_utc", "pause_basis", "pause_what", "pause_source", "pause_lag_bound_s",
           "response_delay_s", "response_delay_bound_s", "response_basis",
           "limit_in_force", "limit_acted", "limit_source", "recovered_usd", "recovered_note",
           "recovered_source", "frozen_usd", "share_10m", "share_1h", "share_6h", "share_24h",
           "path_coverage", "dl_name", "dl_date", "dl_amount_usd", "notes"]


def share_cell(b):
    lo, hi = b
    if abs(hi - lo) < 1e-9:
        return f"{lo:.3f}"
    return f"{lo:.3f}-{hi:.3f}"


def row_for(ev, d):
    out_src = ev.get("outflow_source") or ""
    if d["onchain_cite"] and not out_src:
        out_src = d["onchain_cite"]
    elif d["onchain_cite"] and ev.get("outflow_source_add_onchain", True):
        out_src = d["onchain_cite"] + " ; " + out_src
    n_src = ev.get("n_releases_source") or out_src
    pre = ev.get("preliminary") or d.get("preliminary_auto", "")
    r = {
        "id": ev["id"], "name": ev["name"], "date": ev.get("date") or (iso(d["first_release_ts"])[:10] if d.get("first_release_ts") else ev.get("dl_date")),
        "scope": ev["scope"], "in_bridge_set": "yes" if ev["in_bridge_set"] else "no",
        "amount_usd": fmt_num(ev.get("amount_usd")), "amount_range": ev.get("amount_range", ""),
        "amount_source": ev.get("amount_source", ""),
        "failure_class": ev.get("failure_class", ""), "failure_basis": ev.get("failure_basis", ""),
        "failure_class_source": ev.get("failure_class_source", ""),
        "release_side": ev.get("release_side", ""), "release_shares": ev.get("release_shares", ""),
        "release_side_source": ev.get("release_side_source", ""),
        "main_chain": ev.get("main_chain", "") or "", "chains": ev.get("chains", ""),
        "first_release_utc": iso(d.get("first_release_ts")) or "", "last_release_utc": iso(d.get("last_release_ts")) or "",
        "outflow_duration_s": fmt_num(d.get("outflow_duration_s")), "time_to_90pct_s": fmt_num(d.get("time_to_90pct_s")),
        "outflow_source": out_src if (d.get("outflow_duration_s") is not None or d.get("first_release_ts")) else "",
        "n_releases": ev.get("n_releases", ""), "n_releases_source": n_src if ev.get("n_releases", "") != "" else "",
        "preliminary_transfers": pre,
        "detection_lag_s": fmt_num(d.get("detection_lag_s")), "ack_utc": ev.get("ack_utc") or "",
        "ack_channel": ev.get("ack_channel", ""), "detection_source": ev.get("detection_source", ""),
        "detection_lag_bound_s": fmt_num(d.get("detection_lag_bound_s")),
        "first_alert_lag_s": fmt_num(d.get("first_alert_lag_s")), "first_alert_by": ev.get("alert_by", ""),
        "first_alert_source": ev.get("alert_source", ""),
        "pause_lag_s": fmt_num(d.get("pause_lag_s")), "pause_utc": ev.get("pause_utc") or "",
        "pause_basis": ev.get("pause_basis", "") or "", "pause_what": ev.get("pause_what", ""),
        "pause_source": ev.get("pause_source", ""), "pause_lag_bound_s": fmt_num(d.get("pause_lag_bound_s")),
        "response_delay_s": fmt_num(d.get("response_delay_s")), "response_delay_bound_s": fmt_num(d.get("response_delay_bound_s")),
        "response_basis": d.get("response_basis", ""),
        "limit_in_force": ev.get("limit_in_force", ""), "limit_acted": ev.get("limit_acted", ""),
        "limit_source": ev.get("limit_source", ""),
        "recovered_usd": fmt_num(ev.get("recovered_usd")), "recovered_note": ev.get("recovered_note", ""),
        "recovered_source": ev.get("recovered_source", ""), "frozen_usd": fmt_num(ev.get("frozen_usd")),
        "path_coverage": d.get("path_coverage", ""),
        "dl_name": ev.get("dl_name", ""), "dl_date": ev.get("dl_date", ""), "dl_amount_usd": fmt_num(ev.get("dl_amount_usd")),
        "notes": ev.get("notes", ""),
    }
    for lab, _ in HORIZONS:
        b = d.get(f"share_{lab}")
        r[f"share_{lab}"] = share_cell(b) if (b and ev["in_bridge_set"] and (d.get("first_release_ts") or b == (1.0, 1.0))) else ""
    return r


# ---------- statistics for the markdown ----------

def quart(xs):
    xs = sorted(xs)
    if not xs:
        return None
    if len(xs) == 1:
        return xs[0], xs[0], xs[0]
    q = statistics.quantiles(xs, n=4, method="inclusive")
    return q[0], statistics.median(xs), q[2]


def hms(s):
    if s is None:
        return ""
    s = int(round(s))
    neg = s < 0
    s = abs(s)
    d, rem = divmod(s, 86400)
    h, rem = divmod(rem, 3600)
    m, sec = divmod(rem, 60)
    if d:
        txt = f"{d} d {h} h {m} min"
    elif h:
        txt = f"{h} h {m} min"
    elif m:
        txt = f"{m} min {sec} s"
    else:
        txt = f"{sec} s"
    return ("-" if neg else "") + txt


def musd(x):
    return f"{x / 1e6:,.1f}"


def dist_block(title, items, unit_note=""):
    """items: list of (value_s, label)."""
    lines = [f"**{title}** (n = {len(items)}{unit_note})", ""]
    if not items:
        return lines + ["No observations.", ""]
    vals = [v for v, _ in items]
    q1, med, q3 = quart(vals)
    lines.append(f"- Median {hms(med)}; quartiles {hms(q1)} and {hms(q3)}; range {hms(min(vals))} to {hms(max(vals))}.")
    lines.append("- List (ascending): " + "; ".join(f"{lab} {hms(v)}" for v, lab in sorted(items)) + ".")
    lines.append("")
    return lines


def main():
    universe = json.loads((DATA / "universe.json").read_text(encoding="utf-8"))
    uid = {u["event_id"] for u in universe}
    ids = [e["id"] for e in EVENTS]
    assert len(ids) == len(set(ids)), "duplicate ids in curation"
    missing = sorted(uid - set(ids))
    assert not missing, f"universe events without a curation record: {missing}"
    for ev in EVENTS:
        if ev.get("amount_usd") is None and ev.get("path"):
            rel, cov = build_path(ev)
            if cov == "complete":
                ev["amount_usd"] = sum(r[2] for r in rel)
    derived = {}
    rows = []
    for ev in EVENTS:
        d = derive(ev)
        derived[ev["id"]] = d
        rows.append(row_for(ev, d))
    RESULTS.mkdir(exist_ok=True)
    with open(RESULTS / "incidents.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    # guard: results must not carry addresses or transaction hashes
    import re
    text = (RESULTS / "incidents.csv").read_text(encoding="utf-8")
    bad = re.findall(r"0x[0-9a-fA-F]{40,64}|\b[13][a-km-zA-HJ-NP-Z1-9]{25,34}\b|bc1[0-9a-z]{20,}", text)
    assert not bad, f"address-like strings in incidents.csv: {bad[:5]}"
    write_markdown(rows, derived)
    print("wrote", RESULTS / "incidents.csv", len(rows), "rows")


def key_figures(bset, derived, tot_b):
    """Short summary block placed before the definitions."""
    def med(key):
        xs = [derived[e["id"]][key] for e in bset if derived[e["id"]].get(key) is not None]
        q = quart(xs)
        return len(xs), q

    out = ["## Key figures (bridge set)", ""]
    out.append(f"- {len(bset)} events, {musd(tot_b)}M USD. Of the 30 largest records, "
               f"{sum(1 for e in sorted(EVENTS, key=lambda x: -(x.get('amount_usd') or 0))[:30] if e['in_bridge_set'])} are in the bridge set.")
    for key, lab in [("outflow_duration_s", "Outflow duration"), ("time_to_90pct_s", "Time to 90% of value"),
                     ("first_alert_lag_s", "First third-party alert"), ("detection_lag_s", "Operator acknowledgment"),
                     ("pause_lag_s", "Pause (chain data or stated)"), ("response_delay_s", "Response delay (first documented response)")]:
        n, q = med(key)
        if q:
            out.append(f"- {lab}: median {hms(q[1])}, quartiles {hms(q[0])} and {hms(q[2])} (n = {n}).")
    vals = [derived[e["id"]]["response_delay_s"] for e in bset if derived[e["id"]].get("response_delay_s") is not None]
    if vals:
        out.append(f"- Mean response delay {hms(statistics.mean(vals))}; median {hms(statistics.median(vals))}.")
    parts = []
    for lab, h in HORIZONS:
        det_e = [e for e in bset if derived[e["id"]].get(f"share_{lab}")
                 and abs(derived[e["id"]][f"share_{lab}"][0] - derived[e["id"]][f"share_{lab}"][1]) < 1e-9]
        vd = sum(e["amount_usd"] for e in det_e)
        if vd:
            parts.append(f"{HLABEL[lab]} {100 * sum(e['amount_usd'] * derived[e['id']][f'share_{lab}'][0] for e in det_e) / vd:.1f}%")
    out.append("- Pooled share of value released within 10 min / 1 h / 6 h / 24 h of the first release (events with the share determined): "
               + ", ".join(parts) + ".")
    cls = {c: sum(e["amount_usd"] for e in bset if e.get("failure_class") == c) for c in "VDSO"}
    out.append("- Value by failure class: " + ", ".join(f"{c} {100 * v / tot_b:.1f}%" for c, v in cls.items()) + ".")
    sides = {s: sum(e["amount_usd"] for e in bset if (e.get("release_side") or "") == s) for s in ["escrow", "mint", "both", "other"]}
    out.append("- Value by release side: " + ", ".join(f"{s} {100 * v / tot_b:.1f}%" for s, v in sides.items()) + ".")
    return out


def write_markdown(rows, derived):
    from curation import MD_CAVEATS, MD_INTRO
    bset = [e for e in EVENTS if e["in_bridge_set"]]
    tot_b = sum(e.get("amount_usd") or 0 for e in bset)
    nm = lambda e: f"{e['id']} {e['short']}"
    L = ["# Large unauthorized outflow events from cross-chain bridges, 2021 to 2026", ""]
    cut = MD_INTRO.index("## 0. Definitions")
    L += MD_INTRO[:cut]
    L += key_figures(bset, derived, tot_b) + [""]
    L += MD_INTRO[cut:] + [""]

    # 1. coverage
    L += ["## 1. Coverage", ""]
    by_scope = {}
    for e in EVENTS:
        by_scope.setdefault(e["scope"], []).append(e)
    L.append(f"- Universe: {len(EVENTS)} records. {UNIVERSE_NOTE}")
    for sc, es in sorted(by_scope.items(), key=lambda kv: -len(kv[1])):
        L.append(f"- Scope `{sc}`: {len(es)} records, {musd(sum(x.get('amount_usd') or 0 for x in es))}M USD "
                 f"({', '.join(x['id'] for x in es)}).")
    L.append(f"- **Bridge set** (scopes `bridge_custody_or_mint` and `bridge_liquidity_or_relayer`), used for every statistic below: "
             f"{len(bset)} events, {musd(tot_b)}M USD.")

    def cov(test):
        es = [e for e in bset if test(e)]
        return f"{len(es)} events ({100 * sum(e.get('amount_usd') or 0 for e in es) / tot_b:.1f}% of value)"

    L.append("- Field coverage in the bridge set:")
    L.append(f"  - first release time: {cov(lambda e: derived[e['id']].get('first_release_ts') is not None)};")
    L.append(f"  - outflow duration: {cov(lambda e: derived[e['id']].get('outflow_duration_s') is not None)};")
    L.append(f"  - whole value path placed in time: {cov(lambda e: derived[e['id']].get('path_coverage') == 'complete')};")
    L.append(f"  - operator acknowledgment time: {cov(lambda e: derived[e['id']].get('detection_lag_s') is not None)}; "
             f"upper bound only: {cov(lambda e: derived[e['id']].get('detection_lag_s') is None and derived[e['id']].get('detection_lag_bound_s') is not None)};")
    L.append(f"  - pause time from chain data or stated: {cov(lambda e: derived[e['id']].get('pause_lag_s') is not None)}; "
             f"announcement only: {cov(lambda e: derived[e['id']].get('pause_lag_s') is None and derived[e['id']].get('pause_lag_bound_s') is not None)};")
    L.append(f"  - limit status documented (a rule, or a documented absence): {cov(lambda e: e.get('limit_in_force') not in ('', None, 'none reported'))}.")
    top = sorted(EVENTS, key=lambda x: -(x.get('amount_usd') or 0))[:30]
    L.append(f"- The 30 largest records by amount: {', '.join(e['id'] for e in top)}; "
             f"{sum(1 for e in top if e['in_bridge_set'])} of them are in the bridge set.")
    L.append("")

    # 2. per-event table
    L += ["## 2. Per-event summary (bridge set, by amount)", ""]
    L.append("Response delay: lag from the first release to the first documented response, the earliest of the pause (time from chain "
             "data or stated), the operator's first public acknowledgment, and the first dated report that a pause was in place; the "
             "basis is in brackets; `<=` marks an upper bound. Outflow duration: first to last release on the main chain.")
    L.append("")
    L.append("| id | event | date | amount (M USD) | outflow duration | response delay (basis) | class | release side |")
    L.append("|---|---|---|---:|---:|---|:---:|---|")
    for e in sorted(bset, key=lambda x: -(x.get("amount_usd") or 0)):
        d = derived[e["id"]]
        dur = hms(d.get("outflow_duration_s")) if d.get("outflow_duration_s") is not None else "n.a."
        if d.get("response_delay_s") is not None:
            rd = f"{hms(d['response_delay_s'])} ({RB[d['response_basis']]})"
        elif d.get("response_delay_bound_s") is not None:
            rd = f"<= {hms(d['response_delay_bound_s'])} (bound)"
        else:
            rd = "n.a."
        date = iso(d["first_release_ts"])[:10] if d.get("first_release_ts") else (e.get("date") or e.get("dl_date"))
        L.append(f"| {e['id']} | {e['short']} | {date} | {musd(e['amount_usd'])} | {dur} | {rd} | "
                 f"{e.get('failure_class', '') or 'n.a.'} | {e.get('release_side', '') or 'n.a.'} |")
    L.append("")
    others = [e for e in EVENTS if not e["in_bridge_set"]]
    if others:
        L.append("Outside the bridge set: " + "; ".join(
            f"{e['id']} {e['short']} ({e['scope']}, {musd(e.get('amount_usd') or 0)}M)" for e in others) + ".")
        L.append("")

    # 3. distributions
    L += ["## 3. Distributions (bridge set)", ""]
    dur = [(derived[e["id"]]["outflow_duration_s"], nm(e)) for e in bset if derived[e["id"]].get("outflow_duration_s") is not None]
    L += dist_block("Outflow duration, first to last unauthorized release on the main chain", dur)
    t90 = [(derived[e["id"]]["time_to_90pct_s"], nm(e)) for e in bset if derived[e["id"]].get("time_to_90pct_s") is not None]
    L += dist_block("Time from the first release until 90% of the event's value had left (whole path placed)", t90)
    det = [(derived[e["id"]]["detection_lag_s"], nm(e)) for e in bset if derived[e["id"]].get("detection_lag_s") is not None]
    L += dist_block("Detection lag, first release to the operator's first public acknowledgment", det)
    detb = [(derived[e["id"]]["detection_lag_bound_s"], nm(e)) for e in bset
            if derived[e["id"]].get("detection_lag_bound_s") is not None and derived[e["id"]].get("detection_lag_s") is None]
    if detb:
        L.append("Acknowledgment known only as an upper bound: " + "; ".join(f"{lab} at most {hms(v)}" for v, lab in sorted(detb)) + ".")
        L.append("")
    al = [(derived[e["id"]]["first_alert_lag_s"], nm(e)) for e in bset if derived[e["id"]].get("first_alert_lag_s") is not None]
    L += dist_block("First public alert by a third party, lag from the first release", al)
    pz = [(derived[e["id"]]["pause_lag_s"], nm(e)) for e in bset if derived[e["id"]].get("pause_lag_s") is not None]
    L += dist_block("Pause or halt lag, first release to the pause (time from chain data or stated)", pz)
    pzb = [(derived[e["id"]]["pause_lag_bound_s"], nm(e)) for e in bset
           if derived[e["id"]].get("pause_lag_bound_s") is not None and derived[e["id"]].get("pause_lag_s") is None]
    if pzb:
        L.append("Pause known only from its announcement (upper bound): " + "; ".join(f"{lab} at most {hms(v)}" for v, lab in sorted(pzb)) + ".")
        L.append("")
    both = [e for e in bset if derived[e["id"]].get("pause_lag_s") is not None and derived[e["id"]].get("last_release_ts") is not None]
    after = [e for e in both if derived[e["id"]]["pause_lag_s"] >= derived[e["id"]]["last_release_ts"] - derived[e["id"]]["first_release_ts"]]
    exc = [e for e in both if e not in after]
    L.append(f"In {len(after)} of the {len(both)} events with a known pause time, the pause came after the last release on the main chain"
             + (f" (exceptions: {', '.join(nm(e) for e in exc)})." if exc else "."))
    L.append("")

    # 4. response delay
    L += ["## 4. Response delay", ""]
    exact = [e for e in bset if derived[e["id"]].get("response_delay_s") is not None]
    bound = [e for e in bset if derived[e["id"]].get("response_delay_s") is None and derived[e["id"]].get("response_delay_bound_s") is not None]
    none_ = [e for e in bset if derived[e["id"]].get("response_delay_s") is None and derived[e["id"]].get("response_delay_bound_s") is None]
    vals = [derived[e["id"]]["response_delay_s"] for e in exact]
    wts = [e["amount_usd"] for e in exact]
    n_p = sum(1 for e in exact if derived[e["id"]]["response_basis"] == "pause")
    n_r = sum(1 for e in exact if derived[e["id"]]["response_basis"] == "pause report")
    L.append(f"- Determined for {len(exact)} events ({n_p} from a pause time, {len(exact) - n_p - n_r} from the acknowledgment, {n_r} from a dated pause report), "
             f"{100 * sum(wts) / tot_b:.1f}% of bridge-set value; upper bound only for {len(bound)} events; unknown for {len(none_)} events"
             + (f" ({', '.join(e['id'] for e in none_)})" if none_ else "") + ".")
    if vals:
        q1, med, q3 = quart(vals)
        L.append(f"- Mean response delay {hms(statistics.mean(vals))}; value-weighted mean "
                 f"{hms(sum(v * w for v, w in zip(vals, wts)) / sum(wts))}; median {hms(med)}; quartiles {hms(q1)} and {hms(q3)}.")
        pv = [derived[e["id"]]["response_delay_s"] for e in exact if derived[e["id"]]["response_basis"] == "pause"]
        av = [derived[e["id"]]["response_delay_s"] for e in exact if derived[e["id"]]["response_basis"] != "pause"]
        L.append(f"- Mean over the {len(pv)} events whose first documented response is a pause: {hms(statistics.mean(pv)) if pv else 'n.a.'}; "
                 f"over the other {len(av)}: {hms(statistics.mean(av)) if av else 'n.a.'}. Without the three events whose shortfall went "
                 f"unnoticed for days (Ronin 2022, Axelar-Secret, Nomic nBTC), the mean is "
                 f"{hms(statistics.mean([derived[e['id']]['response_delay_s'] for e in exact if e['id'] not in ('E13', 'E51', 'E65')]))}.")
    L.append("")
    L.append("Share of events and of value whose response delay exceeded h. An event known only through an upper bound counts as "
             "not exceeding h when the bound is at most h, and is left out otherwise.")
    L.append("")
    L.append("| h | events counted | events exceeding h | share of events | value exceeding h (M USD) | share of value |")
    L.append("|---|---:|---:|---:|---:|---:|")
    for lab, h in [("1 h", 3600), ("6 h", 21600), ("12 h", 43200), ("24 h", 86400), ("48 h", 172800)]:
        counted, over = [], []
        for e in bset:
            d = derived[e["id"]]
            if d.get("response_delay_s") is not None:
                counted.append(e)
                if d["response_delay_s"] > h:
                    over.append(e)
            elif d.get("response_delay_bound_s") is not None and d["response_delay_bound_s"] <= h:
                counted.append(e)
        vc = sum(e["amount_usd"] for e in counted)
        vo = sum(e["amount_usd"] for e in over)
        L.append(f"| {lab} | {len(counted)} | {len(over)} | {100 * len(over) / len(counted):.1f}% | {musd(vo)} | {100 * vo / vc:.1f}% |")
    L.append("")

    # 5. pooled shares
    L += ["## 5. Pooled share of value released within h of each event's first release", ""]
    L.append("| h | events with the share determined | their share of value | pooled share over them | bounds over the whole bridge set |")
    L.append("|---|---:|---:|---:|---|")
    for lab, h in HORIZONS:
        det_e = [e for e in bset if derived[e["id"]].get(f"share_{lab}")
                 and abs(derived[e["id"]][f"share_{lab}"][0] - derived[e["id"]][f"share_{lab}"][1]) < 1e-9]
        vd = sum(e["amount_usd"] for e in det_e)
        pooled = sum(e["amount_usd"] * derived[e["id"]][f"share_{lab}"][0] for e in det_e) / vd if vd else float("nan")
        lo = sum(e["amount_usd"] * (derived[e["id"]].get(f"share_{lab}") or (0, 1))[0] for e in bset) / tot_b
        hi = sum(e["amount_usd"] * (derived[e["id"]].get(f"share_{lab}") or (0, 1))[1] for e in bset) / tot_b
        L.append(f"| {HLABEL[lab]} | {len(det_e)} | {100 * vd / tot_b:.1f}% | {100 * pooled:.1f}% | {100 * lo:.1f}% to {100 * hi:.1f}% |")
    L.append("")
    L.append("Per event (share released within 10 min / 1 h / 6 h / 24 h; a range where not determined):")
    L.append("")
    for e in sorted(bset, key=lambda x: -x["amount_usd"]):
        d = derived[e["id"]]
        cells = [share_cell(d[f"share_{lab}"]) if d.get(f"share_{lab}") else "n.a." for lab, _ in HORIZONS]
        L.append(f"- {nm(e)} ({musd(e['amount_usd'])}M): " + " / ".join(cells))
    L.append("")

    # 6. value by class and side
    L += ["## 6. Value by failure class and by release side (bridge set)", ""]
    L.append("| failure class | events | value (M USD) | share of value |")
    L.append("|---|---:|---:|---:|")
    for c, lab in [("V", "V: authorizing keys or parties under outside control"),
                   ("D", "D: release-side verification accepted an invalid message"),
                   ("S", "S: origin-side logic recorded an unbacked lock, deposit or burn"),
                   ("O", "O: other or unclear")]:
        es = [e for e in bset if e.get("failure_class") == c]
        v = sum(e["amount_usd"] for e in es)
        L.append(f"| {lab} | {len(es)} | {musd(v)} | {100 * v / tot_b:.1f}% |")
    L.append("")
    L.append("| release side | events | value (M USD) | share of value |")
    L.append("|---|---:|---:|---:|")
    for sd in ["escrow", "mint", "both", "other", ""]:
        es = [e for e in bset if (e.get("release_side") or "") == sd]
        if not es and sd == "":
            continue
        v = sum(e["amount_usd"] for e in es)
        L.append(f"| {sd or 'not determined'} | {len(es)} | {musd(v)} | {100 * v / tot_b:.1f}% |")
    L.append("")
    split = [e for e in bset if e.get("release_side") == "both" and e.get("both_escrow_share") is not None]
    if split:
        esc = sum(e["amount_usd"] * e["both_escrow_share"] for e in split)
        mnt = sum(e["amount_usd"] * (1 - e["both_escrow_share"]) for e in split)
        esc_only = sum(e["amount_usd"] for e in bset if e.get("release_side") == "escrow")
        L.append(f"Within `both` ({', '.join(e['id'] for e in split)} have published shares), {musd(esc)}M USD was redeemed against an "
                 f"escrow and {musd(mnt)}M USD was realized from minted claims alone. Counting redemptions as escrow outflows, value that "
                 f"left an escrow is {100 * (esc_only + esc) / tot_b:.1f}% of the bridge set.")
        L.append("")
    L.append("Cross-tabulation, value in M USD (events):")
    L.append("")
    L.append("| class | escrow | mint | both | other |")
    L.append("|---|---:|---:|---:|---:|")
    for c in ["V", "D", "S", "O"]:
        cells = []
        for sd in ["escrow", "mint", "both", "other"]:
            es = [e for e in bset if e.get("failure_class") == c and e.get("release_side") == sd]
            cells.append(f"{musd(sum(e['amount_usd'] for e in es))} ({len(es)})" if es else "-")
        L.append(f"| {c} | " + " | ".join(cells) + " |")
    L.append("")

    # 7. limits and recoveries
    L += ["## 7. Limits in force, and recoveries (bridge set)", ""]
    lim = [e for e in bset if e.get("limit_in_force") not in ("", None, "none reported")
           and not str(e.get("limit_in_force")).startswith("none")]
    L.append(f"- A limit, delay or automatic halt is documented for {len(lim)} of {len(bset)} events:")
    for e in lim:
        L.append(f"  - {nm(e)}: {e['limit_in_force']}. Acted: {e.get('limit_acted') or 'not documented'}.")
    none_v = [e for e in bset if str(e.get("limit_in_force", "")).startswith("none") and e.get("limit_in_force") != "none reported"]
    nr = [e for e in bset if e.get("limit_in_force") in ("none reported", "", None)]
    L.append(f"- Documented absence of any limit: {len(none_v)} events ({', '.join(e['id'] for e in none_v)}). "
             f"No source on limits: {len(nr)} events.")
    rec = [e for e in bset if e.get("recovered_usd") not in (None, "")]
    L.append(f"- Recovered (returned or seized; operator reimbursement excluded) where documented: {len(rec)} events, "
             f"{musd(sum(e['recovered_usd'] for e in rec))}M USD ({100 * sum(e['recovered_usd'] for e in rec) / tot_b:.1f}% of "
             f"bridge-set value); frozen in place: {musd(sum(e.get('frozen_usd') or 0 for e in bset))}M USD.")
    L.append("")
    L += ["## 8. Caveats", ""] + MD_CAVEATS + [""]
    (RESULTS / "incidents.md").write_text("\n".join(L), encoding="utf-8")


if __name__ == "__main__":
    main()
