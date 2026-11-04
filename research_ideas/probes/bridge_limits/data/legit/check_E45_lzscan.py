"""E45 cross-check: messages delivered to the adapter according to LayerZero Scan (2026-10-16).

Source: https://scan.layerzero-api.com/v1/messages/oapp/30101/<adapter> (public; newest first; paged with
nextToken). Every page is cached under raw/E45/public/lzscan_<n>.json (addresses and hashes stay in raw/).
The script pages back until the source timestamps fall before the window start, then compares the inbound
messages (destination eid 30101) delivered inside the window with the adapter's OFTReceived events
(by message guid). Output: raw/E45/public/lzscan_check.json.
Run: python -I -B data/legit/check_E45_lzscan.py
"""
import collections
import json
import pathlib
import time
import urllib.parse
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
RAW = HERE / "raw" / "E45"
PUB = RAW / "public"
PUB.mkdir(parents=True, exist_ok=True)
UA = {"User-Agent": "Mozilla/5.0 (bridge-limits-probe/1.0)", "Accept": "application/json"}
OFT_RECEIVED = "0xefed6d3500546b29533b128a29e3a94d70788727f0507505ac12eaf2e578fd9c"


def get(url):
    last = None
    for k in range(6):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=90) as r:
                return json.loads(r.read().decode())
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(3 * (k + 1))
    raise RuntimeError(f"{url[:100]}: {last}")


def main():
    c = json.loads((RAW / "contracts.json").read_text())
    W = json.loads((RAW / "blocks.json").read_text())
    a = c["release_point"]
    msgs = []
    token, n = None, 0
    while True:
        p = PUB / f"lzscan_{n}.json"
        if p.exists():
            j = json.loads(p.read_text())
        else:
            q = {"limit": 100}
            if token:
                q["nextToken"] = token
            j = get(f"https://scan.layerzero-api.com/v1/messages/oapp/30101/{a}?" + urllib.parse.urlencode(q))
            p.write_text(json.dumps(j))
            time.sleep(0.5)
        data = j.get("data") or []
        msgs += data
        token = j.get("nextToken")
        n += 1
        oldest = min((m.get("source", {}).get("tx", {}).get("blockTimestamp") or 10 ** 12) for m in data) if data else 0
        if n % 10 == 0:
            print("pages", n, "messages", len(msgs), "oldest source ts", oldest, flush=True)
        if not token or not data or oldest < W["t0"] - 7 * 86400:
            break
    eid_chain = {}
    for m in msgs:
        pw = m.get("pathway", {})
        for side, k in (("sender", "srcEid"), ("receiver", "dstEid")):
            ch = (pw.get(side) or {}).get("chain")
            if ch and pw.get(k):
                eid_chain[str(pw[k])] = ch
    inbound = {}
    for m in msgs:
        pw = m.get("pathway", {})
        if pw.get("dstEid") != 30101:
            continue
        d = m.get("destination", {})
        ts = (d.get("tx") or {}).get("blockTimestamp")
        inbound[m["guid"].lower()] = {"src": pw.get("srcEid"), "status": d.get("status"), "dst_ts": ts,
                                      "src_ts": m.get("source", {}).get("tx", {}).get("blockTimestamp")}
    in_win = {g: v for g, v in inbound.items() if v["dst_ts"] and W["t0"] <= v["dst_ts"] <= W["t1"]}
    ok = {g for g, v in in_win.items() if v["status"] == "SUCCEEDED"}
    # adapter events
    ev = set()
    for line in (RAW / "logs_own.jsonl").read_text().splitlines():
        for lg in json.loads(line)["res"]:
            if lg["topics"] and lg["topics"][0] == OFT_RECEIVED:
                ev.add(lg["topics"][1].lower())
    out = {"pages": n, "messages_listed": len(msgs), "inbound_listed": len(inbound),
           "inbound_delivered_in_window": len(in_win), "inbound_succeeded_in_window": len(ok),
           "status_in_window": dict(collections.Counter(v["status"] for v in in_win.values())),
           "oftreceived_events_in_window": len(ev), "in_both": len(ok & ev),
           "scan_only": len(ok - ev), "events_only": len(ev - ok),
           "scan_only_detail": [in_win[g] for g in sorted(ok - ev)][:20],
           "by_src_in_window": {f"{k} ({eid_chain.get(str(k), '?')})": v
                                for k, v in collections.Counter(v["src"] for v in in_win.values()).most_common()},
           "eid_chain": eid_chain}
    (PUB / "lzscan_check.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
