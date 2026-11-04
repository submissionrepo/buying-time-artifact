"""Legitimate release history before a failure, for fitting a limit to a bridge's own traffic (2026-10-16).

Failures: E22 (three Ethereum custody legs of one operator's bridges) and E24 (Ethereum custody contract).
Window: the 150 days that end one second before the failure's first unauthorized release
(results/incidents.csv first_release_utc). Release points: `custody` of the onchain_targets.json legs.

Step 1 (collect, cached under raw/<ID>/; addresses and hashes stay there):
  - ERC-20: Transfer logs with topic1 = custody (eth_getLogs, all token contracts).
  - Native: trace_filter with fromAddress = custody (calls with value > 0, no error).
  - The trace set also gives every transaction in which the custody made a call; ERC-20 logs in
    other transactions are flagged (third-party transferFrom or unsolicited token events).
Step 2 (price): DefiLlama /batchHistorical at each release time (searchWidth 10 min, then 2 h for misses).
Step 3 (write): <ID>.csv (ts_utc, leg, asset, amount, usd, kind, priced) and aggregate checks.
Run: python -I data/legit/collect_legit_E22_E24.py collect|price|write [E22 E24]
"""
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

TARGETS = json.loads((ROOT / "data" / "incidents" / "onchain_targets.json").read_text())
ONCHAIN = ROOT / "data" / "incidents" / "onchain"
WINDOW_DAYS = 150

FAILURES = {
    "E22": {"first_release_utc": "2023-07-06T18:10:35Z",
            "legs": {"fantom": "E22_eth_ftm", "moonriver": "E22_eth_movr", "dogechain": "E22_eth_doge"},
            "failure_caches": ["E22_eth_ftm", "E22_eth_movr", "E22_eth_doge", "E22_eth_ftm_tests"]},
    "E24": {"first_release_utc": "2023-11-22T09:59:35Z",
            "legs": {"custody": "E24_eth"},
            "failure_caches": ["E24_eth"]},
}


def to_ts(s):
    return int(datetime.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp())


def iso(ts):
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def raw_dir(fid):
    d = HERE / "raw" / fid
    d.mkdir(parents=True, exist_ok=True)
    return d


def batch_headers(blocks, url="https://rpc.mevblocker.io"):
    out = {}
    blocks = sorted(set(blocks))
    for i in range(0, len(blocks), 50):
        chunk = blocks[i:i + 50]
        body = json.dumps([{"jsonrpc": "2.0", "id": b, "method": "eth_getBlockByNumber",
                            "params": [hex(b), False]} for b in chunk]).encode()
        for attempt in range(6):
            try:
                req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json",
                                                                      "User-Agent": "bridge-limits-probe/1.0"})
                with urllib.request.urlopen(req, timeout=60) as r:
                    j = json.loads(r.read().decode())
                for x in j:
                    out[x["id"]] = int(x["result"]["timestamp"], 16)
                break
            except Exception as e:  # noqa: BLE001
                time.sleep(1 + attempt)
                if attempt == 5:
                    raise RuntimeError(f"header batch failed: {e}")
    return out


