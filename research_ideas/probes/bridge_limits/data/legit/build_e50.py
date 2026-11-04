"""E50 (Syscoin UTXO-NEVM bridge, NEVM vault): legitimate releases over the 150 days before the failure (2026-10-16).

Inputs  results/incidents.csv                failure time (first_release_utc)
        raw/E50/targets.json                 vault, relay and failure addresses (raw cache; taken from
                                             data/incidents/research/batch_L.json and checked on chain)
        raw/E50/src_vault.json               verified vault source (explorer.syscoin.org Blockscout API)
Outputs E50.csv                              ts_utc, leg, asset, amount, usd, kind, priced (no addresses, no hashes)
        raw/E50/                             RPC and explorer caches, prices, summary.json

Method
- Window [t_fail - 150 d, t_fail - 1 s]; t_fail = block time of the first unauthorized release (NEVM block 934,686).
- Release record. The vault (SyscoinVaultManager, verified source) releases only in processTransaction, which
  only the relay contract may call after checking an SPV proof of a burn on the UTXO chain. It pays native SYS
  with a plain call (_withdrawSYS), ERC-20/721/1155 with token transfers, and emits
  TokenUnfreeze(uint64 indexed assetGuid, address indexed recipient, uint value) after the payment. The
  contract has no other outflow path (no owner withdrawal, no receive or fallback function). One event is
  one row (kind `event`); `value` is in 8-decimal units (satoshis), so a native release pays value * 1e10 wei.
- Checks. (a) Native SYS: every TokenUnfreeze for the SYS asset GUID is matched to a successful internal
  call from the vault in the same transaction with value = event value * 1e10 wei (explorer internal
  transactions), and every successful value-bearing internal call from the vault is matched to an event.
  (b) Vault balance at the window ends equals the start balance plus native locks (values of the vault
  transactions that emitted TokenFreeze for SYS) minus native releases.
- Prices: DefiLlama /chart for coingecko:syscoin, hourly (nearest point within 2 h), else daily (36 h).
Run: python -I data/legit/build_e50.py collect|build
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

from Crypto.Hash import keccak

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent.parent
EID = "E50"
RAW = HERE / "raw" / EID
T = json.loads((HERE / "targets" / f"{EID}.json").read_text())
URL, API = T["rpc"], T["explorer_api"]
VAULT, RELAY = T["vault"].lower(), T["relay"].lower()
LEG = "NEVM vault (Syscoin NEVM)"
UNFREEZE = "0xb27598a6740f5e57c905fdf107266796e030a0739a6e06cee3b5b74c69d0545e"
FREEZE = "0x0b8914e27c9a6c88836bc5547f82ccf331142c761f84e9f1d36934a6a31eefad"
REGISTRY = "0x8b803ac4bafd549786ec90c18b77168e378826e9d960830a680c85ba0247d430"
WINDOW_S = 150 * 86400
UA = {"User-Agent": "bridge-limits-probe/1.0"}


def sel(sig):
    h = keccak.new(digest_bits=256)
    h.update(sig.encode())
    return "0x" + h.hexdigest()[:8]


def iso(ts):
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def to_ts(s):
    return int(datetime.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp())


def failure_time():
    with open(ROOT / "results" / "incidents.csv", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["id"] == EID:
                return to_ts(r["first_release_utc"])
    raise KeyError(EID)


def http_json(url, data=None, tries=8):
    last = None
    for k in range(tries):
        try:
            hdr = dict(UA)
            if data is not None:
                hdr["Content-Type"] = "application/json"
            with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=hdr), timeout=120) as r:
                return json.loads(r.read().decode())
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(3 * (k + 1))
    raise RuntimeError(f"{url}: {last}")


def rpc(method, params):
    j = http_json(URL, json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode())
    if "error" in j:
        raise RuntimeError(f"{method}: {j['error']}")
    return j["result"]


def cached(path, fn):
    if path.exists():
        return json.loads(path.read_text())
    v = fn()
    path.write_text(json.dumps(v))
    return v


def block_ts(b):
    return int(rpc("eth_getBlockByNumber", [hex(b), False])["timestamp"], 16)


def block_at(ts, lo, hi):
    while lo < hi:
        mid = (lo + hi) // 2
        if block_ts(mid) < ts:
            lo = mid + 1
        else:
            hi = mid
    return lo


def window():
    def fn():
        t_fail = failure_time()
        fb = T["failure_block"]
        assert block_ts(fb) == t_fail, "failure block time differs from incidents.csv"
        t_start = t_fail - WINDOW_S
        b0 = block_at(t_start, 1, fb)
        bf = block_at(t_fail, b0, fb)
        w = {"t_fail": t_fail, "t_start": t_start, "t_end": t_fail - 1, "b0": b0, "b1": bf - 1,
             "ts_b0m1": block_ts(b0 - 1), "ts_b0": block_ts(b0), "ts_b1": block_ts(bf - 1), "ts_bf": block_ts(bf)}
        assert w["ts_b0m1"] < t_start <= w["ts_b0"] and w["ts_b1"] < t_fail <= w["ts_bf"], w
        return w
    return cached(RAW / "window.json", fn)


def collect():
    w = window()
    print(w, flush=True)
    b0, b1 = w["b0"], w["b1"]
    # vault logs in the window, in 20,000-block steps
    logs = []
    for s in range(b0, b1 + 1, 20000):
        e = min(s + 19999, b1)
        logs += cached(RAW / f"vault_logs_{s}_{e}.json",
                       lambda s=s, e=e: rpc("eth_getLogs", [{"address": VAULT, "fromBlock": hex(s), "toBlock": hex(e)}]))
    print("vault logs", len(logs), collections.Counter(lg["topics"][0] for lg in logs), flush=True)
    # contract state read at the window end
    def state():
        out = {"SYSAssetGuid": int(rpc("eth_call", [{"to": VAULT, "data": sel("SYSAssetGuid()")}, hex(b1)]), 16),
               "paused": int(rpc("eth_call", [{"to": VAULT, "data": sel("paused()")}, hex(b1)]), 16),
               "trustedRelayerContract": "0x" + rpc("eth_call", [{"to": VAULT, "data": sel("trustedRelayerContract()")}, hex(b1)])[-40:],
               "globalAssetIdCount": int(rpc("eth_call", [{"to": VAULT, "data": sel("globalAssetIdCount()")}, hex(b1)]), 16)}
        reg = {}
        for aid in range(1, out["globalAssetIdCount"] + 1):
            r = rpc("eth_call", [{"to": VAULT, "data": sel("assetRegistry(uint32)") + format(aid, "064x")}, hex(b1)])
            d = r[2:]
            ws = [d[i:i + 64] for i in range(0, len(d), 64)]
            reg[aid] = {"assetType": int(ws[0], 16), "assetContract": "0x" + ws[1][-40:], "precision": int(ws[2], 16),
                        "tokenIdCount": int(ws[3], 16)}
        out["registry"] = reg
        return out
    st = cached(RAW / "vault_state.json", state)
    print(st, flush=True)
    # block timestamps for every vault log in the window
    def stamps():
        return {str(b): block_ts(b) for b in sorted({int(lg["blockNumber"], 16) for lg in logs})}
    cached(RAW / "block_ts.json", stamps)
    # balances at the window ends
    cached(RAW / "balances.json", lambda: {str(b): int(rpc("eth_getBalance", [VAULT, hex(b)]), 16) for b in (b0 - 1, b1)})
    # values of the vault transactions behind TokenFreeze logs (native locks carry msg.value)
    def txvals():
        out = {}
        for lg in logs:
            if lg["topics"][0] == FREEZE and lg["transactionHash"] not in out:
                tx = rpc("eth_getTransactionByHash", [lg["transactionHash"]])
                rc = rpc("eth_getTransactionReceipt", [lg["transactionHash"]])
                out[lg["transactionHash"]] = {"to": tx["to"], "value": int(tx["value"], 16), "status": rc["status"]}
        return out
    cached(RAW / "freeze_tx_values.json", txvals)
    # explorer internal transactions of the vault, newest first, until the window start is passed
    pages = RAW / "itx"
    pages.mkdir(exist_ok=True)
    params, k = None, 0
    while True:
        p = pages / f"page_{k:04d}.json"
        if p.exists():
            j = json.loads(p.read_text())
        else:
            q = "" if params is None else "?" + "&".join(f"{a}={b}" for a, b in params.items())
            j = http_json(f"{API}/addresses/{T['vault']}/internal-transactions{q}")
            p.write_text(json.dumps(j))
            time.sleep(0.5)
        items = j.get("items") or []
        params = j.get("next_page_params")
        k += 1
        if not items or params is None or min(it["block_number"] for it in items) < b0:
            break
    print("internal-transaction pages", k, flush=True)


class Prices:
    def __init__(self, t0, t1):
        self.t0, self.t1 = t0, t1
        self.dir = RAW / "px"
        self.dir.mkdir(exist_ok=True)
        self.series = {}

    def _cached(self, name, url):
        p = self.dir / name
        if p.exists():
            return json.loads(p.read_text())
        j = http_json(url)
        p.write_text(json.dumps(j))
        time.sleep(0.3)
        return j

    def load(self, cid):
        if cid in self.series:
            return self.series[cid]
        safe = cid.replace(":", "_")
        hourly = []
        t = self.t0 - 3 * 3600
        while t < self.t1 + 3600:
            j = self._cached(f"1h_{safe}_{t}.json", f"https://coins.llama.fi/chart/{cid}?start={t}&span=500&period=1h")
            pts = [(q["timestamp"], q["price"]) for q in (j.get("coins", {}).get(cid, {}).get("prices") or [])]
            if len(pts) < 450:
                j2 = self._cached(f"1h_{safe}_{t}_sw1800.json",
                                  f"https://coins.llama.fi/chart/{cid}?start={t}&span=500&period=1h&searchWidth=1800")
                pts += [(q["timestamp"], q["price"]) for q in (j2.get("coins", {}).get(cid, {}).get("prices") or [])]
            hourly += pts
            t += 500 * 3600
        j = self._cached(f"1d_{safe}_{self.t0}.json",
                         f"https://coins.llama.fi/chart/{cid}?start={self.t0 - 2 * 86400}&span=160&period=1d")
        daily = [(q["timestamp"], q["price"]) for q in (j.get("coins", {}).get(cid, {}).get("prices") or [])]
        self.series[cid] = (sorted(set(hourly)), sorted(set(daily)))
        return self.series[cid]

    @staticmethod
    def near(series, ts, tol):
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
        return None if best is None else best[1]

    def price(self, cid, ts):
        h, d = self.load(cid)
        p = self.near(h, ts, 2 * 3600)
        if p is not None:
            return p, "defillama chart 1h"
        p = self.near(d, ts, 36 * 3600)
        if p is not None:
            return p, "defillama chart 1d"
        return None, ""


def build():
    import numpy as np
    w = json.loads((RAW / "window.json").read_text())
    st = json.loads((RAW / "vault_state.json").read_text())
    tsc = {int(k): v for k, v in json.loads((RAW / "block_ts.json").read_text()).items()}
    logs = []
    for p in sorted(RAW.glob("vault_logs_*.json"), key=lambda p: int(p.name.split("_")[2])):
        logs += json.loads(p.read_text())
    sys_guid = st["SYSAssetGuid"]
    unf, frz, reg = [], [], []
    for lg in logs:
        t0 = lg["topics"][0]
        blk = int(lg["blockNumber"], 16)
        if t0 == UNFREEZE:
            unf.append({"block": blk, "ts": tsc[blk], "tx": lg["transactionHash"], "logIndex": int(lg["logIndex"], 16),
                        "guid": int(lg["topics"][1], 16), "to": "0x" + lg["topics"][2][-40:], "value": int(lg["data"], 16)})
        elif t0 == FREEZE:
            frz.append({"block": blk, "ts": tsc[blk], "tx": lg["transactionHash"], "guid": int(lg["topics"][1], 16),
                        "from": "0x" + lg["topics"][2][-40:], "sat": int(lg["data"][2:66], 16)})
        elif t0 == REGISTRY:
            reg.append({"block": blk, "ts": tsc[blk], "assetId": int(lg["topics"][1], 16)})
    # internal transactions (explorer)
    itx = []
    for p in sorted((RAW / "itx").glob("page_*.json")):
        itx += json.loads(p.read_text()).get("items") or []
    itx = [x for x in itx if w["b0"] <= x["block_number"] <= w["b1"]]
    itx_out = [x for x in itx if (x["from"] or {}).get("hash", "").lower() == VAULT and int(x["value"]) > 0]
    itx_out_ok = [x for x in itx_out if x.get("success")]
    by_tx = collections.defaultdict(list)
    for x in itx_out_ok:
        by_tx[x["transaction_hash"].lower()].append(x)
    used = set()
    nat_unmatched = []
    for e in unf:
        if e["guid"] != sys_guid:
            continue
        cand = [x for x in by_tx.get(e["tx"].lower(), []) if id(x) not in used and int(x["value"]) == e["value"] * 10 ** 10
                and (x["to"] or {}).get("hash", "").lower() == e["to"].lower()]
        if cand:
            used.add(id(cand[0]))
        else:
            nat_unmatched.append(e)
    itx_unmatched = [x for x in itx_out_ok if id(x) not in used]

    # balance reconciliation over [b0, b1]
    bal = json.loads((RAW / "balances.json").read_text())
    fv = json.loads((RAW / "freeze_tx_values.json").read_text())
    locks_wei = sum(v["value"] for h, v in fv.items() if v["status"] == "0x1"
                    and any(f["tx"] == h and f["guid"] == sys_guid for f in frz))
    other_vault_tx_value = sum(v["value"] for h, v in fv.items() if v["status"] == "0x1"
                               and not any(f["tx"] == h and f["guid"] == sys_guid for f in frz))
    rel_wei = sum(e["value"] * 10 ** 10 for e in unf if e["guid"] == sys_guid)
    b_start, b_end = bal[str(w["b0"] - 1)], bal[str(w["b1"])]
    rec = {"start_sys": b_start / 1e18, "end_sys": b_end / 1e18, "locks_sys": locks_wei / 1e18,
           "releases_sys": rel_wei / 1e18, "other_lock_tx_value_sys": other_vault_tx_value / 1e18,
           "residual_sys": (b_start + locks_wei - rel_wei - b_end) / 1e18}

    fail_to = {T.get("failure_recipient", "").lower()}
    prices = Prices(w["ts_b0"], w["ts_b1"])
    rows, excluded = [], collections.Counter()
    for e in sorted(unf, key=lambda e: (e["block"], e["logIndex"])):
        if e["to"].lower() in fail_to:
            excluded["release to the failure's initiating address"] += 1
            continue
        if e["to"].lower() in (VAULT, RELAY):
            excluded["to the bridge's own contracts"] += 1
            continue
        if e["guid"] == sys_guid:
            amt, asset, cid = e["value"] / 1e8, "SYS", "coingecko:syscoin"
        else:
            aid = e["guid"] & 0xFFFFFFFF
            item = st["registry"].get(str(aid), {})
            asset = f"asset {aid} (type {item.get('assetType')})"
            amt = e["value"] / 1e8 if item.get("assetType") == 2 else e["value"]
            cid = f"syscoin:{item.get('assetContract')}" if item.get("assetType") == 2 else None
        p, src = prices.price(cid, e["ts"]) if cid else (None, "")
        rows.append({"ts": e["ts"], "ts_utc": iso(e["ts"]), "leg": LEG, "asset": asset, "amount": amt,
                     "usd": None if p is None else amt * p, "kind": "event", "priced": "yes" if p is not None else "no",
                     "src": src, "to": e["to"].lower()})
    rows.sort(key=lambda r: r["ts"])
    for r in rows:
        assert w["t_start"] <= r["ts"] <= w["t_end"]
    with open(HERE / f"{EID}.csv", "w", newline="", encoding="utf-8") as f:
        wr = csv.writer(f)
        wr.writerow(["ts_utc", "leg", "asset", "amount", "usd", "kind", "priced"])
        for r in rows:
            wr.writerow([r["ts_utc"], r["leg"], r["asset"], repr(r["amount"]), "" if r["usd"] is None else f"{r['usd']:.2f}",
                         r["kind"], r["priced"]])

    pr = [r for r in rows if r["usd"] is not None]
    hour, day = collections.defaultdict(float), collections.defaultdict(float)
    hour_n, day_n = collections.Counter(), collections.Counter()
    for r in rows:
        hour_n[r["ts"] // 3600 * 3600] += 1
        day_n[r["ts"] // 86400 * 86400] += 1
        if r["usd"] is not None:
            hour[r["ts"] // 3600 * 3600] += r["usd"]
            day[r["ts"] // 86400 * 86400] += r["usd"]
    days_all = list(range(w["t_start"] // 86400 * 86400, w["t_end"] // 86400 * 86400 + 1, 86400))
    day_vals = [day.get(d, 0.0) for d in days_all]
    ts_sorted = sorted(r["ts"] for r in rows)
    gaps = []
    for a, b in zip([w["t_start"]] + ts_sorted, ts_sorted + [w["t_end"]]):
        if b - a > 2 * 86400:
            gaps.append([iso(a), iso(b), round((b - a) / 86400, 1)])
    recip = collections.Counter()
    recip_n = collections.Counter()
    for r in rows:
        recip[r["to"]] += r["amount"] if r["asset"] == "SYS" else 0.0
        recip_n[r["to"]] += 1
    usd_arr = np.array([r["usd"] for r in pr]) if pr else np.array([0.0])
    amt_arr = np.array([r["amount"] for r in rows if r["asset"] == "SYS"]) if rows else np.array([0.0])
    big = sorted(pr, key=lambda r: -r["usd"])[:5]
    s = {
        "id": EID, "window_utc": [iso(w["t_start"]), iso(w["t_end"])], "blocks": [w["b0"], w["b1"]],
        "block_times": [iso(w["ts_b0"]), iso(w["ts_b1"])], "vault_state_at_b1": {k: v for k, v in st.items() if k != "trustedRelayerContract"},
        "relay_matches_target": st["trustedRelayerContract"].lower() == RELAY,
        "vault_log_topics": dict(collections.Counter(lg["topics"][0] for lg in logs)),
        "n_unfreeze": len(unf), "n_unfreeze_by_guid": dict(collections.Counter(e["guid"] for e in unf)),
        "n_freeze": len(frz), "n_freeze_by_guid": dict(collections.Counter(f["guid"] for f in frz)),
        "freeze_sys_total": sum(f["sat"] for f in frz if f["guid"] == sys_guid) / 1e8,
        "n_registry": len(reg),
        "itx_in_window": len(itx), "itx_out_value": len(itx_out), "itx_out_value_ok": len(itx_out_ok),
        "native_events_unmatched": len(nat_unmatched), "itx_out_unmatched": len(itx_unmatched),
        "balance_check": rec, "excluded": dict(excluded),
        "n_rows": len(rows), "n_priced": len(pr), "share_priced": len(pr) / len(rows) if rows else None,
        "usd_total": float(sum(r["usd"] for r in pr)), "sys_total": float(sum(r["amount"] for r in rows if r["asset"] == "SYS")),
        "price_sources": dict(collections.Counter(r["src"] for r in pr)),
        "first_release": iso(ts_sorted[0]) if ts_sorted else None, "last_release": iso(ts_sorted[-1]) if ts_sorted else None,
        "days_with_release": len({r["ts"] // 86400 for r in rows}), "n_days_window": len(days_all),
        "largest": [{"ts_utc": r["ts_utc"], "asset": r["asset"], "amount": r["amount"], "usd": r["usd"]} for r in big],
        "usd_quantiles": {q: float(np.quantile(usd_arr, q)) for q in (0.5, 0.9, 0.99)},
        "sys_quantiles": {q: float(np.quantile(amt_arr, q)) for q in (0.5, 0.9, 0.99)},
        "busiest_hour_usd": (lambda h: {"hour_utc": iso(h), "usd": hour[h], "n": hour_n[h]})(max(hour, key=hour.get)) if hour else None,
        "busiest_hour_count": (lambda h: {"hour_utc": iso(h), "n": hour_n[h], "usd": hour.get(h, 0.0)})(max(hour_n, key=hour_n.get)) if hour_n else None,
        "busiest_day_usd": (lambda d: {"day_utc": iso(d)[:10], "usd": day[d], "n": day_n[d]})(max(day, key=day.get)) if day else None,
        "busiest_day_count": (lambda d: {"day_utc": iso(d)[:10], "n": day_n[d], "usd": day.get(d, 0.0)})(max(day_n, key=day_n.get)) if day_n else None,
        "daily_usd_quantiles": {q: float(np.quantile(day_vals, q)) for q in (0.5, 0.9, 0.99, 1.0)},
        "daily_usd_mean_150d": float(sum(r["usd"] for r in pr) / 150.0),
        "gaps_over_2d": gaps,
        "n_recipients": len(recip_n),
        "top_recipient_sys_shares": [round(v / max(1e-9, sum(recip.values())), 4) for _, v in recip.most_common(5)],
        "top_recipient_counts": [n for _, n in recip_n.most_common(5)],
    }
    (RAW / "summary.json").write_text(json.dumps(s, indent=1, default=str))
    (RAW / "recipients.json").write_text(json.dumps({"by_sys": recip.most_common(20), "by_count": recip_n.most_common(20)}, indent=1))
    print(json.dumps(s, indent=1, default=str))


if __name__ == "__main__":
    {"collect": collect, "build": build}[sys.argv[1]]()
