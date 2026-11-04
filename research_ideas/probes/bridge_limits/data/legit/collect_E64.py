"""E64 legitimate release history: peg-outs paid from the Liquid federation's Bitcoin reserve (2026-10-16).

Window: the 150 days that end one second before the failure's first unauthorized release
(results/incidents.csv first_release_utc), by Bitcoin block timestamp.

Release point: the federation's Bitcoin peg wallet. Its current main address (named in the research notes
for E64) only starts on 2026-07-27; before that the federation paid change to an earlier main address, which
is found as the address spent in the earliest transactions of the current one (and so on backwards until an
address is older than the window). Peg-in deposits sit at single-use addresses whose script has the same
11-of-15 template; the federation spends them together with main-address coins.

A transaction is federation-signed when one of its inputs is a federation address (a main address, an address
co-spent with a main address, a peg-in deposit address in the sidechain's peg records, or an address in the
audit API's current reserve list). Its outputs to main or other federation addresses are internal (change,
consolidation, timelock refresh); its other outputs are releases.

Release events: the sidechain's own peg-out records (burns of the sidechain asset carrying a Bitcoin
destination), from the mempool.space Liquid audit API (liquid.network/api/v1/liquid/pegs/list/<offset>),
which links each peg-out to the Bitcoin transaction and output that paid it. Release outputs are matched to
these records one to one by (transaction, output index).

Stages (all responses cached under raw/E64/; addresses and transaction ids stay in those caches):
  fetch   federation address histories (mempool.space Esplora), peg list pages, reserve endpoints,
          Bitcoin transactions named by peg-out records but not yet seen
  build   classify transactions and outputs, match to peg-out records -> raw/E64/rows_all.json
  price   DefiLlama BTC hourly chart (2 h tolerance), daily fallback (36 h) -> raw/E64/prices/
  write   E64.csv and raw/E64/summary.json
Run: python -I data/legit/collect_E64.py fetch|build|price|write|all
"""
import collections
import csv
import datetime
import json
import pathlib
import sys
import time
import urllib.error
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent          # data/legit
RAW = HERE / "raw" / "E64"                              # caches (not shipped)
LEGIT = HERE                                            # data/legit
ROOT = LEGIT.parent.parent                              # bridge_limits
sys.path.insert(0, str(LEGIT))
import pricing  # noqa: E402  (DefiLlama chart helper shared with the other collectors)

FID = "E64"
WINDOW_DAYS = 150
UA = {"User-Agent": "bridge-limits-probe/1.0"}
ESPLORA = ["https://mempool.space/api", "https://blockstream.info/api"]
LIQ = "https://liquid.network/api/v1/liquid"
LEG = "federation reserve (Bitcoin)"
COIN = "coingecko:bitcoin"


def to_ts(s):
    return int(datetime.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp())


def iso(ts):
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def incident_row():
    for r in csv.DictReader(open(ROOT / "results" / "incidents.csv", newline="", encoding="utf-8")):
        if r["id"] == FID:
            return r
    raise KeyError(FID)


T_FAIL = to_ts(incident_row()["first_release_utc"])
T_END = T_FAIL - 1
T_START = T_FAIL - WINDOW_DAYS * 86400


def http_json(url, tries=8):
    last = None
    for k in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=90) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            last = e
            if e.code == 404:
                raise
            time.sleep(min(60, 3 * (k + 1)) if e.code == 429 else 2 * (k + 1))
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(2 * (k + 1))
    raise RuntimeError(f"{url}: {last}")