def collect(fid):
    f = FAILURES[fid]
    rd = raw_dir(fid)
    rpc = Rpc("ethereum")
    rt = Rpc("ethereum_trace")
    t_end = to_ts(f["first_release_utc"]) - 1
    t_start = t_end + 1 - WINDOW_DAYS * 86400
    b0 = rpc.block_at(t_start)
    b_fail = rpc.block_at(t_end + 1)
    b1 = b_fail - 1
    meta = {"fid": fid, "t_start": t_start, "t_end": t_end, "b0": b0, "b1": b1,
            "b0_ts": rpc.block_ts(b0), "b1_ts": rpc.block_ts(b1), "legs": {}}
    tokmeta = {}
    for leg, tid in f["legs"].items():
        custody = [a.lower() for a in TARGETS[tid]["custody"]]
        logs_f = rd / f"{leg}_logs.json"
        if not logs_f.exists():
            logs = []
            for c in custody:
                print(fid, leg, "logs", flush=True)
                for lg in rpc.logs(None, [TRANSFER, topic_addr(c)], b0, b1, step=5000):
                    logs.append({k: lg.get(k) for k in ("address", "topics", "data", "blockNumber",
                                                         "blockTimestamp", "transactionHash", "logIndex")})
            logs_f.write_text(json.dumps(logs))
        tr_f = rd / f"{leg}_traces.json"
        if not tr_f.exists():
            print(fid, leg, "traces", flush=True)
            trs = []
            for x in rt.trace_filter(custody, b0, b1, step=20000):
                a = x.get("action", {})
                trs.append({"block": x.get("blockNumber"), "tx": x.get("transactionHash"), "type": x.get("type"),
                            "callType": a.get("callType"), "from": (a.get("from") or "").lower(),
                            "to": (a.get("to") or "").lower(), "value": a.get("value", "0x0"),
                            "sel": (a.get("input") or "")[:10], "error": x.get("error"),
                            "traceAddress": x.get("traceAddress")})
            tr_f.write_text(json.dumps(trs))
        logs = json.loads(logs_f.read_text())
        for lg in logs:
            erc20_meta(rpc, lg["address"].lower(), tokmeta)
        meta["legs"][leg] = {"target": tid, "custody": custody}
    # timestamps for native rows
    blocks = []
    for leg in f["legs"]:
        for x in json.loads((rd / f"{leg}_traces.json").read_text()):
            if int(x["value"] or "0x0", 16) > 0:
                blocks.append(x["block"])
    tsf = rd / "block_ts.json"
    have = {int(k): v for k, v in json.loads(tsf.read_text()).items()} if tsf.exists() else {}
    need = [b for b in set(blocks) if b not in have]
    have.update(batch_headers(need))
    tsf.write_text(json.dumps(have))
    meta["tokmeta"] = tokmeta
    (rd / "meta.json").write_text(json.dumps(meta, indent=1))
    print(fid, "collected", b0, b1, flush=True)


def failure_recipients(fid):
    out = set()
    for tid in FAILURES[fid]["failure_caches"]:
        p = ONCHAIN / f"{tid}.json"
        if p.exists():
            d = json.loads(p.read_text())
            out |= {r["to"] for r in d["rows"] if r.get("selected")}
        out |= {a.lower() for a in TARGETS.get(tid, {}).get("recipients", [])}
    return out


def build_rows(fid):
    """All candidate release rows with exclusion flags (raw, with addresses; kept in raw/)."""
    rd = raw_dir(fid)
    meta = json.loads((rd / "meta.json").read_text())
    tokmeta = meta["tokmeta"]
    bts = {int(k): v for k, v in json.loads((rd / "block_ts.json").read_text()).items()}
    all_custody = {c for L in meta["legs"].values() for c in L["custody"]}
    fail_to = failure_recipients(fid)
    rows = []
    for leg, L in meta["legs"].items():
        custody = set(L["custody"])
        trs = json.loads((rd / f"{leg}_traces.json").read_text())
        sent_tx = {x["tx"] for x in trs if x["from"] in custody and not x.get("error")}
        err_tx = {x["tx"] for x in trs if x["from"] in custody and x.get("error")
                  and x.get("traceAddress") == []}
        for lg in json.loads((rd / f"{leg}_logs.json").read_text()):
            if len(lg["topics"]) != 3:
                continue
            tok = lg["address"].lower()
            sym, dec = tokmeta.get(tok, ("?", 18))
            raw = int(lg["data"], 16) if lg["data"] not in ("0x", "", None) else 0
            if raw == 0:
                continue
            rows.append({"leg": leg, "kind": "erc20", "token": tok, "symbol": sym, "amount": raw / 10 ** dec,
                         "from": addr_from_topic(lg["topics"][1]).lower(),
                         "to": addr_from_topic(lg["topics"][2]).lower(), "block": int(lg["blockNumber"], 16),
                         "ts": int(lg["blockTimestamp"], 16), "tx": lg["transactionHash"],
                         "custody_call": lg["transactionHash"] in sent_tx})
        for x in trs:
            v = int(x["value"] or "0x0", 16)
            if v == 0 or x["type"] != "call" or x["callType"] != "call" or x.get("error"):
                continue
            if x["tx"] in err_tx:
                continue
            rows.append({"leg": leg, "kind": "native", "token": "native", "symbol": "ETH", "amount": v / 1e18,
                         "from": x["from"], "to": x["to"], "block": x["block"], "ts": bts[x["block"]],
                         "tx": x["tx"], "custody_call": True})
    for r in rows:
        excl = ""
        if r["to"] in all_custody:
            excl = "internal_custody"
        elif r["to"] in fail_to:
            excl = "failure_recipient"
        elif r["ts"] > meta["t_end"] or r["ts"] < meta["t_start"]:
            excl = "outside_window"
        elif not r["custody_call"]:
            excl = "not_custody_initiated"
        r["exclude"] = excl
    return meta, rows


