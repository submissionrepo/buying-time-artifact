"""Legitimate release history of a failed bridge gateway over the 150 days before its failure (2026-10-16).

Inputs  results/incidents.csv                      (failure time)
        data/incidents/onchain_targets.json        (release-point contracts; read only)
        data/incidents/onchain/<target>.json        (the failure's own releases, for exclusion; read only)
Outputs data/legit/<ID>.csv                         (no addresses or hashes)
        data/legit/raw/<ID>/                        (raw RPC and price caches; addresses live here only)
        data/legit/raw/<ID>/summary.json            (numbers quoted in the README)

Method
- Window: [t_fail - 150 d, t_fail - 1 s], t_fail = first unauthorized release (block timestamp).
- Release record: the gateway's own release event. Ronin v1 gateway: TokenWithdrew(uint256 indexed id,
  address indexed owner, address indexed token, uint256 amount). Ronin v2/v3 gateway (MainchainGatewayV3 in
  axieinfinity/ronin-bridge-contracts): Withdrew(bytes32, Transfer.Receipt), emitted on direct release and on
  unlock of a locked withdrawal. One event = one release (kind "event").
- Reconciliation: every ERC-20 Transfer log with the gateway as sender, and every value-bearing call trace from
  the gateway (trace_filter), is matched to a release event in the same transaction. Unmatched outflows are
  listed by kind ("erc20", "native") and classified; only those that are payments to outside parties enter the
  CSV. Native outflows inside reverted transactions (trace_filter returns them) are dropped after a receipt check.
- Prices: DefiLlama /chart hourly series (nearest point within 2 h; a 500-hour request that returns fewer
  than 450 points is repeated with searchWidth=1800 and merged); fallback daily series (nearest point
  within 36 h); otherwise unpriced.
Run: python -I data/legit/build_legit.py E13|E30
"""
import bisect
import collections
import csv
import datetime
import json
import pathlib
import sys
import time
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT / "incidents"))
from rpc import Rpc, TRANSFER, topic_addr, addr_from_topic, erc20_meta  # noqa: E402

TOKEN_WITHDREW = "0x86174ea401f083b9bb1bdebca3068f27fb023c7091365ed2a8a02b8d75cf0e52"
TOKEN_DEPOSITED = "0x72848855a2461abf0dd243723dfcc9163eec2ea5215469d101c0d9c9ef58940d"
WITHDREW = "0x21e88e956aa3e086f6388e899965cef814688f99ad8bb29b08d396571016372d"
DEPOSIT_REQUESTED = "0xd7b25068d9dc8d00765254cfb7f5070f98d263c8d68931d937c7362fa738048b"
WITHDRAWAL_LOCKED = "0x89e52969465b1f1866fc5d46fd62de953962e9cb33552443cd999eba05bd20dc"
WITHDRAWAL_UNLOCKED = "0xd639511b37b3b002cca6cfe6bca0d833945a5af5a045578a0627fc43b79b2630"
WETH = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"

CFG = {
    "E13": {"target": "E13_eth", "mode": "v1", "leg": "Ethereum gateway (v1)"},
    "E30": {"target": "E30_eth", "mode": "v3", "leg": "Ethereum gateway (v2/v3)"},
}
WINDOW_S = 150 * 86400
LOG_STEP = 5000
TRACE_STEP = 2000


def iso(ts):
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def to_ts(s):
    return int(datetime.datetime.fromisoformat(s.replace("Z", "")).replace(tzinfo=datetime.timezone.utc).timestamp())


def cached(path, fn):
    if path.exists():
        return json.loads(path.read_text())
    v = fn()
    path.write_text(json.dumps(v))
    return v


def http_json(url, tries=5):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "bridge-limits-probe/1.0"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode())
        except Exception as e:
            last = e
            time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"{url}: {last}")