def cached(path, url_list):
    """Return cached JSON at path, else fetch from the first URL in url_list that answers."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return json.loads(path.read_text())
    err = None
    for u in url_list:
        try:
            j = http_json(u)
            path.write_text(json.dumps(j))
            time.sleep(0.25)
            return j
        except Exception as e:  # noqa: BLE001
            err = e
    raise RuntimeError(str(err))


def release_points():
    """Addresses by role, from the research notes (kept in raw/E64/release_points.json)."""
    p = RAW / "release_points.json"
    if p.exists():
        return json.loads(p.read_text())
    res = ROOT / "data" / "incidents" / "research"
    refs = None
    for f in sorted(res.glob("batch_*.json")):
        for ev in json.loads(f.read_text(encoding="utf-8"))["events"]:
            if ev.get("event_id") == FID:
                refs = ev["onchain_refs"]
    rp = {"federation_main": [r["value"] for r in refs if r["role"].startswith("federation peg address")][0],
          "failure_final_recipient": [r["value"] for r in refs if r["role"].startswith("recipient address")],
          "peg_out_service_address": [r["value"] for r in refs if r["role"].startswith("SideSwap allowlisted")],
          "failure_txids": [r["value"] for r in refs if r["chain"] == "Bitcoin" and len(r["value"]) == 64],
          "note": "From data/incidents/research batch notes for E64 (onchain_refs). failure_final_recipient: the "
                  "address that ended up with the failure's release. peg_out_service_address: the allowlisted "
                  "address of the peg-out service through which the failure's release was paid; the same service "
                  "also receives legitimate peg-outs, so it is not an exclusion criterion by itself."}
    p.write_text(json.dumps(rp, indent=1))
    return rp


# ------------------------------------------------------------------ fetch
def addr_history(addr):
    """All confirmed transactions of an address (Esplora pages of 25, newest first), cached per page."""
    d = RAW / "esplora" / "addr" / addr[:16]
    txs, last, n = [], None, 0
    while True:
        suffix = "" if last is None else f"/{last}"
        page = cached(d / f"page_{n:04d}.json", [f"{b}/address/{addr}/txs/chain{suffix}" for b in ESPLORA])
        txs += page
        if len(page) < 25:
            break
        last = page[-1]["txid"]
        n += 1
    return txs


def get_tx(txid):
    return cached(RAW / "esplora" / "tx" / f"{txid}.json", [f"{b}/tx/{txid}" for b in ESPLORA])


def pegs_list(stop_before_ts):
    """Peg list pages (15 per page, newest first) until a page ends before stop_before_ts."""
    d = RAW / "liquid" / "pegs_list"
    out, off = [], 0
    while True:
        page = cached(d / f"off_{off:06d}.json", [f"{LIQ}/pegs/list/{off}"])
        out += page
        if len(page) < 15 or page[-1]["blocktime"] < stop_before_ts:
            break
        off += 15
        if off % 1500 == 0:
            print("  pegs list offset", off, iso(page[-1]["blocktime"]), flush=True)
    seen, uniq = set(), []   # offset paging repeats rows if the list grows during the crawl
    for e in out:
        k = (e["txid"], e["txindex"])
        if k not in seen:
            seen.add(k)
            uniq.append(e)
    return uniq


def is_fed_template(asm):
    """11-of-15 multisig with a CSV-delayed 2-of-3 branch (the federation peg script template)."""
    t = (asm or "").split()
    return len(t) >= 40 and t[0] == "OP_PUSHNUM_11" and "OP_PUSHNUM_15" in t and "OP_CSV" in t


def main_addresses():
    """Current main address and its predecessors, newest first, with their histories."""
    rp = release_points()
    chain = [rp["federation_main"]]
    hist = {}
    while True:
        a = chain[-1]
        txs = addr_history(a)
        hist[a] = txs
        first = min(t["status"]["block_time"] for t in txs)
        if first < T_START - 7 * 86400 or len(chain) > 6:
            break
        early = sorted(txs, key=lambda t: t["status"]["block_height"])[:40]
        cand = collections.Counter()
        for t in early:
            for v in t["vin"]:
                b = v["prevout"]["scriptpubkey_address"]
                if b != a and b not in chain and is_fed_template(v.get("inner_witnessscript_asm")):
                    cand[b] += 1
        if not cand:
            break
        nxt, n = cand.most_common(1)[0]
        if n < 5:   # a predecessor main address is spent in most early transactions; peg-in addresses once
            break
        chain.append(nxt)
    rp["federation_main_chain"] = chain
    (RAW / "release_points.json").write_text(json.dumps(rp, indent=1))
    return chain, hist


def fetch():
    for p in ["pegs/count", "pegs/month", "reserves/month", "reserves/addresses", "reserves/utxos", "pegs"]:
        cached(RAW / "liquid" / (p.replace("/", "_") + ".json"), [f"{LIQ}/{p}"])
    chain, hist = main_addresses()
    for i, a in enumerate(chain):
        bt = [t["status"]["block_time"] for t in hist[a]]
        print(f"main address #{i}: txs {len(bt)} first {iso(min(bt))} last {iso(max(bt))} "
              f"in window {sum(T_START <= b <= T_END for b in bt)}", flush=True)
    pegs = pegs_list(T_START - 21 * 86400)
    print("peg list rows", len(pegs), "from", iso(min(e["blocktime"] for e in pegs)), flush=True)
    have = {t["txid"] for a in chain for t in hist[a]}
    need = sorted({e["bitcointxid"] for e in pegs if e["amount"] < 0 and e["bitcointxid"]
                   and T_START - 21 * 86400 <= e["blocktime"] <= T_FAIL} - have)
    print("peg-out payout transactions not in the main-address histories:", len(need), flush=True)
    for t in need:
        get_tx(t)


# ------------------------------------------------------------------ build
def load_all():
    rp = release_points()
    chain = rp["federation_main_chain"]
    txs = {}
    for a in chain:
        for t in addr_history(a):
            txs[t["txid"]] = t
    pegs = pegs_list(T_START - 21 * 86400)
    for e in pegs:
        if e["amount"] < 0 and e["bitcointxid"] and e["bitcointxid"] not in txs \
                and T_START - 21 * 86400 <= e["blocktime"] <= T_FAIL:
            txs[e["bitcointxid"]] = get_tx(e["bitcointxid"])
    return rp, chain, txs, pegs


def build():
    rp, chain, txs, pegs = load_all()
    mains = set(chain)
    reserve_now = {x["bitcoinaddress"] for x in cached(RAW / "liquid" / "reserves_addresses.json", [])}
    pegin_addrs = {e["bitcoinaddress"] for e in pegs if e["amount"] > 0}
    pegouts = {}
    for e in pegs:
        if e["amount"] < 0 and e["bitcointxid"]:
            pegouts.setdefault((e["bitcointxid"], e["bitcoinindex"]), []).append(e)
    # federation addresses: mains, co-spent inputs of transactions that spend a main address, peg-in deposits
    fed = set(mains) | reserve_now | pegin_addrs
    cospent_template = collections.Counter()
    for t in txs.values():
        ins = [v["prevout"]["scriptpubkey_address"] for v in t["vin"]]
        if any(a in mains for a in ins):
            for v in t["vin"]:
                a = v["prevout"]["scriptpubkey_address"]
                if a not in mains:
                    fed.add(a)
                    cospent_template[is_fed_template(v.get("inner_witnessscript_asm"))] += 1
    fail_final = set(rp["failure_final_recipient"])
    service = set(rp["peg_out_service_address"])
    rows, txinfo = [], collections.Counter()
    for t in sorted(txs.values(), key=lambda t: (t["status"]["block_height"], t["txid"])):
        ts = t["status"]["block_time"]
        ins = [v["prevout"]["scriptpubkey_address"] for v in t["vin"]]
        fed_in = [a in fed or is_fed_template(v.get("inner_witnessscript_asm")) for a, v in zip(ins, t["vin"])]
        if not any(fed_in):
            txinfo["not federation-signed (payment into a federation address)"] += 1
            continue
        if not all(fed_in):
            txinfo["mixed inputs (federation and other)"] += 1
        tmpl = all(is_fed_template(v.get("inner_witnessscript_asm")) for v in t["vin"])
        txinfo["federation-signed"] += 1
        for o in t["vout"]:
            a = o.get("scriptpubkey_address")
            n = t["vout"].index(o)
            base = {"txid": t["txid"], "vout": n, "block": t["status"]["block_height"], "ts": ts,
                    "to": a, "btc": o["value"] / 1e8, "all_inputs_template": tmpl, "n_out": len(t["vout"])}
            if a is None:
                rows.append(dict(base, cls="no_address_output"))
                continue
            if a in mains:
                rows.append(dict(base, cls="change_main"))
                continue
            if a in fed:
                rows.append(dict(base, cls="internal_federation"))
                continue
            m = pegouts.get((t["txid"], n), [])
            r = dict(base, cls="release", matched=len(m), service=a in service,
                     peg_amount_btc=(-sum(x["amount"] for x in m) / 1e8) if m else None,
                     peg_time=min(x["blocktime"] for x in m) if m else None,
                     peg_addr_ok=all(x["bitcoinaddress"] == a for x in m) if m else None)
            excl = ""
            if ts >= T_FAIL:
                excl = "at_or_after_failure"
            elif ts < T_START:
                excl = "before_window"
            elif a in fail_final:
                excl = "failure_recipient"
            r["exclude"] = excl
            rows.append(r)
    (RAW / "rows_all.json").write_text(json.dumps(rows))
    rel = [r for r in rows if r["cls"] == "release" and not r["exclude"]]
    win_tx = {r["txid"] for r in rows if T_START <= r["ts"] <= T_END}
    cls = collections.Counter(r["cls"] for r in rows if T_START <= r["ts"] <= T_END)
    # peg-out records whose payout falls in the window but whose output was not classified as a release
    rel_keys = {(r["txid"], r["vout"]) for r in rel}
    out_keys = {(r["txid"], r["vout"]): r for r in rows}
    orphan = []
    for (txid, n), es in pegouts.items():
        t = txs.get(txid)
        if t and T_START <= t["status"]["block_time"] <= T_END and (txid, n) not in rel_keys:
            orphan.append({"txid": txid, "vout": n, "cls": out_keys.get((txid, n), {}).get("cls"),
                           "amount": [e["amount"] for e in es]})
    chk = {
        "window": [iso(T_START), iso(T_END)],
        "main_address_chain_len": len(chain),
        "federation_address_set": len(fed),
        "cospent_inputs_with_template": dict(cospent_template),
        "tx_classes": dict(txinfo),
        "federation_txs_in_window": len(win_tx),
        "output_classes_in_window": dict(cls),
        "releases_in_window": len(rel),
        "releases_matched_one": sum(r["matched"] == 1 for r in rel),
        "releases_matched_multi": sum(r["matched"] > 1 for r in rel),
        "releases_unmatched": sum(r["matched"] == 0 for r in rel),
        "matched_address_mismatch": sum(1 for r in rel if r["matched"] and not r["peg_addr_ok"]),
        "matched_amount_diff_btc": sorted(round(r["btc"] - r["peg_amount_btc"], 8) for r in rel if r["matched"])[:3]
        + sorted(round(r["btc"] - r["peg_amount_btc"], 8) for r in rel if r["matched"])[-3:],
        "pegout_records_paid_in_window_not_release": orphan[:20],
        "n_pegout_records_paid_in_window_not_release": len(orphan),
        "exclusions": dict(collections.Counter(r["exclude"] for r in rows if r["cls"] == "release")),
        "releases_to_service_address": sum(r["service"] for r in rel),
    }
    (RAW / "build_checks.json").write_text(json.dumps(chk, indent=1))
    print(json.dumps(chk, indent=1))


# ------------------------------------------------------------------ price + write
def price_rows():
    rows = json.loads((RAW / "rows_all.json").read_text())
    rel = [r for r in rows if r["cls"] == "release" and not r["exclude"]]
    if not rel:
        return rows
    t0, t1 = min(r["ts"] for r in rel), max(r["ts"] for r in rel)
    hourly = pricing.chart(COIN, t0, t1, "1h", RAW / "prices", search_width=1800)
    daily = pricing.chart(COIN, t0, t1, "1d", RAW / "prices", search_width=43200)
    for r in rel:
        p = pricing.nearest(hourly, r["ts"], 2 * 3600)
        src = "hourly"
        if p is None:
            p = pricing.nearest(daily, r["ts"], 36 * 3600)
            src = "daily" if p is not None else None
        r["price"], r["price_src"] = p, src
        r["usd"] = round(r["btc"] * p, 2) if p is not None else None
    (RAW / "rows_all.json").write_text(json.dumps(rows))
    print("priced", sum(r["usd"] is not None for r in rel), "of", len(rel),
          collections.Counter(r["price_src"] for r in rel), "hourly points", len(hourly), "daily points", len(daily))
    return rows


def write():
    rows = json.loads((RAW / "rows_all.json").read_text())
    rel = sorted((r for r in rows if r["cls"] == "release" and not r["exclude"]), key=lambda r: (r["ts"], r["txid"], r["vout"]))
    with open(LEGIT / f"{FID}.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ts_utc", "leg", "asset", "amount", "usd", "kind", "priced"])
        for r in rel:
            w.writerow([iso(r["ts"]), LEG, "BTC", f"{r['btc']:.8f}", "" if r.get("usd") is None else f"{r['usd']:.2f}",
                        "native", "yes" if r.get("usd") is not None else "no"])
    print("wrote", len(rel), "rows")


if __name__ == "__main__":
    for s in sys.argv[1:] or ["all"]:
        if s in ("fetch", "all"):
            fetch()
        if s in ("build", "all"):
            build()
        if s in ("price", "all"):
            price_rows()
        if s in ("write", "all"):
            write()