LLAMA = "https://coins.llama.fi"


def get_json(url):
    for attempt in range(5):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "bridge-limits-probe/1.0"})
            with urllib.request.urlopen(req, timeout=90) as r:
                return json.loads(r.read().decode())
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(2 + 2 * attempt)
    raise RuntimeError(f"{url[:120]}: {last}")


def coin_of(r, alias):
    c = "coingecko:ethereum" if r["token"] == "native" else f"ethereum:{r['token']}"
    return alias.get(c, c)


def get_alias(fid):
    alias = {}
    for tid in FAILURES[fid]["legs"].values():
        alias.update({f"ethereum:{k.lower()}": v for k, v in TARGETS[tid].get("price_alias", {}).items()})
    return alias


PASSES = [("600", 600), ("2h", 7200)]  # searchWidth label, max |price ts - release ts| accepted


def price(fid):
    """DefiLlama /batchHistorical at each release time. Pass 1: searchWidth 10 min; pass 2 (rows still
    unpriced): searchWidth 2 h. Cache raw/<ID>/llama_batch.json: {coin: {release_ts: [price_ts, price]}}."""
    import urllib.parse
    rd = raw_dir(fid)
    meta, rows = build_rows(fid)
    alias = get_alias(fid)
    pf = rd / "llama_batch.json"
    cache = json.loads(pf.read_text()) if pf.exists() else {}
    tried_f = rd / "llama_batch_tried.json"
    tried = json.loads(tried_f.read_text()) if tried_f.exists() else {}
    for label, width in PASSES:
        need = {}
        for r in rows:
            if r["exclude"]:
                continue
            c = coin_of(r, alias)
            if str(r["ts"]) in cache.get(c, {}) or f"{c}|{r['ts']}" in tried.get(label, []):
                continue
            need.setdefault(c, set()).add(r["ts"])
        jobs = []
        for c, tss in sorted(need.items()):
            tss = sorted(tss)
            for i in range(0, len(tss), 80):
                jobs.append((c, tss[i:i + 80]))
        print(fid, "pass", label, "coins", len(need), "requests", len(jobs), flush=True)
        for n, (c, tss) in enumerate(jobs):
            q = urllib.parse.quote(json.dumps({c: tss}, separators=(",", ":")))
            try:
                j = get_json(f"{LLAMA}/batchHistorical?coins={q}&searchWidth={label}")
            except RuntimeError as e:
                print("  fail", c, e, flush=True)
                continue
            pts = sorted((p["timestamp"], p["price"]) for p in (j.get("coins", {}).get(c) or {}).get("prices", []))
            got = cache.setdefault(c, {})
            for t in tss:
                best = min(pts, key=lambda p: abs(p[0] - t), default=None)
                if best is not None and abs(best[0] - t) <= width:
                    got[str(t)] = [best[0], best[1]]
            tried.setdefault(label, []).extend(f"{c}|{t}" for t in tss if str(t) not in got)
            if n % 10 == 9 or n == len(jobs) - 1:
                pf.write_text(json.dumps(cache))
                tried_f.write_text(json.dumps(tried))
            time.sleep(0.25)
    print(fid, "priced coins", sum(1 for v in cache.values() if v), flush=True)


