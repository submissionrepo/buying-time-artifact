"""Build the legitimate release series data/legit/<ID>.csv from the raw log cache.

usage: python -I process.py <ID>
Configuration per ID is in CFG below (roles of the custody contracts, the release event, window).
Addresses come from data/incidents/onchain_targets.json and stay in data/legit/raw/<ID>/.
"""
import datetime
import json
import pathlib
import sys
import time
import urllib.request
from collections import Counter, defaultdict

from Crypto.Hash import keccak

BL = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BL / "incidents"))
from rpc import Rpc, TRANSFER, addr_from_topic, erc20_meta  # noqa: E402

ZERO = "0x" + "0" * 40
ETH_PLACEHOLDER = "0x00" + "e" * 38


def k256(s):
    h = keccak.new(digest_bits=256)
    h.update(s.encode())
    return "0x" + h.hexdigest()


CFG = {
    "E15": {
        "target": "E15_eth", "first_release_utc": "2022-08-01T21:32:31",
        "blocks": (14322947, 15259100), "chain": "ethereum",
        "roles": ["BridgeRouter (escrow)"],
        # Receive(uint64 indexed originAndNonce, address indexed token, address indexed recipient,
        #         address liquidityProvider, uint256 amount)
        "event": "Receive(uint64,address,address,address,uint256)",
        "own_extra": ["classify.replicas"],
    },
    "E14": {
        "target": "E14_eth", "first_release_utc": "2022-06-23T11:06:46",
        "blocks": (14067979, 15012645), "chain": "ethereum",
        "roles": ["ERC20 manager (escrow)", "ETH manager (escrow)"],
        # Unlocked(address ethToken, uint256 amount, address recipient, bytes32 receiptId)
        "event": "Unlocked(address,uint256,address,bytes32)",
        "own_extra": [],
    },
}


def iso(ts):
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def to_ts(s):
    return int(datetime.datetime.fromisoformat(s).replace(tzinfo=datetime.timezone.utc).timestamp())


def words(data):
    d = data[2:]
    return [d[i:i + 64] for i in range(0, len(d), 64)]


def get_json(url, tries=5):
    last = None
    for a in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "bridge-limits-probe/1.0"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode())
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(2 * (a + 1))
    raise RuntimeError(f"{url[:80]}...: {last}")


def hourly_prices(coin, t0, t1, cache_dir):
    """DefiLlama /chart hourly series for one coin over [t0, t1]; chunks of 450 points, cached."""
    pts = []
    s = t0 - 3 * 3600
    while s < t1 + 3600:
        f = cache_dir / f"chart_1h_{coin.replace(':', '_')}_{s}.json"
        if f.exists():
            j = json.loads(f.read_text())
        else:
            try:
                j = get_json(f"https://coins.llama.fi/chart/{coin}?start={s}&span=450&period=1h&searchWidth=600")
            except Exception as e:  # noqa: BLE001
                j = {"error": str(e)[:300]}
            f.write_text(json.dumps(j))
        for v in (j.get("coins") or {}).values():
            pts += [(p["timestamp"], p["price"]) for p in v.get("prices", [])]
        s += 450 * 3600
    return sorted(set(pts))


def daily_prices(coin, t0, t1, cache_dir):
    f = cache_dir / f"chart_1d_{coin.replace(':', '_')}_{t0}.json"
    if f.exists():
        j = json.loads(f.read_text())
    else:
        span = int((t1 - t0) / 86400) + 3
        try:
            j = get_json(f"https://coins.llama.fi/chart/{coin}?start={t0 - 86400}&span={span}&period=1d&searchWidth=43200")
        except Exception as e:  # noqa: BLE001
            j = {"error": str(e)[:300]}
        f.write_text(json.dumps(j))
    pts = []
    for v in (j.get("coins") or {}).values():
        pts += [(p["timestamp"], p["price"]) for p in v.get("prices", [])]
    return sorted(set(pts))


def nearest(pts, ts, tol):
    if not pts:
        return None
    import bisect
    i = bisect.bisect_left(pts, (ts, -1e300))
    best = None
    for j in (i - 1, i):
        if 0 <= j < len(pts):
            d = abs(pts[j][0] - ts)
            if d <= tol and (best is None or d < best[0]):
                best = (d, pts[j][1])
    return best[1] if best else None


