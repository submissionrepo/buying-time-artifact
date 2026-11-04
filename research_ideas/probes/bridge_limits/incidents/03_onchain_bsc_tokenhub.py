"""BSC Token Hub event (E16, 2022-10-06): release times and the chain halt, from BSC data (2026-10-16).

Reads the Token Hub address and block window from data/incidents/onchain_targets.json (key E16_bsc).
Releases: Token Hub logs whose data carries an amount word of at least `min_native` BNB (1M BNB each).
Halt: the largest gap between consecutive block timestamps inside the window after the last release.
Writes data/incidents/onchain/E16_bsc.json (raw, with hashes) and the E16_bsc entry of
data/incidents/onchain_summary.json (no addresses or hashes).
"""
import datetime
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from rpc import Rpc  # noqa: E402

DATA = pathlib.Path(__file__).resolve().parent.parent / "data" / "incidents"


def iso(ts):
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main():
    t = json.loads((DATA / "onchain_targets.json").read_text())["E16_bsc"]
    r = Rpc("bsc")
    b0, b1 = t["block_from"], t["block_to"]
    rows = []
    for lg in r.logs(t["hub"], [t["topic0"]], b0, b1, step=2000):
        data = lg["data"][2:]
        words = [int(data[i:i + 64], 16) for i in range(0, len(data), 64)]
        amt = [w for w in words if w == t["amount_wei"]]
        if amt:
            blk = int(lg["blockNumber"], 16)
            rows.append({"block": blk, "ts": r.block_ts(blk), "amount_bnb": amt[0] / 1e18, "tx": lg["transactionHash"]})
    rows.sort(key=lambda x: x["block"])
    # halt: scan block timestamps from the last release to the end of the window for the largest gap
    last = rows[-1]["block"]
    lo, hi = t["halt_search_from"], t["halt_search_to"]
    prev_ts = r.block_ts(lo)
    gap = (0, None, None)
    for b in range(lo + 1, hi + 1):
        ts = r.block_ts(b)
        if ts - prev_ts > gap[0]:
            gap = (ts - prev_ts, b - 1, b)
        prev_ts = ts
    halt_last_block, resume_block = gap[1], gap[2]
    halt_ts, resume_ts = r.block_ts(halt_last_block), r.block_ts(resume_block)
    out = {"rows": rows, "halt_last_block": halt_last_block, "halt_last_ts": halt_ts,
           "resume_block": resume_block, "resume_ts": resume_ts, "gap_s": gap[0], "last_release_block": last}
    (DATA / "onchain" / "E16_bsc.json").write_text(json.dumps(out, indent=1))
    price = t["bnb_usd"]
    t0 = rows[0]["ts"]
    s = {"target": "E16_bsc", "event_id": "E16", "leg": "BSC Token Hub (destination-side release)", "chain": "bsc",
         "selection": "Token Hub transfer-in logs of exactly 1,000,000 BNB", "classified": False,
         "n_candidate_rows": len(rows), "n_selected_rows": len(rows),
         "first_release_utc": iso(t0), "last_release_utc": iso(rows[-1]["ts"]),
         "duration_s": rows[-1]["ts"] - t0, "n_release_tx": len(rows),
         "usd_total": sum(x["amount_bnb"] for x in rows) * price, "usd_missing_rows": 0,
         "by_symbol": {"BNB": {"amount": sum(x["amount_bnb"] for x in rows),
                               "usd": sum(x["amount_bnb"] for x in rows) * price}},
         "path": [[x["ts"] - t0, x["amount_bnb"] * price] for x in rows],
         "share_within": {str(h): sum(x["amount_bnb"] for x in rows if x["ts"] - t0 <= h) /
                          sum(x["amount_bnb"] for x in rows) for h in (600, 3600, 21600, 86400)},
         "pause_logs": [{"label": "chain halt (last block before the gap)", "utc": iso(halt_ts),
                         "lag_from_first_release_s": halt_ts - t0},
                        {"label": "chain resumed (first block after the gap)", "utc": iso(resume_ts),
                         "lag_from_first_release_s": resume_ts - t0}],
         "price_note": f"BNB valued at {price} USD (DefiLlama historical price at the first release)"}
    sp = DATA / "onchain_summary.json"
    summ = json.loads(sp.read_text())
    summ["E16_bsc"] = s
    sp.write_text(json.dumps(summ, indent=1))
    print(json.dumps({k: s[k] for k in ("first_release_utc", "last_release_utc", "duration_s", "n_release_tx",
                                         "usd_total", "pause_logs")}, indent=1))


if __name__ == "__main__":
    main()