def failure_time(eid):
    with open(ROOT / "results" / "incidents.csv", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["id"] == eid:
                return to_ts(r["first_release_utc"])
    raise KeyError(eid)


def chunked_logs(rpc, address, topics, b0, b1, cdir, tag):
    out = []
    for s in range(b0, b1 + 1, LOG_STEP):
        e = min(s + LOG_STEP - 1, b1)
        p = cdir / f"{tag}_{s}_{e}.json"
        out += cached(p, lambda: rpc.logs(address, topics, s, e, step=LOG_STEP))
    return out


def chunked_traces(rpc, addr, b0, b1, cdir):
    out = []
    for s in range(b0, b1 + 1, TRACE_STEP):
        e = min(s + TRACE_STEP - 1, b1)
        p = cdir / f"tr_{s}_{e}.json"

        def fetch():
            res = rpc.trace_filter([addr], s, e, step=TRACE_STEP)
            keep = []
            for x in res:
                a = x.get("action", {})
                if x.get("type") == "call" and a.get("callType") == "call" and int(a.get("value", "0x0"), 16) > 0:
                    keep.append({"blockNumber": x["blockNumber"], "transactionHash": x["transactionHash"],
                                 "to": (a.get("to") or "").lower(), "value": a.get("value"),
                                 "traceAddress": x.get("traceAddress")})
            return keep
        out += cached(p, fetch)
    return out


def is_nft(rpc, token, cache):
    if token in cache:
        return cache[token]
    v = False
    try:
        r = rpc.eth_call(token, "0x01ffc9a780ac58cd00000000000000000000000000000000000000000000000000000000")
        v = bool(r and r != "0x" and int(r, 16) == 1)
    except Exception:
        v = False
    cache[token] = v
    return v


class Prices:
    def __init__(self, cdir, t0, t1):
        self.cdir, self.t0, self.t1 = cdir, t0, t1
        self.series = {}

    def _load(self, cid):
        if cid in self.series:
            return self.series[cid]
        safe = cid.replace(":", "_")
        hourly, daily = [], []
        t = self.t0 - 3 * 3600
        while t < self.t1 + 3600:
            p = self.cdir / f"px1h_{safe}_{t}.json"
            j = cached(p, lambda: http_json(f"https://coins.llama.fi/chart/{cid}?start={t}&span=500&period=1h"))
            pts = [(q["timestamp"], q["price"]) for q in (j.get("coins", {}).get(cid, {}).get("prices") or [])]
            if len(pts) < 450:
                # the default 600 s search width leaves holes in older hourly data; 1800 s fills them
                p2 = self.cdir / f"px1h_{safe}_{t}_sw1800.json"
                j2 = cached(p2, lambda: http_json(
                    f"https://coins.llama.fi/chart/{cid}?start={t}&span=500&period=1h&searchWidth=1800"))
                pts += [(q["timestamp"], q["price"]) for q in (j2.get("coins", {}).get(cid, {}).get("prices") or [])]
            hourly += pts
            t += 500 * 3600
        p = self.cdir / f"px1d_{safe}_{self.t0}.json"
        j = cached(p, lambda: http_json(
            f"https://coins.llama.fi/chart/{cid}?start={self.t0 - 2 * 86400}&span=160&period=1d"))
        daily = [(q["timestamp"], q["price"]) for q in (j.get("coins", {}).get(cid, {}).get("prices") or [])]
        hourly, daily = sorted(set(hourly)), sorted(set(daily))
        self.series[cid] = (hourly, daily)
        return self.series[cid]

    @staticmethod
    def _near(series, ts, tol):
        if not series:
            return None
        xs = [s[0] for s in series]
        i = bisect.bisect_left(xs, ts)
        best = None
        for j in (i - 1, i):
            if 0 <= j < len(series):
                d = abs(series[j][0] - ts)
                if d <= tol and (best is None or d < best[0]):
                    best = (d, series[j][1])
        return best[1] if best else None

    def price(self, cid, ts):
        hourly, daily = self._load(cid)
        p = self._near(hourly, ts, 2 * 3600)
        if p is not None:
            return p, "defillama chart 1h"
        p = self._near(daily, ts, 36 * 3600)
        if p is not None:
            return p, "defillama chart 1d"
        return None, ""


def main(eid):
    cfg = CFG[eid]
    targets = json.loads((ROOT / "data" / "incidents" / "onchain_targets.json").read_text())
    tgt = targets[cfg["target"]]
    gw = tgt["custody"][0].lower()
    fail = json.loads((ROOT / "data" / "incidents" / "onchain" / f"{cfg['target']}.json").read_text())
    fail_to = {r["to"] for r in fail["rows"] if r.get("selected")}
    fail_to |= {a.lower() for a in tgt.get("recipients", [])}
    t_fail = failure_time(eid)
    t_start, t_end = t_fail - WINDOW_S, t_fail - 1
    cdir = HERE / "raw" / eid
    cdir.mkdir(parents=True, exist_ok=True)
    rpc = Rpc("ethereum")
    rpc.urls = ["https://rpc.mevblocker.io", "https://mainnet.gateway.tenderly.co"]
    rt = Rpc("ethereum_trace")

    def blocks():
        b0 = rpc.block_at(t_start)
        bf = rpc.block_at(t_fail)
        return [b0, bf - 1, rpc.block_ts(b0), rpc.block_ts(bf - 1), rpc.block_ts(bf)]
    b0, b1, ts_b0, ts_b1, ts_bf = cached(cdir / "blocks.json", blocks)
    assert ts_b0 >= t_start and ts_b1 <= t_end and ts_bf >= t_fail, (ts_b0, ts_b1, ts_bf)
    print(eid, "blocks", b0, b1, iso(ts_b0), iso(ts_b1), flush=True)

    logs = chunked_logs(rpc, gw, None, b0, b1, cdir, "gw")
    print("gateway logs", len(logs), flush=True)
    xfers = chunked_logs(rpc, None, [TRANSFER, topic_addr(gw)], b0, b1, cdir, "xf")
    print("erc20 transfers out", len(xfers), flush=True)
    traces = chunked_traces(rt, gw, b0, b1, cdir)
    print("native traces out", len(traces), flush=True)

    meta, nft = {}, {}
    mf = cdir / "token_meta.json"
    if mf.exists():
        j = json.loads(mf.read_text())
        meta = {k: tuple(v) for k, v in j["meta"].items()}
        nft = j["nft"]

    topic_counts = collections.Counter(lg["topics"][0] for lg in logs if lg["topics"])
    events = []
    locked, unlocked = [], []
    for lg in logs:
        t0 = lg["topics"][0] if lg["topics"] else None
        ts = int(lg["blockTimestamp"], 16)
        blk = int(lg["blockNumber"], 16)
        if cfg["mode"] == "v1" and t0 == TOKEN_WITHDREW:
            tok = addr_from_topic(lg["topics"][3]).lower()
            to = addr_from_topic(lg["topics"][2]).lower()
            raw = int(lg["data"], 16)
            wid = int(lg["topics"][1], 16)
        elif cfg["mode"] == "v3" and t0 in (WITHDREW, WITHDRAWAL_LOCKED, WITHDRAWAL_UNLOCKED):
            w = [lg["data"][2 + 64 * i: 2 + 64 * (i + 1)] for i in range(12)]
            wid = int(w[1], 16)
            to = "0x" + w[3][-40:]
            tok = ("0x" + w[4][-40:]).lower()
            erc = int(w[9], 16)
            raw = int(w[11], 16) if erc == 0 else int(w[10], 16)
            if t0 == WITHDRAWAL_LOCKED:
                locked.append({"id": wid, "ts": ts, "token": tok, "raw": raw})
                continue
            if t0 == WITHDRAWAL_UNLOCKED:
                unlocked.append({"id": wid, "ts": ts, "token": tok, "raw": raw})
                continue
        else:
            continue
        events.append({"id": wid, "ts": ts, "block": blk, "tx": lg["transactionHash"], "to": to.lower(),
                       "token": tok, "raw": raw, "logIndex": int(lg["logIndex"], 16)})
    toks = sorted({e["token"] for e in events} | {x["address"].lower() for x in xfers})
    for tk in toks:
        if tk not in meta:
            meta[tk] = erc20_meta(rpc, tk, {})
        if tk not in nft:
            nft[tk] = is_nft(rpc, tk, {})
    mf.write_text(json.dumps({"meta": meta, "nft": nft}, indent=1))

    # reconciliation by transaction
    ev_tx = collections.defaultdict(list)
    for e in events:
        ev_tx[e["tx"]].append(e)
    unmatched_x, unmatched_n = [], []
    matched_native_tx = set()
    for x in xfers:
        if len(x["topics"]) != 3:
            continue
        tok = x["address"].lower()
        to = addr_from_topic(x["topics"][2]).lower()
        raw = int(x["data"], 16) if x["data"] not in ("0x", "") else 0
        if x["transactionHash"] in ev_tx and any(e["token"] == tok for e in ev_tx[x["transactionHash"]]):
            continue
        unmatched_x.append({"ts": int(x["blockTimestamp"], 16), "block": int(x["blockNumber"], 16),
                            "tx": x["transactionHash"], "to": to, "token": tok, "raw": raw})
    for n in traces:
        if n["transactionHash"] in ev_tx and any(e["token"] == WETH for e in ev_tx[n["transactionHash"]]):
            matched_native_tx.add(n["transactionHash"])
            continue
        unmatched_n.append({"block": n["blockNumber"], "tx": n["transactionHash"], "to": n["to"],
                            "raw": int(n["value"], 16)})
    # WETH events released as native ETH?
    weth_ev_tx = {e["tx"] for e in events if e["token"] == WETH}
    weth_native = len(weth_ev_tx & matched_native_tx)

    def classify(to):
        if to == gw:
            return "internal: to the gateway itself"
        if to in fail_to:
            return "failure: recipient of the failure releases"
        if to == WETH:
            return "internal: wrap into WETH"
        return "outside party"

    for u in unmatched_x + unmatched_n:
        u["class"] = classify(u["to"])

    # Block timestamps and receipt status, fetched only for native outflows to outside parties.
    # trace_filter also returns calls inside transactions that reverted; those moved nothing.
    out_n = [n for n in unmatched_n if n["class"] == "outside party"]
    tsf, stf = cdir / "block_ts.json", cdir / "tx_status.json"
    tsc = {int(k): v for k, v in json.loads(tsf.read_text()).items()} if tsf.exists() else {}
    txst = json.loads(stf.read_text()) if stf.exists() else {}
    for i, n in enumerate(out_n):
        if n["block"] not in tsc:
            tsc[n["block"]] = rpc.block_ts(n["block"])
        if n["tx"] not in txst:
            txst[n["tx"]] = rpc.receipt(n["tx"])["status"]
        if i % 200 == 199:
            tsf.write_text(json.dumps(tsc))
            stf.write_text(json.dumps(txst))
    tsf.write_text(json.dumps(tsc))
    stf.write_text(json.dumps(txst))
    for n in out_n:
        n["ts"] = tsc[n["block"]]
        if txst[n["tx"]] == "0x0":
            n["class"] = "reverted: transaction failed, nothing moved"

    # rows
    prices = Prices(cdir, ts_b0, ts_b1)
    rows, excluded = [], collections.Counter()

    def cid_of(tok):
        return "coingecko:ethereum" if tok in (WETH, "native") else f"ethereum:{tok}"

    def add(ts, kind, tok, raw, to):
        if to in fail_to:
            excluded["to failure recipient"] += 1
            return
        if to == gw:
            excluded["to gateway itself"] += 1
            return
        if tok == "native":
            sym, dec, isnft = "ETH", 18, False
        else:
            sym, dec = meta[tok]
            isnft = nft[tok]
        if isnft:
            rows.append({"ts": ts, "ts_utc": iso(ts), "leg": cfg["leg"], "asset": f"{sym} (ERC-721)",
                         "amount": 1, "usd": None, "kind": kind, "priced": "no", "src": "", "nft": True})
            return
        amt = raw / 10 ** dec
        asset = "ETH" if tok in (WETH, "native") else sym
        p, src = prices.price(cid_of(tok), ts)
        rows.append({"ts": ts, "ts_utc": iso(ts), "leg": cfg["leg"], "asset": asset, "amount": amt,
                     "usd": amt * p if p is not None else None, "kind": kind,
                     "priced": "yes" if p is not None else "no", "src": src, "nft": False})

    for e in sorted(events, key=lambda e: (e["ts"], e["logIndex"])):
        add(e["ts"], "event", e["token"], e["raw"], e["to"])
    for u in unmatched_x:
        if u["class"] == "outside party":
            add(u["ts"], "erc20", u["token"], u["raw"], u["to"])
    for u in unmatched_n:
        if u["class"] == "outside party":
            add(u["ts"], "native", "native", u["raw"], u["to"])
    rows.sort(key=lambda r: r["ts"])

    out = HERE / f"{eid}.csv"
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["ts_utc", "leg", "asset", "amount", "usd", "kind", "priced"])
        for r in rows:
            w.writerow([r["ts_utc"], r["leg"], r["asset"], repr(r["amount"]) if isinstance(r["amount"], float)
                        else r["amount"], "" if r["usd"] is None else f"{r['usd']:.2f}", r["kind"], r["priced"]])

    # summary
    fung = [r for r in rows if not r["nft"]]
    pr = [r for r in fung if r["usd"] is not None]
    by_asset = collections.defaultdict(lambda: [0, 0.0, 0.0, 0])
    for r in rows:
        a = by_asset[r["asset"]]
        a[0] += 1
        a[1] += r["amount"]
        a[2] += r["usd"] or 0.0
        a[3] += r["priced"] == "yes"
    src = collections.Counter(r["src"] for r in pr)
    hour = collections.defaultdict(float)
    day = collections.defaultdict(float)
    hour_n = collections.Counter()
    for r in pr:
        hour[r["ts"] // 3600 * 3600] += r["usd"]
        day[r["ts"] // 86400 * 86400] += r["usd"]
        hour_n[r["ts"] // 3600 * 3600] += 1
    nd = (ts_b1 - ts_b0) / 86400
    days_all = [ts_b0 // 86400 * 86400 + 86400 * i for i in range(int(nd) + 2)]
    day_vals = [day.get(d, 0.0) for d in days_all if ts_b0 // 86400 * 86400 <= d <= ts_b1]
    gaps = []
    ts_sorted = sorted(r["ts"] for r in rows)
    for a, b in zip([ts_b0] + ts_sorted, ts_sorted + [ts_b1]):
        if b - a > 6 * 3600:
            gaps.append([iso(a), iso(b), round((b - a) / 3600, 1)])
    big = max(pr, key=lambda r: r["usd"]) if pr else None
    import numpy as np
    usd_arr = np.array([r["usd"] for r in pr]) if pr else np.array([0.0])
    s = {
        "id": eid, "blocks": [b0, b1], "window_utc": [iso(ts_b0), iso(ts_b1)], "window_days": round(nd, 3),
        "t_fail_utc": iso(t_fail),
        "gateway_log_topics": dict(topic_counts),
        "n_release_events": len(events), "n_erc20_transfers_out": len(xfers), "n_native_traces_out": len(traces),
        "weth_events": len(weth_ev_tx), "weth_events_with_native_send": weth_native,
        "unmatched_erc20": collections.Counter(u["class"] for u in unmatched_x),
        "unmatched_native": collections.Counter(u["class"] for u in unmatched_n),
        "unmatched_outside_detail": [{"ts_utc": iso(u["ts"]), "kind": "erc20" if "token" in u else "native",
                                      "asset": (meta[u["token"]][0] if "token" in u else "ETH"),
                                      "amount": u["raw"] / 10 ** (meta[u["token"]][1] if "token" in u else 18)}
                                     for u in unmatched_x + unmatched_n if u["class"] == "outside party"][:50],
        "excluded": dict(excluded),
        "n_rows": len(rows), "n_nft_rows": len(rows) - len(fung), "n_fungible": len(fung), "n_priced": len(pr),
        "usd_total": float(sum(r["usd"] for r in pr)),
        "share_priced_count_fungible": len(pr) / len(fung) if fung else None,
        "price_sources": dict(src),
        "by_asset": {k: {"n": v[0], "amount": v[1], "usd": v[2], "n_priced": v[3]}
                     for k, v in sorted(by_asset.items(), key=lambda kv: -kv[1][2])},
        "largest": {"ts_utc": big["ts_utc"], "asset": big["asset"], "amount": big["amount"], "usd": big["usd"]}
        if big else None,
        "usd_quantiles": {q: float(np.quantile(usd_arr, q)) for q in (0.5, 0.9, 0.99, 0.999)},
        "busiest_hour": (lambda h: {"hour_utc": iso(h), "usd": hour[h], "n": hour_n[h]})(max(hour, key=hour.get))
        if hour else None,
        "busiest_day": (lambda d: {"day_utc": iso(d)[:10], "usd": day[d]})(max(day, key=day.get)) if day else None,
        "daily_usd_quantiles": {q: float(np.quantile(day_vals, q)) for q in (0.5, 0.9, 0.99, 1.0)},
        "daily_usd_mean": float(np.mean(day_vals)),
        "gaps_over_6h": gaps,
        "locked": len(locked), "unlocked": len(unlocked),
        "locked_detail": [{"lock_utc": iso(x["ts"]), "asset": meta.get(x["token"], ("?", 18))[0],
                           "amount": x["raw"] / 10 ** meta.get(x["token"], ("?", 18))[1],
                           "unlock_utc": next((iso(u["ts"]) for u in unlocked if u["id"] == x["id"]), None)}
                          for x in locked],
    }
    (cdir / "summary.json").write_text(json.dumps(s, indent=1, default=str))
    print(json.dumps({k: s[k] for k in ("n_release_events", "n_rows", "n_priced", "usd_total",
                                        "share_priced_count_fungible", "excluded", "unmatched_erc20",
                                        "unmatched_native", "largest", "busiest_hour", "busiest_day",
                                        "locked", "unlocked")}, indent=1, default=str))


if __name__ == "__main__":
    main(sys.argv[1])
