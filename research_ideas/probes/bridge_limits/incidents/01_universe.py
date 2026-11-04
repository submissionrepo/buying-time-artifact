"""Event universe for the bridge drain dataset (2026-10-16).

Universe = union of
  (a) DefiLlama incident records (api.llama.fi/hacks, raw copy downloaded 2026-10-15 to
      data/incidents/defillama_hacks_20261015.json) with bridgeHack = true, amount >= 1M USD,
      dated 2021-01-01 .. 2026-12-31;
  (b) DefiLlama records in the same window and size class whose classification is
      "Bridge & Cross-Chain" but which are not flagged bridgeHack;
  (c) incidents of at least 1M USD in the SoK tables (Augusto et al., IEEE S&P 2024, Tables 5 and 8,
      transcribed from those tables) that DefiLlama does not flag as bridge
      incidents (BXH 2021-10, Multichain 2022-01, QANplatform 2022-10, Mixin 2023-09).

Writes data/incidents/universe.json (no addresses or hashes; DefiLlama fields only plus an event id).
Run: python -I incidents/01_universe.py
"""
import datetime
import json
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
DATA = HERE.parent / "data" / "incidents"
RAW = DATA / "defillama_hacks_20261015.json"
OUT = DATA / "universe.json"

T0 = datetime.datetime(2021, 1, 1, tzinfo=datetime.timezone.utc).timestamp()
T1 = datetime.datetime(2027, 1, 1, tzinfo=datetime.timezone.utc).timestamp()

# SoK-only additions: (DefiLlama name, DefiLlama date) when DefiLlama has the record unflagged,
# with the SoK row they correspond to.
SOK_ONLY = {
    ("BXH", "2021-10-30"): "SoK Table 5 row 6 / Table 8: BXH, Oct 2021, 139M",
    ("Multichain", "2022-01-18"): "SoK Table 5 row 17 / Table 8: Multichain #1, Jan 2022, 3M",
    ("QANplatform", "2022-10-11"): "SoK Table 8: QANplatform, Oct 2022, 2.00M",
    ("Mixin Network", "2023-09-23"): "SoK Table 8: Mixin Network, Sep 2023, 200.00M",
}


def day(ts):
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime("%Y-%m-%d")


def main():
    recs = json.loads(RAW.read_text(encoding="utf-8"))
    rows = []
    for r in recs:
        ts = r.get("date") or 0
        amt = r.get("amount") or 0
        if not (T0 <= ts < T1) or amt < 1e6:
            continue
        key = (r.get("name"), day(ts))
        if r.get("bridgeHack"):
            basis = "DefiLlama bridgeHack=true"
        elif r.get("classification") == "Bridge & Cross-Chain":
            basis = "DefiLlama classification 'Bridge & Cross-Chain' (bridgeHack=false)"
        elif key in SOK_ONLY:
            basis = "SoK table (DefiLlama bridgeHack=false): " + SOK_ONLY[key]
        else:
            continue
        rows.append({
            "dl_date": day(ts),
            "dl_name": r.get("name"),
            "dl_amount_usd": amt,
            "dl_chain": r.get("chain"),
            "dl_classification": r.get("classification"),
            "dl_technique": r.get("technique"),
            "dl_returned": r.get("returnedFunds"),
            "dl_id": r.get("defillamaId"),
            "basis": basis,
        })
    rows.sort(key=lambda x: (x["dl_date"], x["dl_name"]))
    for i, x in enumerate(rows, 1):
        x["event_id"] = f"E{i:02d}"
    OUT.write_text(json.dumps(rows, indent=1, ensure_ascii=False), encoding="utf-8")
    for x in rows:
        print(x["event_id"], x["dl_date"], x["dl_name"], round(x["dl_amount_usd"] / 1e6, 2), "|", x["basis"][:40])
    print(len(rows), "records ->", OUT)


if __name__ == "__main__":
    main()
