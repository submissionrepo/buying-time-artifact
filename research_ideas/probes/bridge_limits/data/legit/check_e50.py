"""E50 cross-checks for E50_README.md (2026-10-16): vault creation block, the relay contract's own transactions in
the window (each successful relay transaction should carry exactly one vault release), and the SYS price series
used against CoinGecko daily closes quoted in the research notes.

Reads raw/E50/targets.json and the caches of build_e50.py; writes raw/E50/checks.json (no addresses).
Run: python -I data/legit/check_e50.py
"""
import collections
import json
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import build_e50 as b  # noqa: E402

RAW = b.RAW


def main():
    w = json.loads((RAW / "window.json").read_text())
    addr = json.loads((RAW / "addr_vault.json").read_text())
    rc = b.rpc("eth_getTransactionReceipt", [addr["creation_transaction_hash"]])
    created_block = int(rc["blockNumber"], 16)
    created_ts = b.block_ts(created_block)
    # relay transactions (explorer), newest first, until the window start is passed
    pages = RAW / "relay_tx"
    pages.mkdir(exist_ok=True)
    params, k, items = None, 0, []
    while True:
        p = pages / f"page_{k:04d}.json"
        if p.exists():
            j = json.loads(p.read_text())
        else:
            q = "" if params is None else "?" + "&".join(f"{a}={v}" for a, v in params.items())
            j = b.http_json(f"{b.API}/addresses/{b.T['relay']}/transactions{q}")
            p.write_text(json.dumps(j))
            time.sleep(0.5)
        its = j.get("items") or []
        items += its
        params = j.get("next_page_params")
        k += 1
        if not its or params is None or min(it["block_number"] for it in its) < w["b0"]:
            break
    inwin = [it for it in items if w["b0"] <= it["block_number"] <= w["b1"]
             and (it.get("to") or {}).get("hash", "").lower() == b.RELAY]
    methods = collections.Counter((it.get("method"), it.get("status")) for it in inwin)
    # vault releases per transaction
    logs = []
    for p in sorted(RAW.glob("vault_logs_*.json")):
        logs += json.loads(p.read_text())
    unf_tx = collections.Counter(lg["transactionHash"].lower() for lg in logs if lg["topics"][0] == b.UNFREEZE)
    ok_relay = {it["hash"].lower() for it in inwin if it.get("status") == "ok"}
    ok_with_release = sum(1 for h in ok_relay if unf_tx.get(h))
    releases_outside_relay_tx = sum(n for h, n in unf_tx.items() if h not in ok_relay)
    # SYS price series used (DefiLlama hourly) against CoinGecko daily values quoted in the research notes
    px = b.Prices(w["ts_b0"], w["ts_b1"])
    h, d = px.load("coingecko:syscoin")
    def day_mean(day):
        t0 = int(b.to_ts(day + "T00:00:00Z"))
        v = [p for t, p in h if t0 <= t < t0 + 86400]
        return sum(v) / len(v) if v else None
    out = {
        "vault_created_block": created_block, "vault_created_utc": b.iso(created_ts),
        "relay_tx_pages": k, "relay_tx_in_window": len(inwin), "relay_methods_status": {f"{m}|{s}": n for (m, s), n in methods.items()},
        "relay_ok_tx": len(ok_relay), "relay_ok_tx_with_release": ok_with_release,
        "releases_per_tx_max": max(unf_tx.values()) if unf_tx else 0,
        "releases_not_in_an_ok_relay_tx": releases_outside_relay_tx,
        "sys_hourly_points": len(h), "sys_daily_points": len(d),
        "sys_hourly_first_last": [b.iso(h[0][0]), b.iso(h[-1][0])] if h else None,
        "sys_daily_mean_hourly": {day: day_mean(day) for day in ("2026-01-10", "2026-03-01", "2026-05-01",
                                                                 "2026-06-06", "2026-06-07")},
    }
    (RAW / "checks.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
