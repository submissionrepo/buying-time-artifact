"""E11 completeness check: token balance of the bridge over the window against logged flows.

For each of the largest released assets: balance(end) - balance(start) should equal
  inbound Transfer logs (to the bridge) [+ WETH Deposit logs with the bridge as dst]
  - outbound Transfer logs (from the bridge, all recipients) [- WETH Withdrawal logs with the bridge as src].
A non-zero residual means a flow the logs do not show (or a non-standard token).
Inbound logs are cached under raw/E11/inbound/. Writes raw/E11/reconcile.json (labels only, no addresses).
Run after build_e11.py: python -I reconcile_e11.py [n_assets] [comma-separated labels to include first]
"""
import collections
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent / "incidents"))
from rpc import Rpc, TRANSFER, WETH_WITHDRAWAL, topic_addr  # noqa: E402

RAW = HERE / "raw" / "E11"
T = json.loads((HERE.parent / "incidents" / "onchain_targets.json").read_text())["E11_eth"]
BRIDGE = T["custody"][0].lower()
WETH = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"
DEPOSIT = "0xe1fffcc4923d04b559f4d29a8bfc6cda04eb5b0d3c460751c2402c5c5cc9109c"
STEP = 5000


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 12
    meta = json.loads((RAW / "window.json").read_text())
    assets = json.loads((RAW / "assets.json").read_text())
    r = Rpc("ethereum")
    out_d = RAW / "inbound"
    out_d.mkdir(exist_ok=True)
    b = meta["b0"]
    inbound, dep = [], []
    while b <= meta["b1"]:
        e = min(b + STEP - 1, meta["b1"])
        f = out_d / f"in_{b}_{e}.json"
        if not f.exists():
            tin = r.logs(None, [TRANSFER, None, topic_addr(BRIDGE)], b, e, step=STEP)
            d = r.logs(WETH, [DEPOSIT, topic_addr(BRIDGE)], b, e, step=STEP)
            f.write_text(json.dumps({"transfer_in": [{k: l[k] for k in ("address", "topics", "data")} for l in tin],
                                     "deposit": [{k: l[k] for k in ("address", "topics", "data")} for l in d]}))
        c = json.loads(f.read_text())
        inbound += c["transfer_in"]
        dep += c["deposit"]
        b = e + 1
    outb = []
    for p in RAW.glob("chunk_*.json"):
        c = json.loads(p.read_text())
        outb += [("t", l) for l in c["transfer"]] + [("w", l) for l in c["withdrawal"]]
    flow = collections.defaultdict(lambda: collections.Counter())
    for l in inbound:
        if len(l["topics"]) == 3:
            flow[l["address"].lower()]["in"] += int(l["data"], 16) if l["data"] not in ("0x", "") else 0
    for l in dep:
        flow[WETH]["in"] += int(l["data"], 16)
    for kind, l in outb:
        if kind == "w":
            flow[WETH]["out"] += int(l["data"], 16)
        elif len(l["topics"]) == 3:
            flow[l["address"].lower()]["out"] += int(l["data"], 16) if l["data"] not in ("0x", "") else 0
    # largest released assets by row count of the build output is not address-bearing; use outflow raw/decimals
    # rank by priced USD released per asset label in E11.csv (labels only)
    import csv
    usd = collections.Counter()
    for row in csv.DictReader(open(HERE / "E11.csv", encoding="utf-8")):
        usd[row["asset"]] += float(row["usd"]) if row["usd"] else 0.0
    # assets that the CSV leaves unpriced are ranked by released quantity for the ones named on the command line
    extra = set(sys.argv[2].split(",")) if len(sys.argv) > 2 else set()
    rank = sorted((t for t in flow if t in assets),
                  key=lambda t: (-(assets[t]["label"] in extra), -usd[assets[t]["label"]]))
    res = {}
    for tok in rank[:n]:
        sel = "0x70a08231" + "0" * 24 + BRIDGE[2:]
        try:
            b0 = int(r.eth_call(tok, sel, meta["b0"] - 1), 16)
            b1 = int(r.eth_call(tok, sel, meta["b1"]), 16)
        except Exception as e:  # noqa: BLE001
            res[assets[tok]["label"]] = {"error": str(e)[:120]}
            continue
        dec = 10 ** assets[tok]["decimals"]
        resid = b1 - b0 - flow[tok]["in"] + flow[tok]["out"]
        res[assets[tok]["label"]] = {"balance_start": b0 / dec, "balance_end": b1 / dec, "in": flow[tok]["in"] / dec,
                                     "out": flow[tok]["out"] / dec, "residual": resid / dec,
                                     "residual_share_of_out": resid / flow[tok]["out"] if flow[tok]["out"] else None}
    (RAW / "reconcile.json").write_text(json.dumps(res, indent=1))
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
