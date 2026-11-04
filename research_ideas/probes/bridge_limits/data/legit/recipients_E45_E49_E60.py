"""Recipient concentration of the legit release series (E45, E49, E60), for the READMEs (2026-10-16).

Reads raw/<ID>/rows_with_detail.json (written by collect_legit_E45_E49_E60.py build). For the recipients that
take the most USD it records whether the address has code and, for contracts, the verified contract name
(eth.blockscout.com API) and the transaction count of plain accounts. Output (addresses stay in raw/):
raw/<ID>/recipients.json; the README quotes only aggregate shares and contract names.
Run: python -I -B data/legit/recipients_E45_E49_E60.py E45|E49|E60 [top_n]
"""
import collections
import json
import pathlib
import sys
import time
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent / "incidents"))
from rpc import Rpc  # noqa: E402

UA = {"User-Agent": "bridge-limits-probe/1.0"}


def blockscout(addr):
    for k in range(4):
        try:
            u = f"https://eth.blockscout.com/api/v2/addresses/{addr}"
            with urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=60) as r:
                return json.loads(r.read().decode())
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(2 * (k + 1))
    return {"error": str(last)}


def main(eid, top_n=15):
    rd = HERE / "raw" / eid
    rows = json.loads((rd / "rows_with_detail.json").read_text())
    rpc = Rpc("ethereum")
    rpc.urls = ["https://rpc.mevblocker.io", "https://eth.drpc.org"]
    tot = sum(r["usd"] or 0.0 for r in rows)
    by = collections.defaultdict(lambda: [0, 0.0])
    for r in rows:
        by[r["to"]][0] += 1
        by[r["to"]][1] += r["usd"] or 0.0
    ranked = sorted(by.items(), key=lambda kv: -kv[1][1])
    out = {"n_recipients": len(by), "usd_total": tot, "top": []}
    cum = 0.0
    for i, (a, (n, u)) in enumerate(ranked[:top_n]):
        cum += u
        code = rpc.call("eth_getCode", [a, "latest"])
        info = blockscout(a)
        out["top"].append({"rank": i + 1, "address": a, "n": n, "usd": u, "share": u / tot if tot else None,
                           "cum_share": cum / tot if tot else None, "is_contract": bool(code and len(code) > 2),
                           "name": info.get("name"), "is_verified": info.get("is_verified"),
                           "implementations": [x.get("name") for x in (info.get("implementations") or [])],
                           "tx_count_note": None})
        time.sleep(0.3)
    for k in (1, 5, 10, 20):
        out[f"top{k}_share"] = sum(u for _, (n, u) in ranked[:k]) / tot if tot else None
    (rd / "recipients.json").write_text(json.dumps(out, indent=1))
    for t in out["top"]:
        print(t["rank"], t["n"], round(t["usd"]), round(t["share"], 4), round(t["cum_share"], 4), t["is_contract"], t["name"], t["implementations"])
    print({k: v for k, v in out.items() if k.startswith("top") and k != "top"}, "recipients", out["n_recipients"])


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 15)