def main():
    ID = sys.argv[1]
    c = CFG[ID]
    raw = BL / "data/legit/raw" / ID
    pdir = raw / "prices"
    pdir.mkdir(parents=True, exist_ok=True)
    t = json.loads((BL / "data/incidents/onchain_targets.json").read_text())[c["target"]]
    custody = [a.lower() for a in t["custody"]]
    own = set(custody)
    for path in c["own_extra"]:
        node = t
        for k in path.split("."):
            node = node.get(k, {}) if isinstance(node, dict) else {}
        own |= set(a.lower() for a in (node or []))
    b0, b1 = c["blocks"]
    T = to_ts(c["first_release_utc"])
    lo, hi = T - 150 * 86400, T - 1
    ev_topic = k256(c["event"])
    rpc = Rpc(c["chain"])
    meta_f = raw / "token_meta.json"
    meta = {k: tuple(v) for k, v in json.loads(meta_f.read_text()).items()} if meta_f.exists() else {}

    # failure transactions (to exclude explicitly, in case any fall inside the window)
    fail_tx = set()
    fj = BL / "data/incidents/onchain" / f"{c['target']}.json"
    if fj.exists():
        fail_tx = {r["tx"] for r in json.loads(fj.read_text())["rows"] if r.get("selected")}

    stats = Counter()
    evcount = Counter()
    rows = []
    release_events = {}  # (tx, token, recipient, amount) -> count, from the contract's own release event
    topic0_seen = Counter()
    for i, cu in enumerate(custody):
        own_logs = json.loads((raw / f"custody{i}_ownlogs_{b0}_{b1}.json").read_text())
        for lg in own_logs:
            topic0_seen[(i, lg["topics"][0] if lg["topics"] else "none")] += 1
            if lg["topics"] and lg["topics"][0] == ev_topic:
                w = words(lg["data"])
                if ID == "E15":
                    token = addr_from_topic(lg["topics"][2]).lower()
                    rcpt = addr_from_topic(lg["topics"][3]).lower()
                    amt = int(w[1], 16)
                else:
                    token = ("0x" + w[0][-40:]).lower()
                    amt = int(w[1], 16)
                    rcpt = ("0x" + w[2][-40:]).lower()
                ts = int(lg["blockTimestamp"], 16)
                key = (lg["transactionHash"], token, amt)
                release_events[key] = release_events.get(key, 0) + 1
                evcount[i] += 1
                if token == ETH_PLACEHOLDER:
                    # native ETH release recorded by the manager's own event
                    if not (lo <= ts <= hi) or lg["transactionHash"] in fail_tx:
                        stats["native_event_outside_window_or_failure"] += 1
                        continue
                    rows.append({"ts": ts, "role": i, "token": "native", "amount": amt / 1e18, "kind": "event",
                                 "to": rcpt, "tx": lg["transactionHash"], "matched": True, "blk": int(lg["blockNumber"], 16)})
        transfers = json.loads((raw / f"custody{i}_transfers_{b0}_{b1}.json").read_text())
        for lg in transfers:
            if len(lg["topics"]) != 3:
                stats["skip_not_erc20"] += 1
                continue
            to = addr_from_topic(lg["topics"][2]).lower()
            ts = int(lg["blockTimestamp"], 16)
            if not (lo <= ts <= hi):
                stats["outside_window"] += 1
                continue
            if lg["transactionHash"] in fail_tx:
                stats["failure_tx"] += 1
                continue
            if to in own:
                stats["to_own_address"] += 1
                continue
            if to == ZERO:
                stats["to_zero"] += 1
                continue
            tok = lg["address"].lower()
            if tok not in meta:
                erc20_meta(rpc, tok, meta)
            sym, dec = meta[tok]
            amt_raw = int(lg["data"], 16) if lg["data"] not in ("0x", "") else 0
            if amt_raw == 0:
                stats["zero_amount"] += 1
                continue
            key = (lg["transactionHash"], tok, amt_raw)
            matched = release_events.get(key, 0) > 0
            if matched:
                release_events[key] -= 1
            rows.append({"ts": ts, "role": i, "token": tok, "amount": amt_raw / 10 ** dec, "kind": "erc20",
                         "to": to, "tx": lg["transactionHash"], "matched": matched, "blk": int(lg["blockNumber"], 16)})
    meta_f.write_text(json.dumps(meta, indent=1))
    # (matching ignores the recipient: a fast-liquidity provider may receive the tokens)
    # release events with no matching Transfer (e.g. representation mints on E15; ETH on E14 handled above)
    unmatched_events = sum(v for k, v in release_events.items() if v > 0 and k[1] != ETH_PLACEHOLDER)

    # symbols: disambiguate distinct token contracts that share a symbol
    sym_of = {}
    by_sym = defaultdict(list)
    for tok in sorted({r["token"] for r in rows if r["token"] != "native"}):
        by_sym[meta[tok][0] or "?"].append(tok)
    for s, toks in by_sym.items():
        # order by number of rows, so the main contract keeps the plain symbol
        toks.sort(key=lambda x: -sum(1 for r in rows if r["token"] == x))
        for j, tok in enumerate(toks):
            sym_of[tok] = s if j == 0 else f"{s}#{j + 1}"
    sym_of["native"] = "ETH"
    (raw / "asset_labels.json").write_text(json.dumps(sym_of, indent=1))

    # prices
    coin_of = lambda tok: "coingecko:ethereum" if tok == "native" else f"ethereum:{tok}"  # noqa: E731
    price_src = {}
    for tok in sorted({r["token"] for r in rows}):
        ts_list = [r["ts"] for r in rows if r["token"] == tok]
        coin = coin_of(tok)
        h = hourly_prices(coin, min(ts_list), max(ts_list), pdir)
        d = daily_prices(coin, lo, hi, pdir) if len(h) < 1 else None
        price_src[tok] = (h, d)
    for r in rows:
        h, d = price_src[r["token"]]
        p = nearest(h, r["ts"], 2 * 3600)
        src = "defillama_1h" if p is not None else None
        if p is None:
            if d is None:
                d = daily_prices(coin_of(r["token"]), lo, hi, pdir)
                price_src[r["token"]] = (h, d)
            p = nearest(d, r["ts"], 36 * 3600)
            src = "defillama_1d" if p is not None else None
        r["price"], r["src"] = p, src
        r["usd"] = r["amount"] * p if p is not None else None

    # write the main CSV (only rows that are releases through the bridge's release function,
    # or unmatched transfers flagged in the raw file)
    rows.sort(key=lambda r: (r["ts"], r["blk"]))
    import csv
    out = BL / "data/legit" / f"{ID}.csv"
    keep = [r for r in rows if r["matched"]]
    dropped = [r for r in rows if not r["matched"]]
    with open(out, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["ts_utc", "leg", "asset", "amount", "usd", "kind", "priced"])
        for r in keep:
            w.writerow([iso(r["ts"]), c["roles"][r["role"]], sym_of[r["token"]], f"{r['amount']:.10g}",
                        "" if r["usd"] is None else f"{r['usd']:.2f}", r["kind"],
                        "yes" if r["usd"] is not None else "no"])
    # raw-side full detail (addresses and hashes stay here)
    (raw / "rows_full.json").write_text(json.dumps(rows, indent=0))
    summ = {
        "window_utc": [iso(lo), iso(hi)], "blocks": [b0, b1], "event_topic": ev_topic,
        "event_counts_by_role": dict(evcount), "stats": dict(stats),
        "unmatched_release_events_non_native": unmatched_events,
        "n_rows_kept": len(keep), "n_transfers_without_release_event": len(dropped),
        "dropped_detail": Counter((sym_of[r["token"]], c["roles"][r["role"]]) for r in dropped).most_common(30),
        "dropped_usd": sum(r["usd"] or 0 for r in dropped),
        "topic0_by_role": {f"{k[0]}:{k[1]}": v for k, v in topic0_seen.items()},
        "price_src": Counter(r["src"] for r in keep),
    }
    (raw / "process_summary.json").write_text(json.dumps(summ, indent=1, default=str))
    print(json.dumps(summ, indent=1, default=str)[:4000])


if __name__ == "__main__":
    main()
