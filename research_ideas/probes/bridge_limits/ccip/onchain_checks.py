"""Read the token pools' own rate-limiter state where the documented buckets cannot accommodate the history.

The replay with the buckets recorded in the documentation (flows_analyze.py, "in force") flags a few transfers
that exceed the tokens available.  A send that exceeds the source pool's outbound bucket reverts and leaves no
message, and an execution that exceeds the destination pool's inbound bucket reverts until the bucket refills,
so every flagged transfer means that the bucket on chain differed from the documented one at that time.  For
each flagged lane and side whose pool is on an EVM chain with a public endpoint that serves historical state,
this script

  1. reads getCurrent{Outbound,Inbound}RateLimiterState(remoteChainSelector) of the pool (TokenPool v1.5 / v1.6;
     returns tokens, lastUpdated, isEnabled, capacity, rate, as of the end of the block) at N_PROBES evenly
     spaced blocks over a window that runs from the documented change before the first flagged transfer (at
     most 30 days earlier, at least 3 days) to the documented change after the last one plus 3 days (at most 30
     days later, at least 3 days), and locates every change of (isEnabled, capacity, rate) between consecutive
     probes by bisection on block numbers;
  2. reads the state at the end of the block before each flagged transfer; where it differs from the probe
     series (a setting shorter than the probe spacing), bisects for the block where it began and reads the state
     at the end of the transfer's block to see whether it was reset inside that block;
  3. downloads the pool's event log in the block range of each flagged transfer and decodes ChainConfigured /
     ConfigChanged / TokensConsumed and the v1.5 / v1.6 lock, burn and consumption events;
  4. writes data/ccip/onchain/amendments.json: the series read on chain inside each window, for
     flows_analyze.py to splice into the documented series (the documented series resumes after the window).
State reads and block timestamps are cached in data/ccip/onchain/cache_<chain>.json (block number, return data),
so a rerun repeats no call.  No transaction identifiers are kept.

Run: python -I onchain_checks.py   (after flows_analyze.py; rerun flows_analyze.py afterwards)
"""
import datetime as dt
import json
import math
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import pandas as pd  # noqa: E402
import requests  # noqa: E402
from Crypto.Hash import keccak  # noqa: E402

import ccip_common as cc  # noqa: E402
import flows_analyze as fa  # noqa: E402

OUT = os.path.join(cc.DATA, "onchain")
RPCS = {
    "mainnet": ["https://rpc.mevblocker.io", "https://eth.drpc.org"],
    "monad-mainnet": ["https://rpc-mainnet.monadinfra.com", "https://rpc1.monad.xyz"],
    "plasma-mainnet": ["https://rpc.plasma.to"],
    "ethereum-mainnet-arbitrum-1": ["https://arbitrum.gateway.tenderly.co", "https://arbitrum-one.public.blastapi.io"],
    "ethereum-mainnet-base-1": ["https://base.drpc.org", "https://mainnet.base.org",
                                "https://base.gateway.tenderly.co"],
}
LOG_CHUNK = {"mainnet": 2000, "monad-mainnet": 100, "plasma-mainnet": 1000, "ethereum-mainnet-arbitrum-1": 500,
             "ethereum-mainnet-base-1": 1000}
N_PROBES = 60
DAY = 86400


def k256(s):
    h = keccak.new(digest_bits=256)
    h.update(s.encode())
    return h.hexdigest()


EVENTS = {"0x" + k256(s): s for s in [
    "ChainConfigured(uint64,(bool,uint128,uint128),(bool,uint128,uint128))",
    "ConfigChanged((bool,uint128,uint128))", "TokensConsumed(uint256)",
    "Locked(address,uint256)", "Released(address,address,uint256)", "Burned(address,uint256)",
    "Minted(address,address,uint256)", "LockedOrBurned(uint64,address,address,uint256)",
    "ReleasedOrMinted(uint64,address,address,address,uint256)",
    "OutboundRateLimitConsumed(uint64,address,uint256)", "InboundRateLimitConsumed(uint64,address,uint256)",
    "RateLimitAdminSet(address)", "BridgeLimitUpdated(uint256,uint256)"]}


