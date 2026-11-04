"""Agreement between the paper's coding and the blind recoding (coding/blind_coding.csv), 2026-10-16.

Class: the paper's failure_class (results/incidents.csv: S, V, D, O) against the blind class (EVENT,
KEYS, CHECK, OTHER); Cohen's kappa over the 57 failures, the value share of the disagreements, and the
verifier-side share of value under the blind coding (class EVENT whole, plus the legs the blind coder
marked as passing the verifiers for the other classes), against the paper's (replay_incidents.
verifier_share). Pause holder: incident_coding.csv against the blind field.
Writes results/blind_agreement.json and prints a summary.
"""
import csv
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
import replay_incidents as ri  # noqa: E402

MAP = {"EVENT": "S", "KEYS": "V", "CHECK": "D", "OTHER": "O"}


def kappa(a, b, cats):
    n = len(a)
    po = sum(x == y for x, y in zip(a, b)) / n
    pe = sum((a.count(c) / n) * (b.count(c) / n) for c in cats)
    return (po - pe) / (1 - pe) if pe < 1 else 1.0


def legs_verifier_share(legs, through):
    """Share of value on legs marked as passing the verifiers; a redeemed leg counts once."""
    try:
        parts = [x.split(":") for x in legs.split(";") if x.strip()]
        flags = [x.strip() for x in through.split(";")]
        shares = [float(p[2]) for p in parts]
    except (IndexError, ValueError):
        return None
    s = sum(sh for sh, f in zip(shares, flags) if f == "yes")
    return min(1.0, s)


def main():
    inc = {r["id"]: r for r in csv.DictReader(open(ROOT / "results" / "incidents.csv", encoding="utf-8"))
           if r["in_bridge_set"].strip().lower() in ("yes", "true", "1")}
    cod = {r["id"]: r for r in csv.DictReader(open(ROOT / "results" / "incident_coding.csv", encoding="utf-8"))}
    blind = {r["id"]: r for r in csv.DictReader(open(HERE / "blind_coding.csv", encoding="utf-8"))}
    ids = sorted(i for i in inc if i in blind)
    missing = sorted(set(inc) - set(blind))
    A = {i: float(inc[i]["amount_usd"] or 0) for i in ids}
    tot = sum(A.values())
    ours = [(inc[i]["failure_class"] or "O")[:1] for i in ids]
    theirs = [MAP.get(blind[i]["class"].strip().upper(), "?") for i in ids]
    dis = [i for i, x, y in zip(ids, ours, theirs) if x != y]
    out = {"n": len(ids), "missing": missing, "agree": len(ids) - len(dis), "kappa": kappa(ours, theirs, "SVDO"),
           "disagreements": [{"id": i, "ours": (inc[i]["failure_class"] or "O")[:1], "blind": blind[i]["class"],
                              "confidence": blind[i]["confidence"], "usd": A[i], "rationale": blind[i]["rationale"]}
                             for i in dis],
           "disagreement_value_share": sum(A[i] for i in dis) / tot,
           "by_class_ours": {c: ours.count(c) for c in "SVDO"},
           "by_class_blind": {c: theirs.count(c) for c in "SVDO?"}}
    ver_ours = sum(A[i] * ri.verifier_share({"id": i, "cls": (inc[i]["failure_class"] or "O")[:1]}) for i in ids) / tot
    vb = {}
    for i in ids:
        if MAP.get(blind[i]["class"].strip().upper()) == "S":
            vb[i] = A[i]
        else:
            s = legs_verifier_share(blind[i]["legs"], blind[i]["legs_through_verifiers"])
            vb[i] = A[i] * (s or 0.0)
    out["verifier_share_ours"] = ver_ours
    out["verifier_share_blind"] = sum(vb.values()) / tot
    # the same share over the failures with a recorded response, the base of the paper's
    # verifier-side ceiling (replay_incidents.load keeps those with a response delay)
    timed = [i for i in ids if (inc[i].get("response_delay_s") or "").strip()]
    out["verifier_share_blind_timed"] = sum(vb[i] for i in timed) / sum(A[i] for i in timed)
    # release points that could not host a contract limit: custody held directly by keys or on a chain
    # without programmable custody (blind coder's release_point_contract == no)
    held = [i for i in ids if blind[i]["release_point_contract"].strip().lower() == "no"]
    out["keys_held_n"] = len(held)
    out["keys_held_value_share"] = sum(A[i] for i in held) / tot
    out["keys_held_ids"] = held
    ph = [(cod[i]["pause_holder"], blind[i]["pause_holder"]) for i in ids if i in cod]
    out["pause_holder_agree"] = sum(a == b for a, b in ph)
    out["pause_holder_n"] = len(ph)
    (ROOT / "results" / "blind_agreement.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in out.items() if k != "disagreements"}, indent=1))
    for d in out["disagreements"]:
        print(f"  {d['id']}: ours {d['ours']} blind {d['blind']} ({d['confidence']}), {d['usd'] / 1e6:.1f}M: {d['rationale'][:160]}")


if __name__ == "__main__":
    main()