def write(fid):
    import pandas as pd
    rd = raw_dir(fid)
    meta, rows = build_rows(fid)
    alias = get_alias(fid)
    cache = json.loads((rd / "llama_batch.json").read_text())
    for r in rows:
        c = coin_of(r, alias)
        r["coin"] = c
        hit = cache.get(c, {}).get(str(r["ts"]))
        r["price"] = hit[1] if hit else None
        r["price_lag_s"] = (hit[0] - r["ts"]) if hit else None
        r["usd"] = r["amount"] * r["price"] if r["price"] is not None else None
    (rd / "rows_all.json").write_text(json.dumps(rows))
    keep = sorted([r for r in rows if not r["exclude"]], key=lambda r: (r["ts"], r["block"]))
    df = pd.DataFrame([{"ts_utc": iso(r["ts"]), "leg": r["leg"], "asset": r["symbol"].strip(),
                        "amount": r["amount"], "usd": (round(r["usd"], 2) if r["usd"] is not None else ""),
                        "kind": r["kind"], "priced": "yes" if r["usd"] is not None else "no"} for r in keep])
    df.to_csv(HERE / f"{fid}.csv", index=False)
    print(fid, "rows written", len(df), flush=True)

EVENTS = {  # E24 custody contract; signatures resolved from topic0 through the 4byte event database
    "0x91b4005f24": "WithdrawingToken(address,address,uint256,string)",
    "0x044513e921": "WithdrawDoneToken(address,address,uint256,string)",
    "0x85c53e7e26": "WithdrawingNative(address,uint256,string)",
    "0xd8ff383321": "WithdrawDoneNative(address,uint256,string)",
}


def events(fid):
    """Bridge's own withdrawal events (two-step: Withdrawing..., then WithdrawDone...)."""
    rd = raw_dir(fid)
    meta = json.loads((rd / "meta.json").read_text())
    rpc = Rpc("ethereum")
    ef = rd / "events.json"
    if not ef.exists():
        out = []
        for c in {c for L in meta["legs"].values() for c in L["custody"]}:
            for lg in rpc.logs(c, [], meta["b0"], meta["b1"], step=5000):
                if lg["topics"] and lg["topics"][0][:12] in EVENTS:
                    out.append({k: lg.get(k) for k in ("address", "topics", "data", "blockNumber",
                                                        "blockTimestamp", "transactionHash", "logIndex")})
        ef.write_text(json.dumps(out))
    evs = json.loads(ef.read_text())
    tokmeta = meta["tokmeta"]
    dec = []
    for lg in evs:
        name = EVENTS[lg["topics"][0][:12]].split("(")[0]
        words = [lg["data"][2 + 64 * i: 2 + 64 * (i + 1)] for i in range((len(lg["data"]) - 2) // 64)]
        amt_raw = int(words[0], 16)
        if "Token" in name:
            to = addr_from_topic(lg["topics"][1]).lower()  # topic order checked against the token list
            tok = addr_from_topic(lg["topics"][2]).lower()
            sym, d = tokmeta.get(tok) or erc20_meta(rpc, tok, tokmeta)
        else:
            tok, sym, d = "native", "ETH", 18
            to = addr_from_topic(lg["topics"][1]).lower()
        n = int(words[2], 16) if len(words) > 2 else 0
        ref = bytes.fromhex("".join(words[3:]))[:n].decode(errors="ignore") if n else ""
        dec.append({"event": name, "token": tok, "symbol": sym, "amount": amt_raw / 10 ** d, "to": to,
                    "ref": ref, "block": int(lg["blockNumber"], 16), "ts": int(lg["blockTimestamp"], 16),
                    "tx": lg["transactionHash"]})
    (rd / "events_decoded.json").write_text(json.dumps(dec))
    import collections
    print(fid, collections.Counter(e["event"] for e in dec))


if __name__ == "__main__":
    if sys.argv[1] == "events":
        events(sys.argv[2])
        sys.exit()
    step = sys.argv[1]
    ids = sys.argv[2:] or list(FAILURES)
    for fid in ids:
        {"collect": collect, "price": price, "write": write}[step](fid)