def fmt(t):
    return dt.datetime.fromtimestamp(int(t), dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


class Chain:
    """JSON-RPC client with a persistent cache of block timestamps and eth_call results."""

    def __init__(self, chain):
        self.chain, self.urls, self.n = chain, RPCS[chain], 0
        self.cache_path = os.path.join(OUT, f"cache_{chain}.json")
        self.cache = (cc.load_json(self.cache_path) if os.path.exists(self.cache_path)
                      else {"ts": {}, "call": {}, "first_access_utc": cc.utcnow()})
        self.sess = requests.Session()  # keep connections open across calls
        self.latest = int(self.rpc("eth_blockNumber", []), 16)

    def save(self):
        with open(self.cache_path, "w", encoding="utf-8") as f:
            json.dump(self.cache, f)

    def rpc(self, method, params):
        last = None
        for attempt in range(8):
            for u in self.urls:
                try:
                    r = self.sess.post(u, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
                                       headers={"User-Agent": "Mozilla/5.0"}, timeout=90)
                    self.n += 1
                    js = r.json()
                except (requests.RequestException, ValueError) as e:
                    last = (u, repr(e)[:200])
                    continue
                if "error" in js:
                    last = (u, js["error"])
                    continue
                return js["result"]
            time.sleep(min(60, 2 ** attempt))
        raise RuntimeError(f"{self.chain} {method} failed: {last}")

    def ts(self, n):
        k = str(n)
        if k not in self.cache["ts"]:
            self.cache["ts"][k] = int(self.rpc("eth_getBlockByNumber", [hex(n), False])["timestamp"], 16)
        return self.cache["ts"][k]

    def call(self, to, data, block):
        k = f"{to}|{data}|{block}"
        if k not in self.cache["call"]:
            self.cache["call"][k] = self.rpc("eth_call", [{"to": to, "data": data}, hex(block)])
        return self.cache["call"][k]

    def block_at(self, t):
        """Smallest block with timestamp >= t (cached by t)."""
        ba = self.cache.setdefault("block_at", {})
        if str(int(t)) not in ba:
            ba[str(int(t))] = self._block_at(int(t))
        return ba[str(int(t))]

    def _block_at(self, t):
        ref = self.latest - 200000
        spb = (self.ts(self.latest) - self.ts(ref)) / (self.latest - ref)
        est = int(self.latest - (self.ts(self.latest) - t) / spb)
        step = max(10, int(DAY / spb))
        lo, hi = max(est - step, 1), min(est + step, self.latest)
        while self.ts(lo) >= t:
            lo = max(lo - step, 1)
            step *= 2
        step = max(10, int(DAY / spb))
        while self.ts(hi) < t and hi < self.latest:
            hi = min(hi + step, self.latest)
            step *= 2
        while hi - lo > 1:
            mid = (lo + hi) // 2
            if self.ts(mid) >= t:
                hi = mid
            else:
                lo = mid
        return hi


class Bucket:
    def __init__(self, ch, pool, side, remote_sel, decimals):
        self.ch, self.pool, self.dec = ch, pool, decimals
        fn = ("getCurrentOutboundRateLimiterState(uint64)" if side == "out"
              else "getCurrentInboundRateLimiterState(uint64)")
        self.data = "0x" + k256(fn)[:8] + format(int(remote_sel), "064x")

    def state(self, block):
        h = self.ch.call(self.pool, self.data, block)[2:]
        w = [int(h[i:i + 64], 16) for i in range(0, len(h), 64)]
        sc = 10 ** self.dec
        return {"tokens": w[0] / sc, "enabled": bool(w[2]), "capacity": w[3] / sc, "rate": w[4] / sc}

    def cfg(self, block):
        s = self.state(block)
        return (s["enabled"], s["capacity"], s["rate"])

    def first_block_with(self, lo, hi, target_differs_from):
        """Smallest block in (lo, hi] whose setting differs from target_differs_from, given cfg(lo) equals it
        and cfg(hi) does not."""
        while hi - lo > 1:
            mid = (lo + hi) // 2
            if self.cfg(mid) == target_differs_from:
                lo = mid
            else:
                hi = mid
        return hi


def decode_log(lg, dec, sel2key):
    sig = EVENTS.get(lg["topics"][0], "unknown")
    h = lg["data"][2:]
    w = [int(h[i:i + 64], 16) for i in range(0, len(h), 64)]
    sc = 10 ** dec
    rec = {"block": int(lg["blockNumber"], 16), "log_index": int(lg["logIndex"], 16), "event": sig.split("(")[0]}
    if sig.startswith("ChainConfigured"):
        rec.update({"remote": sel2key.get(str(w[0]), str(w[0])),
                    "out": [bool(w[1]), w[2] / sc, w[3] / sc], "in": [bool(w[4]), w[5] / sc, w[6] / sc]})
    elif sig.startswith("ConfigChanged"):
        rec.update({"setting": [bool(w[0]), w[1] / sc, w[2] / sc]})
    elif sig.startswith("TokensConsumed") or rec["event"] in ("Locked", "Burned", "Released", "Minted",
                                                               "LockedOrBurned", "ReleasedOrMinted",
                                                               "OutboundRateLimitConsumed",
                                                               "InboundRateLimitConsumed"):
        rec.update({"amount": w[-1] / sc if w else None})
    else:
        rec.update({"n_words": len(w)})
    return rec


def get_logs(ch, pool, b0, b1):
    out, b, chunk = [], b0, LOG_CHUNK[ch.chain]
    while b <= b1:
        e = min(b + chunk - 1, b1)
        try:
            out += ch.rpc("eth_getLogs", [{"address": pool, "fromBlock": hex(b), "toBlock": hex(e)}])
        except RuntimeError:
            if chunk > 10:
                chunk //= 4
                continue
            raise
        b = e + 1
    return out


def documented_changes(hist, refined, src, dst, tok, side):
    ser = fa.param_series(hist, refined, {}, src, dst, tok, side)
    return [p[0] for p in ser if p[0] != -math.inf]


def main():
    os.makedirs(OUT, exist_ok=True)
    R = cc.load_json(os.path.join(cc.DERIVED, "flows_results.json"))
    hist = pd.read_csv(os.path.join(cc.DERIVED, "lanes_history.csv"))
    refined = cc.load_json(os.path.join(cc.DERIVED, "param_changes_refined.json")).get("effective", {})
    chains = cc.load_json(os.path.join(cc.DATA, "lanes_current", "chains.json"))
    key2sel, sel2key = cc.selector_maps(chains)
    tokens_cur = cc.load_json(os.path.join(cc.DATA, "lanes_history", "current", "tokens.json"))
    amendments, report = {}, {}
    clients = {}
    for r in R["results"]:
        for side in ("out", "in"):
            s = r.get(f"{side}_inforce_doc")  # replay with the documented series only
            if not s or not s["flagged"]:
                continue
            key = f"{r['src']}|{r['dst']}|{r['token']}|{side}"
            pool_chain, remote = (r["src"], r["dst"]) if side == "out" else (r["dst"], r["src"])
            if pool_chain not in RPCS:
                report[key] = {"skipped": "no public endpoint with historical state"}
                continue
            tok = tokens_cur[r["token"]][pool_chain]
            dec = tok["decimals"]
            if side == "in" and "1.5." in str(tok.get("typeAndVersion", "")):
                dec = tokens_cur[r["token"]][remote]["decimals"]  # v1.5 inbound bucket in remote decimals
            ch = clients.setdefault(pool_chain, Chain(pool_chain))
            n0, started = ch.n, cc.utcnow()
            bk = Bucket(ch, tok["poolAddress"], side, key2sel[remote], dec)
            fl = s["flagged"]
            ft = [f["t"] for f in fl]
            docs = documented_changes(hist, refined, r["src"], r["dst"], r["token"], side)
            prev = max([t for t in docs if t <= min(ft)], default=min(ft))
            nxt = min([t for t in docs if t > max(ft)], default=max(ft))
            t0 = max(min(ft) - 30 * DAY, min(min(ft) - 3 * DAY, prev - DAY))
            t1 = min(max(ft) + 30 * DAY, max(max(ft) + 3 * DAY, nxt + 3 * DAY), ch.ts(ch.latest) - 600)
            b0, b1 = ch.block_at(t0), ch.block_at(t1)
            # 1. probes and bisection
            blocks = sorted({int(round(b0 + k * (b1 - b0) / (N_PROBES - 1))) for k in range(N_PROBES)})
            segs = [(blocks[0], bk.cfg(blocks[0]))]
            for x, y in zip(blocks, blocks[1:]):
                cx, cy = bk.cfg(x), bk.cfg(y)
                lo = x
                while cx != cy:  # walk through every change between x and y
                    hb = bk.first_block_with(lo, y, cx)
                    segs.append((hb, bk.cfg(hb)))
                    lo, cx = hb, bk.cfg(hb)
            # 2. state before each flagged transfer; short settings missed by the probes
            pick, seen_days = [], set()
            for f in fl:
                if f["utc"][:10] not in seen_days:
                    seen_days.add(f["utc"][:10])
                    pick.append(f)
            big = max(fl, key=lambda f: f["amount"])
            if big not in pick:
                pick.append(big)
            per, inserted, after_blocks = [], [], set()
            for f in pick[:8]:
                bt = ch.block_at(f["t"])
                st_before = bk.state(bt - 1)
                c_before = (st_before["enabled"], st_before["capacity"], st_before["rate"])
                series_val = [c for b, c in segs if b <= bt - 1][-1]
                rec = {"utc": f["utc"], "amount": f["amount"], "documented_capacity": f["capacity"],
                       "documented_rate": f["rate"], "state_before": st_before, "series_value": series_val}
                if c_before != series_val:
                    # where did it begin?  last segment start before bt-1 has series_val
                    lo = max(b for b, c in segs if b <= bt - 1)
                    start = bk.first_block_with(lo, bt - 1, series_val)
                    c_after = bk.cfg(bt)
                    if c_after == c_before:
                        nxt_seg = min([b for b, c in segs if b > bt] + [b1])
                        end = bk.first_block_with(bt, nxt_seg, c_before) if bk.cfg(nxt_seg) != c_before else nxt_seg
                        end_ts = ch.ts(end)
                    else:
                        end, end_ts = bt, ch.ts(bt) + 1  # reset inside the transfer's block, after the transfer
                    inserted.append((start, ch.ts(start), c_before, end_ts, bk.cfg(end if end != bt else bt)))
                    rec.update({"short_setting_from": fmt(ch.ts(start)), "short_setting_to": fmt(end_ts),
                                "reset_in_transfer_block": end == bt})
                lg = get_logs(ch, tok["poolAddress"], bt - 1, ch.block_at(f["t"] + 2))
                dl = [decode_log(x, dec, sel2key) for x in lg]
                rec["logs_in_block_range"] = dl
                # a setting changed later in the same block as the transfer applies only after it
                cons = [x for x in dl if x["event"] in ("TokensConsumed", "OutboundRateLimitConsumed",
                                                        "InboundRateLimitConsumed")
                        and x.get("amount") and abs(x["amount"] - f["amount"]) <= 1e-6 * f["amount"]]
                if cons:
                    c0 = cons[0]
                    if any(x["event"] in ("ConfigChanged", "ChainConfigured") and x["block"] == c0["block"]
                           and x["log_index"] > c0["log_index"] for x in dl):
                        after_blocks.add(c0["block"])
                        rec["setting_changed_after_transfer_in_same_block"] = True
                per.append(rec)
            # series inside the window: (time, setting); a change in a block where it followed the flagged
            # transfer is dated one second after the block
            pts = [(ch.ts(b) + (1 if b in after_blocks else 0), c) for b, c in segs]
            for start_b, start_ts, c, end_ts, c_end in inserted:
                pts.append((start_ts, c))
                pts.append((end_ts, c_end))
            pts.sort(key=lambda p: p[0])
            am = []
            for (ta, c), (tb, _) in zip(pts, pts[1:] + [(ch.ts(b1), None)]):
                if tb <= ta:
                    continue
                if am and am[-1]["setting"] == c and am[-1]["to"] == ta:
                    am[-1]["to"], am[-1]["to_utc"] = tb, fmt(tb)
                    continue
                am.append({"from": ta, "to": tb, "enabled": c[0], "b": c[1], "r": c[2], "setting": c,
                           "from_utc": fmt(ta), "to_utc": fmt(tb), "source": f"{pool_chain} pool state"})
            amendments[key] = am
            report[key] = {"pool_chain": pool_chain, "pool_version": tok.get("typeAndVersion"), "remote": remote,
                           "rpc": RPCS[pool_chain], "started_utc": started, "finished_utc": cc.utcnow(),
                           "window_utc": [fmt(ch.ts(b0)), fmt(ch.ts(b1))], "n_probes": len(blocks),
                           "n_calls_this_run": ch.n - n0, "n_flagged": len(fl),
                           "changes": [{"utc": fmt(ch.ts(b)), "setting": c} for b, c in segs[1:]],
                           "flagged_checked": per}
            ch.save()
            print("==", key, "calls", ch.n - n0, "window", fmt(ch.ts(b0)), fmt(ch.ts(b1)), flush=True)
            for a in am:
                print("   ", a["from_utc"], "->", a["to_utc"], a["setting"], flush=True)
            for p in per[:4]:
                print("   flagged", p["utc"], p["amount"], "before", (p["state_before"]["enabled"],
                      p["state_before"]["capacity"], p["state_before"]["rate"]), p.get("short_setting_from"),
                      p.get("short_setting_to"), [(x["event"], x.get("setting") or x.get("amount"))
                                                  for x in p["logs_in_block_range"]][:8], flush=True)
    for c in clients.values():
        c.save()
    with open(os.path.join(OUT, "amendments.json"), "w", encoding="utf-8") as fh:
        json.dump({"built_utc": cc.utcnow(), "source": "pool state via public JSON-RPC (onchain_checks.py)",
                   "rpc": RPCS, "amendments": amendments, "report": report}, fh, indent=1, default=str)


if __name__ == "__main__":
    main()
