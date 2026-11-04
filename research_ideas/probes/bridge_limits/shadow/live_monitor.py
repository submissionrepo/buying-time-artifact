"""Live shadow run of the deposit-backing check on two bridges between Ethereum and BSC (started 2026-10-17).

Streams: Wormhole's token bridge and Chainlink CCIP, releases on Ethereum of transfers from BSC and releases on
BSC of transfers from Ethereum (the pairs of raw/wormhole/targets.json and raw/ccip/targets.json, the same as the
42-day dataset built by wormhole_collect.py and ccip_collect.py).

Poll. Every P = 12 s a poller per chain asks one public endpoint (round robin over the pool below) for its latest
block, its finalized block and the logs of both bridges' release events since the last poll (Wormhole
TransferRedeemed of the token bridge, CCIP ExecutionStateChanged of the OffRamps). A release's time is its block's
timestamp; it is seen when the poll that returned its log completes.

Decode and check. Releases of the pair are decoded with the dataset's code (wormhole_decode.new_releases,
ccip_decode.new_releases, fed the poll's logs) and each is checked at once with the dataset's source lookup
(wormhole_decode.find_source, ccip_decode.find_source): a release is confirmed when its source message exists, the
source transaction moved the value (the amount went into custody or was burned) and the message agrees with the
release in amount, token and recipient, the rule of the dataset's columns matched, value_moved and amount_agrees.
A release not confirmed at the first check is checked again 60 s and 300 s after it, then every 15 min until
24 h after it ("standing" if never confirmed).

Forged twins. After the first check of a release, the same lookup runs on a copy whose source message was never
issued (Wormhole: sequence number + 10^9 and no signed-message time to search around; CCIP: sequence number +
10^9 and a random message id), and the agreement rule runs on copies with the amount raised by one base unit and
with another recipient, against the source message the release's own check found. Each twin should be flagged.

Sweep. Every 10 min another query, through an endpoint picked at random, re-reads the release events of blocks
the polls read 5 to 15 min earlier; events the polls missed are decoded and checked then (mode "sweep").

Files. shadow/live/ holds no addresses and no transaction hashes: events.jsonl (one line per release once its
checks end), twins.jsonl, polls.csv, finality.csv, sweeps.csv, clock.csv (offset of this computer's clock from
Cloudflare's, hourly), status.json. shadow/raw/live/ (not committed) keeps the decoded releases and source
records with addresses and hashes (releases.jsonl), the state (state.json, pending.json) and errors.log.

Run:     python -I shadow/live_monitor.py run [--minutes N]   resumes from the saved state; a gap of more
                                                                     than 10 min is read in mode "backfill"
         python -I shadow/live_monitor.py summary             results/shadow_live.json and .md
         python -I shadow/live_monitor.py status
Start detached: shadow/run_live.ps1 (a scheduled task that runs pythonw, without a console window, at logon and
every 10 minutes; a run while the monitor is up is skipped, so it also restarts the monitor after a crash).
Stop: shadow/stop_live.ps1 (writes shadow/live/STOP; the monitor saves its state and exits within a minute and
does not start while the file exists; run_live.ps1 removes it).
"""
from __future__ import annotations

import collections
import csv
import datetime as dt
import heapq
import itertools
import json
import math
import os
import pathlib
import queue
import random
import re
import sys
import threading
import time
import traceback
import urllib.request
from decimal import Decimal

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import wormhole_decode as wd  # noqa: E402
import ccip_decode as cd  # noqa: E402
import ccip_collect as cc  # noqa: E402

LIVE = HERE / "live"
PRIV = HERE / "raw" / "live"
RESULTS = ROOT / "results"
CHAINS = ("ethereum", "bsc")
P = 12.0
MARGIN = {"ethereum": 0, "bsc": 2}            # a poll reads up to this many blocks below the endpoint's head
MAX_RANGE = {"ethereum": 500, "bsc": 2_000}   # blocks per query while catching up
BLOCK_S = {"ethereum": 12.0, "bsc": 0.45}
BACKFILL_S = 600                              # a poll starting this far behind the head reads in backfill mode
RECHECK_S = [60, 300] + [300 + 900 * k for k in range(1, 96)]   # after the first check; the last is at 24 h
SWEEP_EVERY_S, SWEEP_LAG_S, SWEEP_MAX_S = 600, 300, 3600
WORKERS = 4
KEEP_KEYS_S = 3 * 86_400
SAVE_EVERY_S = 30
FORGED_OFFSET = 10 ** 9
OTHER_RECIPIENT = "0x" + "11" * 20
DEMO_KEY = (__import__("os").environ.get("NODEREAL_KEY") or "unset")  # NodeReal endpoint key from the environment

# Endpoints tested 2026-10-17 for the poll's three calls (latest and finalized block, eth_getLogs over a few
# blocks with an address list and a topic list). BSC: the bnbchain and defibit dataseeds answer 'limit exceeded'
# to eth_getLogs, api.zan.top HTTP 429, drpc HTTP 400 over 600 blocks; publicnode at times answers 'block range
# extends beyond current head' (its backends differ), so it comes last.
POLL_URLS = {
    "ethereum": ["https://ethereum-rpc.publicnode.com", "https://mainnet.gateway.tenderly.co",
                 "https://rpc.mevblocker.io", "https://eth.drpc.org", "https://rpc.flashbots.net",
                 "https://eth.api.pocket.network"],
    "bsc": ["https://rpc-bsc.48.club", "https://bsc.rpc.blxrbdn.com",
            f"https://bsc-mainnet.nodereal.io/v1/{DEMO_KEY}", "https://bsc.api.pocket.network",
            "https://bsc-rpc.publicnode.com"],
}
# eth_getLogs for the decoders' own lookups (wormhole_decode.Client: url and largest range)
WH_LOG_EPS = {
    "ethereum": [("https://mainnet.gateway.tenderly.co", 50_000), ("https://ethereum-rpc.publicnode.com", 10_000),
                 ("https://rpc.mevblocker.io", 10_000), ("https://eth.api.pocket.network", 10_000)],
    "bsc": [("https://rpc-bsc.48.club", 5_000), ("https://bsc.rpc.blxrbdn.com", 5_000),
            (f"https://bsc-mainnet.nodereal.io/v1/{DEMO_KEY}", 50_000), ("https://bsc.api.pocket.network", 1_000)],
}
# ccip_collect.CachedRpc pools for this process (archive state is needed for the OnRamp counters at past blocks)
cc.URLS = {"ethereum": ["https://rpc.mevblocker.io", "https://mainnet.gateway.tenderly.co",
                        "https://ethereum-rpc.publicnode.com"],
           "bsc": ["https://api.zan.top/bsc-mainnet", f"https://bsc-mainnet.nodereal.io/v1/{DEMO_KEY}"]}
cc.LOG_URLS = {"ethereum": cc.URLS["ethereum"],
               "bsc": [f"https://bsc-mainnet.nodereal.io/v1/{DEMO_KEY}", "https://rpc-bsc.48.club",
                       "https://bsc.rpc.blxrbdn.com"]}

HEX = re.compile(r"0x[0-9a-fA-F]{40,}")


def scrub(s):
    """Text for the public files: no addresses, hashes or API keys."""
    return HEX.sub("0x...", str(s)).replace(DEMO_KEY, "...")


def iso(t):
    return dt.datetime.fromtimestamp(float(t), dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def units(raw, dec):
    if raw is None or dec is None:
        return ""
    return format((Decimal(int(raw)) / (Decimal(10) ** int(dec))).normalize(), "f")


def atomic_write(path, text):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def rpc_call(url, method, params, timeout=15):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json",
                                                          "User-Agent": "bridge-limits-probe/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        j = json.loads(r.read().decode())
    if "error" in j:
        raise RuntimeError(str(j["error"])[:160])
    return j["result"]


# ------------------------------------------------------------------------------------------------ RPC plumbing
class MemCache:
    """In-memory stand-in for the collectors' sqlite caches (both interfaces), cleared when full."""

    def __init__(self, cap=200_000):
        self.d, self.ts, self.cap = {}, {}, cap
        self.lock = threading.Lock()
        self.db = self          # wormhole_decode.Client commits through cache.db

    def get(self, k):
        return self.d.get(k)

    def put(self, k, v, commit=True):
        if len(self.d) >= self.cap:
            self.d.clear()
        self.d[k] = v

    def commit(self):
        pass

    def get_ts(self, blocks):
        return {b: self.ts[b] for b in blocks if b in self.ts}

    def put_ts(self, m):
        if len(self.ts) >= self.cap:
            self.ts.clear()
        self.ts.update(m)


class LiveCcipRpc(cc.CachedRpc):
    """ccip_collect.CachedRpc with shorter timeouts and fewer retries (a live check should fail and be re-checked
    rather than wait out a long outage)."""

    def __init__(self, chain, cache):
        super().__init__(chain, cache)
        self.timeout = 30

    def call(self, method, params, retries=8):
        return super().call(method, params, retries=retries)


_TL = threading.local()


def clients():
    """Per-thread decoder clients: wormhole_decode.Client and ccip_collect.CachedRpc for each chain."""
    if not hasattr(_TL, "wh"):
        _TL.wh = {}
        for c in CHAINS:
            cl = wd.Client(c, cache_dir=None, endpoints=WH_LOG_EPS[c], timeout=30)
            cl.cache = MemCache()
            _TL.wh[c] = cl
        mc = MemCache()
        _TL.cc = {c: LiveCcipRpc(c, mc) for c in CHAINS}
    for c in CHAINS:
        _TL.cc[c]._head = None      # CachedRpc keeps its first head; a live lookup needs the current one
    return _TL.wh, _TL.cc


def _match(lg, address, topics, b0, b1):
    if not (b0 <= wd.hx(lg["blockNumber"]) <= b1):
        return False
    a = lg["address"].lower()
    if isinstance(address, str):
        if a != address.lower():
            return False
    elif a not in {x.lower() for x in address}:
        return False
    t = [x.lower() for x in lg["topics"]]
    for i, w in enumerate(topics or []):
        if w is None:
            continue
        if i >= len(t):
            return False
        if isinstance(w, (list, tuple)):
            if t[i] not in {x.lower() for x in w}:
                return False
        elif t[i] != w.lower():
            return False
    return True


class LogsFrom:
    """A decoder client whose eth_getLogs answers are a poll's logs; every other call goes to the client."""

    def __init__(self, client, logs):
        self._client, self._logs = client, logs

    def logs(self, address, topics, b0, b1, step=None, endpoints=None):
        return [lg for lg in self._logs if _match(lg, address, topics, int(b0), int(b1))]

    def __getattr__(self, k):
        return getattr(self._client, k)


# ------------------------------------------------------------------------------------------------ verdicts
def agree_ok(ag):
    return bool(ag.get("amount") and ag.get("token") and ag.get("recipient"))


def verdict_wh(s):
    if s is None:
        return "not_found", "no source message with this sequence"
    bad = []
    if s.get("value_moved") != "yes":
        bad.append("value not moved")
    if s.get("amount_agrees") != "yes":
        parts = [f"{k} disagrees" for k, v in (s.get("agree") or {}).items() if v is False]
        bad += parts or ["source message is not a token transfer"]
    return ("confirmed", "") if not bad else ("disagrees", "; ".join(bad))


def verdict_cc(s, r):
    if s is None:
        return "not_found", "no send event with this message id"
    i = r.get("token_index", 0)
    vals = s.get("value") or []
    v = vals[i] if i < len(vals) else None
    bad = []
    if not v or v.get("detail") == "none":
        bad.append("value not moved")
    c = s.get("compare") or {}
    if not c.get("agrees"):
        bad += [f"{k} disagrees" for k in ("token", "amount", "recipient") if not c.get(k)] or ["disagrees"]
    return ("confirmed", "") if not bad else ("disagrees", "; ".join(bad))


def outflow_rule_wh(rpc_dst, r, s, T):
    """Second rule for Wormhole releases the first rule did not confirm (tokens that take a fee on every transfer
    split one release into several transfers, which wormhole_decode reads as a relayer fee and the rest): every
    transfer of the released token out of custody (minted, for a wrapped token) between the redeem event and the
    next one, summed, equals the signed amount, and one of them goes to the recipient named in the source message.
    shadow/fee_token_check.py applies it to the 13 such releases of the 42-day dataset."""
    p = (s or {}).get("payload") or {}
    if not p or r.get("kind") not in ("unlock", "mint") or not r.get("token"):
        return None
    tb = T["chains"][r["dst_chain"]]["token_bridge"]
    logs = sorted(rpc_dst.receipt(r["tx"])["logs"], key=lambda x: wd.hx(x["logIndex"]))
    i = next((k for k, x in enumerate(logs) if wd.hx(x["logIndex"]) == r["log_index"]), None)
    if i is None:
        return None
    j = next((k for k in range(i + 1, len(logs)) if logs[k]["topics"] and logs[k]["topics"][0] == wd.REDEEMED
              and logs[k]["address"].lower() == tb), len(logs))
    frm = wd.ZERO if r["kind"] == "mint" else tb
    outs = [(wd.addr_from_word(x["topics"][2]), int(x["data"], 16)) for x in logs[i + 1:j]
            if x["address"].lower() == r["token"] and x["topics"] and x["topics"][0] == wd.TRANSFER
            and len(x["topics"]) == 3 and wd.addr_from_word(x["topics"][1]) == frm]
    to = wd.addr_from_word(p["to"]) if wd.word_is_address(p["to"]) else None
    return sum(v for _, v in outs) == wd.denormalize(p["amount"], r["decimals"]) and any(a == to for a, _ in outs)


def pid_alive(pid):
    import ctypes
    h = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(pid))     # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return False
    code = ctypes.c_ulong()
    ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(code))
    ctypes.windll.kernel32.CloseHandle(h)
    return code.value == 259                                            # STILL_ACTIVE


def rel_key(bridge, r):
    if bridge == "wormhole":
        return f"wh|{r['emitter_chain']}|{r['sequence']}"
    return f"cc|{r['message_id']}|{r['token_index']}"


def ev_key_wh(lg):
    t = lg["topics"]
    return f"wh|{int(t[1], 16)}|{int(t[3], 16)}"


def ev_key_cc(lg):
    e = cd.exec_event(lg)
    return f"cx|{e['message_id']}|{e['state']}"


def public_event(rec, end):
    r, s = rec["rel"], rec.get("source") or {}
    a = rec.get("attempts") or []
    conf = next((i for i, x in enumerate(a) if x["outcome"] == "confirmed"), None)
    notes = r.get("notes") if isinstance(r.get("notes"), list) else ([r["note"]] if r.get("note") else [])
    return {"bridge": rec["bridge"], "direction": f"{rec['src']}->{rec['dst']}", "kind": r.get("kind"),
            "token": scrub(r.get("symbol") or ""), "amount": units(r.get("amount_raw"), r.get("decimals")),
            "release_block": r.get("block"), "release_ts": r.get("ts"), "src_block": s.get("block"),
            "src_ts": s.get("ts"), "mode": rec["mode"], "poll_host": scrub(rec.get("host") or ""),
            "t_seen": rec["t_seen"], "t_decoded": rec.get("t_decoded"), "decode_tries": rec.get("decode_tries", 0),
            "attempts": [{k: x.get(k) for k in ("t0", "t1", "outcome", "reason", "src_final", "outflow_rule")}
                         for x in a],
            "confirmed_at_attempt": conf, "t_confirmed": a[conf]["t1"] if conf is not None else None,
            "final": end, "notes": [scrub(n) for n in notes if n]}


# ------------------------------------------------------------------------------------------------ the monitor
class Monitor:
    def __init__(self, force=False):
        LIVE.mkdir(parents=True, exist_ok=True)
        PRIV.mkdir(parents=True, exist_ok=True)
        self.WT = wd.load_targets()
        self.CFG = cd.load_targets()
        self.meta = {}
        self.stop_ev = threading.Event()
        self.lock = threading.RLock()
        self.flock = threading.Lock()
        self.q = queue.Queue()
        self.heap, self.hlock, self.tick = [], threading.Lock(), itertools.count()
        self.jid = itertools.count()
        self.cursor = {c: None for c in CHAINS}
        self.sweep_cursor = {c: None for c in CHAINS}
        self.final = {c: None for c in CHAINS}
        self.last_poll = {c: None for c in CHAINS}
        self.seen_ev, self.done, self.records, self.jobs = {}, {}, {}, {}
        self.counters = collections.Counter()
        self.started, self.restarts = time.time(), 0
        self.load(force)

    # -- state
    def load(self, force):
        pf = LIVE / "monitor.pid"
        if pf.exists() and not force:
            other = int(pf.read_text().strip() or 0)
            if other and other != os.getpid() and pid_alive(other):
                raise SystemExit(f"a monitor is running (process {other}); stop it first (or pass --force)")
        st = PRIV / "state.json"
        if st.exists():
            s = json.loads(st.read_text(encoding="utf-8"))
            self.cursor.update(s.get("cursor") or {})
            self.sweep_cursor.update(s.get("sweep_cursor") or {})
            self.seen_ev = s.get("seen_ev") or {}
            self.done = s.get("done") or {}
            self.counters.update(s.get("counters") or {})
            self.started = s.get("started", self.started)
            self.restarts = s.get("restarts", 0) + 1
        pf = PRIV / "pending.json"
        if pf.exists():
            p = json.loads(pf.read_text(encoding="utf-8"))
            self.records = p.get("records") or {}
            for job in (p.get("jobs") or {}).values():
                self.jobs[job["id"]] = job
                self.q.put(job)
            now = time.time()
            for key, rec in self.records.items():
                a = rec.get("attempts") or []
                if not a:
                    rec["first_check_after_restart"] = True
                    due = now
                else:
                    n = len(a)
                    due = a[0]["t1"] + RECHECK_S[min(n - 1, len(RECHECK_S) - 1)]
                self.schedule(max(due, now), {"type": "check", "key": key})

    def save(self):
        now = time.time()
        with self.lock:
            cut = now - KEEP_KEYS_S
            self.seen_ev = {k: t for k, t in self.seen_ev.items() if t >= cut}
            self.done = {k: t for k, t in self.done.items() if t >= cut}
            state = json.dumps({"saved_at": now, "started": self.started, "restarts": self.restarts,
                                "cursor": self.cursor, "sweep_cursor": self.sweep_cursor, "final": self.final,
                                "seen_ev": self.seen_ev, "done": self.done, "counters": dict(self.counters)})
            pend = json.dumps({"records": self.records, "jobs": self.jobs}, default=str)
            status = {"saved_utc": iso(now), "started_utc": iso(self.started), "restarts": self.restarts,
                      "last_poll_utc": {c: (iso(t) if t else None) for c, t in self.last_poll.items()},
                      "cursor": self.cursor, "finalized": self.final, "pending_checks": len(self.records),
                      "decode_jobs": len(self.jobs), "queued": self.q.qsize(),
                      "counters": dict(sorted(self.counters.items()))}
        atomic_write(PRIV / "state.json", state)
        atomic_write(PRIV / "pending.json", pend)
        atomic_write(LIVE / "status.json", json.dumps(status, indent=1))

    # -- files
    def append(self, path, line):
        with self.flock:
            with open(path, "a", encoding="utf-8", newline="") as f:
                f.write(line + "\n")

    def append_csv(self, name, header, row):
        path = LIVE / name
        with self.flock:
            new = not path.exists()
            with open(path, "a", encoding="utf-8", newline="") as f:
                w = csv.writer(f)
                if new:
                    w.writerow(header)
                w.writerow(row)

    def err(self, where):
        self.counters[f"error {where.split()[0]}"] += 1
        path = PRIV / "errors.log"
        with self.flock:
            if path.exists() and path.stat().st_size > 20_000_000:
                os.replace(path, PRIV / "errors.1.log")
            with open(path, "a", encoding="utf-8") as f:
                f.write(f"{iso(time.time())} {where}\n{traceback.format_exc()}\n")

    def poll_row(self, c, t0, host, ok, head=None, head_ts=None, fin=None, frm=None, to=None, n_logs=0, n_wh=0,
                 n_cc=0, mode="", dur=0.0, err=""):
        self.counters[f"poll {'ok' if ok else 'failed'} {c}"] += 1
        if ok:
            self.last_poll[c] = t0
        self.append_csv("polls.csv", ["chain", "t_wall", "host", "ok", "head", "head_ts", "finalized", "from_block",
                                      "to_block", "n_logs", "n_wormhole", "n_ccip", "mode", "dur_s", "error"],
                        [c, f"{t0:.3f}", scrub(host), int(ok), head, head_ts, fin, frm, to, n_logs, n_wh, n_cc, mode,
                         f"{dur:.3f}", scrub(err)])

    def set_final(self, c, fin, t):
        if fin is not None and fin != self.final[c]:
            self.final[c] = fin
            self.append_csv("finality.csv", ["chain", "t_wall", "finalized"], [c, f"{t:.3f}", fin])

    # -- what a poll reads
    def addresses(self, c):
        a = {self.WT["chains"][c]["token_bridge"].lower()}
        a |= {r["address"].lower() for r in cd.offramps(self.CFG, c)}
        return sorted(a)

    @staticmethod
    def topics0():
        return [wd.REDEEMED] + sorted(cd.EXEC_TOPICS)

    def split(self, c, logs):
        """The poll's logs that are releases of the pair: Wormhole redeems whose emitter is the other chain's token
        bridge, and CCIP executions of messages from the other chain."""
        src = wd.other_chain(c, self.WT)
        tb = self.WT["chains"][c]["token_bridge"].lower()
        ws = self.WT["chains"][src]
        t1, t2 = wd.topic_u(ws["wormhole_chain_id"]), ws["emitter32"].lower()
        offs = {r["address"].lower(): r["family"] for r in cd.offramps(self.CFG, c)}
        sel = cd.selector(self.CFG, src)
        wh, cx = [], []
        for lg in logs:
            a, t = lg["address"].lower(), [x.lower() for x in lg["topics"]]
            if a == tb and len(t) >= 4 and t[0] == wd.REDEEMED and t[1] == t1 and t[2] == t2:
                wh.append(lg)
            elif a in offs and t and t[0] in cd.EXEC_TOPICS:
                e = cd.exec_event(lg)
                if e and offs[a] == e["family"] and (e["source_selector"] is None or e["source_selector"] == sel):
                    cx.append(lg)
        return wh, cx

    def accept(self, c, frm, to, wh, cx, t_seen, mode, host):
        """Advance the cursor and queue the new events, in one step under the lock (a saved state never has the
        cursor past events it has not queued)."""
        with self.lock:
            new_wh = [lg for lg in wh if ev_key_wh(lg) not in self.seen_ev]
            new_cx = [lg for lg in cx if ev_key_cc(lg) not in self.seen_ev]
            for lg in new_wh:
                self.seen_ev[ev_key_wh(lg)] = t_seen
            for lg in new_cx:
                self.seen_ev[ev_key_cc(lg)] = t_seen
            if mode != "sweep":
                self.cursor[c] = to
            for bridge, logs in (("wormhole", new_wh), ("ccip", new_cx)):
                if logs:
                    job = {"type": "decode", "id": f"{int(t_seen * 1000)}-{next(self.jid)}", "bridge": bridge,
                           "chain": c, "b0": frm, "b1": to, "logs": logs, "t_seen": t_seen, "mode": mode,
                           "host": host, "tries": 0}
                    self.jobs[job["id"]] = job
                    self.q.put(job)
        return len(new_wh), len(new_cx)

    # -- scheduling and workers
    def schedule(self, due, job):
        with self.hlock:
            heapq.heappush(self.heap, (due, next(self.tick), job))

    def scheduler(self):
        while not self.stop_ev.is_set():
            now, due = time.time(), []
            with self.hlock:
                while self.heap and self.heap[0][0] <= now:
                    due.append(heapq.heappop(self.heap)[2])
            for job in due:
                self.q.put(job)
            self.stop_ev.wait(0.5)

    def worker(self):
        while not self.stop_ev.is_set():
            try:
                job = self.q.get(timeout=1.0)
            except queue.Empty:
                continue
            try:
                if job["type"] == "decode":
                    self.do_decode(job)
                else:
                    with self.lock:
                        rec = self.records.get(job["key"])
                    if rec is not None:
                        self.check(rec)
            except Exception:  # noqa: BLE001
                self.err(f"worker {job.get('type')}")

    def do_decode(self, job):
        whc, ccl = clients()
        c = job["chain"]
        diag = None
        try:
            if job["bridge"] == "wormhole":
                rels = wd.new_releases(LogsFrom(whc[c], job["logs"]), c, job["b0"], job["b1"], T=self.WT,
                                       meta=self.meta)
            else:
                diag = {}
                rels = cd.new_releases(LogsFrom(ccl[c], job["logs"]), c, job["b0"], job["b1"], diag=diag,
                                       discover=False)
        except Exception:  # noqa: BLE001
            job["tries"] += 1
            self.err(f"decode {job['bridge']} {c} try {job['tries']}")
            if job["tries"] < 6:
                self.schedule(time.time() + 20 * job["tries"], job)
            else:
                self.decode_failed(job)
            return
        t_dec = time.time()
        if diag is not None:
            for e in diag.get("executions") or []:
                self.counters[f"ccip executions {c} state {e['state']}"] += 1
            self.counters[f"ccip executions {c} success without token release"] += len(diag.get("success_without_release") or [])
            self.counters[f"ccip executions {c} pool problems"] += len(diag.get("no_pool_event") or [])
        recs = []
        with self.lock:
            self.jobs.pop(job["id"], None)
            for r in rels:
                key = rel_key(job["bridge"], r)
                if key in self.records or key in self.done:
                    continue
                rec = {"key": key, "bridge": job["bridge"], "dst": c, "src": r["src_chain"], "rel": r,
                       "t_seen": job["t_seen"], "mode": job["mode"], "host": job["host"], "t_decoded": t_dec,
                       "decode_tries": job["tries"], "attempts": []}
                self.records[key] = rec
                recs.append(rec)
                self.counters[f"releases {job['bridge']} {r['src_chain']}->{c} {job['mode']}"] += 1
        for rec in recs:
            self.check(rec)
            if rec["mode"] != "backfill":
                self.twins(rec)

    def decode_failed(self, job):
        with self.lock:
            self.jobs.pop(job["id"], None)
            self.counters[f"decode failed {job['bridge']} {job['chain']}"] += len(job["logs"])
        src = wd.other_chain(job["chain"], self.WT)
        for lg in job["logs"]:
            self.append(LIVE / "events.jsonl", json.dumps({
                "bridge": job["bridge"], "direction": f"{src}->{job['chain']}", "release_block": wd.hx(lg["blockNumber"]),
                "mode": job["mode"], "t_seen": job["t_seen"], "final": "decode_failed", "attempts": []}))

    def check(self, rec):
        whc, ccl = clients()
        r, src = rec["rel"], rec["src"]
        t0 = time.time()
        s, outcome, reason = None, "error", ""
        try:
            if rec["bridge"] == "wormhole":
                s = wd.find_source(whc[src], src, r, T=self.WT, meta=self.meta)
                outcome, reason = verdict_wh(s)
            else:
                s = cd.find_source(ccl[src], src, r)
                outcome, reason = verdict_cc(s, r)
        except Exception as e:  # noqa: BLE001
            reason = type(e).__name__
            self.err(f"check {rec['bridge']} {rec['dst']}")
        t1 = time.time()
        fin = self.final.get(src)
        sb = s.get("block") if s else None
        att = {"t0": round(t0, 3), "t1": round(t1, 3), "outcome": outcome, "reason": scrub(reason),
               "src_final": (sb <= fin) if (sb is not None and fin is not None) else None}
        if rec["bridge"] == "wormhole" and outcome == "disagrees" and s and s.get("value_moved") == "yes":
            try:
                att["outflow_rule"] = outflow_rule_wh(whc[rec["dst"]], r, s, self.WT)
            except Exception:  # noqa: BLE001
                self.err(f"outflow {rec['dst']}")
        end, due = None, None
        with self.lock:
            rec["attempts"].append(att)
            if s is not None:
                rec["source"] = s
            n = len(rec["attempts"])
            if outcome == "confirmed":
                end = "confirmed"
            elif n - 1 >= len(RECHECK_S):
                end = "standing"
            else:
                due = rec["attempts"][0]["t1"] + RECHECK_S[n - 1]
        if end:
            self.finish(rec, end)
        else:
            self.schedule(max(due, time.time()), {"type": "check", "key": rec["key"]})

    def finish(self, rec, end):
        with self.lock:
            self.records.pop(rec["key"], None)
            self.done[rec["key"]] = time.time()
            self.counters[f"final {end}"] += 1
        self.append(PRIV / "releases.jsonl", json.dumps(rec, default=str))
        self.append(LIVE / "events.jsonl", json.dumps(public_event(rec, end)))

    def twins(self, rec):
        whc, ccl = clients()
        r, src = rec["rel"], rec["src"]
        t0 = time.time()
        outcome = "error"
        try:
            if rec["bridge"] == "wormhole":
                tw = dict(r, sequence=r["sequence"] + FORGED_OFFSET, vaa=None)
                outcome, _ = verdict_wh(wd.find_source(whc[src], src, tw, T=self.WT, meta=self.meta))
            else:
                tw = dict(r, seq=r["seq"] + FORGED_OFFSET, message_id="0x" + os.urandom(32).hex())
                outcome, _ = verdict_cc(cd.find_source(ccl[src], src, tw), tw)
        except Exception:  # noqa: BLE001
            self.err(f"twin {rec['bridge']} {rec['dst']}")
        t1 = time.time()
        s = rec.get("source")
        amt = rcp = None
        try:
            if s and rec["bridge"] == "wormhole" and s.get("payload"):
                amt = not agree_ok(wd.agreement(dict(r, amount_raw=r["amount_raw"] + 1), s["payload"], r["dst_chain"], self.WT))
                rcp = not agree_ok(wd.agreement(dict(r, recipient=OTHER_RECIPIENT), s["payload"], r["dst_chain"], self.WT))
            elif s and rec["bridge"] == "ccip":
                amt = not cd.compare(s, dict(r, amount_raw=r["amount_raw"] + 1), r.get("decimals"))["agrees"]
                rcp = not cd.compare(s, dict(r, recipient=OTHER_RECIPIENT), r.get("decimals"))["agrees"]
        except Exception:  # noqa: BLE001
            self.err(f"twin-agreement {rec['bridge']} {rec['dst']}")
        a = rec["attempts"]
        self.counters[f"twins no-deposit {outcome}"] += 1
        self.append(LIVE / "twins.jsonl", json.dumps({
            "bridge": rec["bridge"], "direction": f"{src}->{rec['dst']}", "release_ts": r.get("ts"),
            "t_seen": rec["t_seen"], "t_decoded": rec["t_decoded"], "mode": rec["mode"],
            "release_first_check": a[0]["outcome"] if a else None, "no_deposit_t0": round(t0, 3),
            "no_deposit_t1": round(t1, 3), "no_deposit_outcome": outcome, "altered_amount_flagged": amt,
            "altered_recipient_flagged": rcp}))

    # -- the hourly clock check
    def clock(self):
        while not self.stop_ev.is_set():
            try:
                t0 = time.time()
                with urllib.request.urlopen("https://www.cloudflare.com/cdn-cgi/trace", timeout=10) as r:
                    txt = r.read().decode()
                t1 = time.time()
                ts = float(re.search(r"ts=([0-9.]+)", txt).group(1))
                self.append_csv("clock.csv", ["t_wall", "offset_s", "rtt_s"],
                                [f"{t1:.3f}", f"{ts - (t0 + t1) / 2:.3f}", f"{t1 - t0:.3f}"])
            except Exception:  # noqa: BLE001
                self.err("clock")
            self.stop_ev.wait(3600)


class Poller(threading.Thread):
    def __init__(self, mon, chain):
        super().__init__(daemon=True, name=f"poll-{chain}")
        self.mon, self.chain = mon, chain
        self.urls = POLL_URLS[chain]
        self.k = random.randrange(len(self.urls))
        self.bad = {}
        self.last_discover = 0.0

    def run(self):
        nxt = time.time()
        while not self.mon.stop_ev.is_set():
            try:
                self.poll()
            except Exception:  # noqa: BLE001
                self.mon.err(f"poll {self.chain}")
            if time.time() - self.last_discover > 3600:
                self.discover()
            nxt += P
            now = time.time()
            if nxt < now:
                nxt = now
            self.mon.stop_ev.wait(nxt - now)

    def poll(self):
        m, c = self.mon, self.chain
        t0 = time.time()
        for j in range(len(self.urls)):
            url = self.urls[(self.k + j) % len(self.urls)]
            if self.bad.get(url, 0) > t0:
                continue
            host = url.split("/")[2]
            try:
                hb = rpc_call(url, "eth_getBlockByNumber", ["latest", False])
                head, head_ts = wd.hx(hb["number"]), wd.hx(hb["timestamp"])
                fb = rpc_call(url, "eth_getBlockByNumber", ["finalized", False])
                fin = wd.hx(fb["number"]) if fb else None
                to = head - MARGIN[c]
                cur = m.cursor[c] if m.cursor[c] is not None else to - 1
                frm = cur + 1
                mode = "backfill" if (to - frm) * BLOCK_S[c] > BACKFILL_S else "live"
                to = min(to, frm + MAX_RANGE[c] - 1)
                logs = []
                if frm <= to:
                    logs = rpc_call(url, "eth_getLogs", [{"address": m.addresses(c), "topics": [m.topics0()],
                                                          "fromBlock": hex(frm), "toBlock": hex(to)}], timeout=30)
            except Exception as e:  # noqa: BLE001
                self.bad[url] = time.time() + 60
                m.poll_row(c, t0, host, False, dur=time.time() - t0, err=f"{type(e).__name__}: {e}"[:160])
                continue
            t_seen = time.time()
            self.k = (self.k + j + 1) % len(self.urls)
            m.set_final(c, fin, t_seen)
            wh, cx = m.split(c, logs)
            m.poll_row(c, t0, host, True, head, head_ts, fin, frm, to, len(logs), len(wh), len(cx), mode, t_seen - t0)
            if frm <= to:
                m.accept(c, frm, to, wh, cx, t_seen, mode, host)
            return

    def discover(self):
        """CCIP ramps registered on the routers now (a ramp upgrade during the run is followed)."""
        self.last_discover = time.time()
        _, ccl = clients()
        m, c = self.mon, self.chain
        try:
            ch = m.CFG["chains"][c]
            n0 = (len(ch["onramps"]), len(ch["offramps"]))
            cd.discover_ramps(ccl[c], c, ccl[c].head(), m.CFG)
            if (len(ch["onramps"]), len(ch["offramps"])) != n0:
                m.counters[f"ccip ramps discovered {c}"] += 1
        except Exception:  # noqa: BLE001
            m.err(f"discover {c}")


class Sweeper(threading.Thread):
    def __init__(self, mon, chain):
        super().__init__(daemon=True, name=f"sweep-{chain}")
        self.mon, self.chain = mon, chain

    def run(self):
        while not self.mon.stop_ev.wait(SWEEP_EVERY_S):
            try:
                self.sweep()
            except Exception:  # noqa: BLE001
                self.mon.err(f"sweep {self.chain}")

    def sweep(self):
        m, c = self.mon, self.chain
        if m.cursor[c] is None:
            return
        end = m.cursor[c] - int(SWEEP_LAG_S / BLOCK_S[c])
        start = (m.sweep_cursor[c] if m.sweep_cursor[c] is not None else end - int(SWEEP_EVERY_S / BLOCK_S[c])) + 1
        skipped = max(0, (end - int(SWEEP_MAX_S / BLOCK_S[c])) - start)
        start = max(start, end - int(SWEEP_MAX_S / BLOCK_S[c]))
        if start > end:
            return
        urls = list(POLL_URLS[c])
        random.shuffle(urls)
        t0 = time.time()
        for url in urls:
            host = url.split("/")[2]
            try:
                logs, b = [], start
                while b <= end:
                    e = min(end, b + MAX_RANGE[c] - 1)
                    logs += rpc_call(url, "eth_getLogs", [{"address": m.addresses(c), "topics": [m.topics0()],
                                                           "fromBlock": hex(b), "toBlock": hex(e)}], timeout=60)
                    b = e + 1
            except Exception as e:  # noqa: BLE001
                m.append_csv("sweeps.csv", SWEEP_HDR, [c, f"{t0:.3f}", scrub(host), 0, start, end, "", "", "", "", skipped,
                                                       scrub(f"{type(e).__name__}: {e}")[:160]])
                continue
            t_seen = time.time()
            wh, cx = m.split(c, logs)
            mw, mc = m.accept(c, start, end, wh, cx, t_seen, "sweep", host)
            m.sweep_cursor[c] = end
            m.counters[f"sweep missed wormhole {c}"] += mw
            m.counters[f"sweep missed ccip {c}"] += mc
            m.append_csv("sweeps.csv", SWEEP_HDR, [c, f"{t0:.3f}", scrub(host), 1, start, end, len(wh), len(cx), mw, mc,
                                                   skipped, ""])
            return


SWEEP_HDR = ["chain", "t_wall", "host", "ok", "from_block", "to_block", "n_wormhole", "n_ccip", "missed_wormhole",
             "missed_ccip", "blocks_skipped", "error"]


def run(minutes=None, force=False):
    stop_file = LIVE / "STOP"
    if stop_file.exists():
        print(f"{iso(time.time())} shadow/live/STOP is present; not starting (run_live.ps1 removes it)", flush=True)
        return
    m = Monitor(force=force)
    (LIVE / "monitor.pid").write_text(str(os.getpid()))
    threads = ([Poller(m, c) for c in CHAINS] + [Sweeper(m, c) for c in CHAINS]
               + [threading.Thread(target=m.worker, daemon=True, name=f"work-{i}") for i in range(WORKERS)]
               + [threading.Thread(target=m.scheduler, daemon=True, name="scheduler"),
                  threading.Thread(target=m.clock, daemon=True, name="clock")])
    for t in threads:
        t.start()
    print(f"{iso(time.time())} monitor started (pid {os.getpid()}, restart {m.restarts})", flush=True)
    t_end = time.time() + 60 * minutes if minutes else None
    last = 0.0
    try:
        while not stop_file.exists() and (t_end is None or time.time() < t_end):
            if time.time() - last >= SAVE_EVERY_S:
                m.save()
                last = time.time()
            time.sleep(1.0)
    except KeyboardInterrupt:
        pass
    finally:
        m.stop_ev.set()
        for t in threads:
            t.join(timeout=60)
        m.save()
        try:
            (LIVE / "monitor.pid").unlink()
        except OSError:
            pass
        print(f"{iso(time.time())} monitor stopped", flush=True)


# ------------------------------------------------------------------------------------------------ summary
def _q(xs, qs=(0.5, 0.9, 0.99, 1.0)):
    xs = sorted(x for x in xs if x is not None and not (isinstance(x, float) and math.isnan(x)))
    if not xs:
        return {}
    out = {}
    for q in qs:
        k = (len(xs) - 1) * q
        lo, hi = math.floor(k), math.ceil(k)
        out[str(q)] = round(xs[lo] + (xs[hi] - xs[lo]) * (k - lo), 2)
    return out


def _jsonl(path):
    if not path.exists():
        return []
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def _csv(path):
    if not path.exists():
        return []
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _stream_stats(es, off):
    """Alarms and delays over the releases `es` (public events). An alarm is raw when the first check did not
    confirm the release; the re-checks 60 s and 300 s later clear it if they confirm; it is confirmed otherwise.
    Delays are from the release block's time to this computer's clock corrected by the median offset `off`."""
    chk = [e for e in es if e.get("attempts")]
    live = [e for e in chk if e["mode"] == "live"]
    k_conf = [e.get("confirmed_at_attempt") for e in chk]
    k_out = [next((i for i, x in enumerate(e["attempts"]) if x["outcome"] == "confirmed" or x.get("outflow_rule")),
                  None) for e in chk]
    return {"releases": len(es), "by_mode": dict(collections.Counter(e["mode"] for e in es)),
            "decode_failed": sum(e["final"] == "decode_failed" for e in es),
            "first_check": dict(collections.Counter(e["attempts"][0]["outcome"] for e in chk)),
            "raw_alarms": sum(k != 0 for k in k_conf),
            "cleared_at_60s": sum(k == 1 for k in k_conf), "cleared_at_300s": sum(k == 2 for k in k_conf),
            "confirmed_alarms": sum(k is None or k >= 3 for k in k_conf),
            "standing_24h": sum(e["final"] == "standing" for e in chk),
            "raw_alarms_with_outflow_rule": sum(k != 0 for k in k_out),
            "confirmed_alarms_with_outflow_rule": sum(k is None or k >= 3 for k in k_out),
            "alarm_reasons": dict(collections.Counter(
                (e["attempts"][0]["reason"] or e["attempts"][0]["outcome"]) for e in chk if e.get("confirmed_at_attempt") != 0)),
            "confirmed_alarm_reasons": dict(collections.Counter(
                (e["attempts"][-1]["reason"] or e["attempts"][-1]["outcome"]) for e, k in zip(chk, k_conf) if k is None or k >= 3)),
            "source_final_at_first_check": dict(collections.Counter(str(e["attempts"][0]["src_final"]) for e in chk)),
            "live": {"releases": len(live),
                     "seen_after_release_s": _q([e["t_seen"] + off - e["release_ts"] for e in live]),
                     "first_verdict_after_release_s": _q([e["attempts"][0]["t1"] + off - e["release_ts"] for e in live]),
                     "confirmed_after_release_s": _q([e["t_confirmed"] + off - e["release_ts"] for e in live if e.get("t_confirmed")]),
                     "check_duration_s": _q([e["attempts"][0]["t1"] - e["attempts"][0]["t0"] for e in live]),
                     "deposit_age_at_release_s": _q([e["release_ts"] - e["src_ts"] for e in live if e.get("src_ts")]),
                     "held_by_gate_600s": sum(1 for e in live if not e.get("t_confirmed")
                                              or e["t_confirmed"] + off - e["release_ts"] > 600)}}


def _twin_stats(ts, off):
    """Forged twins: a copy citing a source message never issued, and copies with another amount or recipient."""
    return {"twins": len(ts),
            "no_deposit": dict(collections.Counter(t["no_deposit_outcome"] for t in ts)),
            "no_deposit_flagged": sum(t["no_deposit_outcome"] != "confirmed" for t in ts),
            "no_deposit_verdict_after_release_s": _q([t["t_seen"] + off - t["release_ts"] + (t["t_decoded"] - t["t_seen"])
                                                      + (t["no_deposit_t1"] - t["no_deposit_t0"])
                                                      for t in ts if t["mode"] == "live" and t.get("release_ts")]),
            "altered_amount_flagged": sum(t["altered_amount_flagged"] is True for t in ts),
            "altered_amount_tested": sum(t["altered_amount_flagged"] is not None for t in ts),
            "altered_recipient_flagged": sum(t["altered_recipient_flagged"] is True for t in ts),
            "altered_recipient_tested": sum(t["altered_recipient_flagged"] is not None for t in ts),
            # a copy altered from a release that itself disagrees with its source says nothing about the rule
            "copies_tested": len(ts) + sum((t[k] is not None and t["release_first_check"] == "confirmed")
                                           for t in ts for k in ("altered_amount_flagged", "altered_recipient_flagged")),
            "copies_flagged": sum(t["no_deposit_outcome"] != "confirmed" for t in ts)
            + sum((t[k] is True and t["release_first_check"] == "confirmed")
                  for t in ts for k in ("altered_amount_flagged", "altered_recipient_flagged"))}


def _monitor_down(polls):
    """Spans of more than 60 s with no successful poll on either chain: this computer was off or the monitor down."""
    ok = sorted(float(p["t_wall"]) for p in polls if p["ok"] == "1")
    return [(a, b) for a, b in zip(ok, ok[1:]) if b - a > 60]


def _distinct(ev, down):
    """Drops the second line of a release checked twice. `save` runs every 30 s, so a stop just after a release ended
    can leave it in pending.json with no attempts, and `load` checks it again. The two lines agree on the release and
    on t_seen, and a stop lies between them; two real releases can agree on these fields too, but with no stop between."""
    out, seen = [], {}
    for e in ev:
        if e.get("attempts"):
            key = tuple(e.get(k) for k in ("bridge", "direction", "release_block", "release_ts", "token", "amount", "t_seen"))
            p = seen.get(key)
            if p and any(p["attempts"][-1]["t1"] <= b and a <= e["attempts"][0]["t1"] for a, b in down):
                continue
            seen[key] = e
        out.append(e)
    return out


def _open_rows(ev, tw):
    """Live releases whose first check did not confirm them and whose re-checks are still running: they reach
    events.jsonl only when the checks end. Their twin line is public and starts right after the first check."""
    done = {(e["bridge"], e["direction"], e.get("release_ts"), e.get("t_seen")) for e in ev}
    return [{"bridge": t["bridge"], "direction": t["direction"], "mode": "live", "t_seen": t["t_seen"],
             "release_ts": t["release_ts"], "first_check": t["release_first_check"],
             "attempts": [{"t1": t["no_deposit_t0"], "outcome": t["release_first_check"]}]}
            for t in tw if t.get("release_first_check") != "confirmed"
            and (t["bridge"], t["direction"], t.get("release_ts"), t.get("t_seen")) not in done]


def _alarm_kinds(ev, open_rows):
    """Alarms by what the first check ran into. A read error is a first check that failed and a re-check that
    confirmed; a release paid in parts is one the outflow rule clears on every attempt. Open rows count as paid in
    parts when the private pending file shows the rule held on each of their attempts."""
    read = parts = other = 0
    for e in ev:
        a, k = e.get("attempts"), e.get("confirmed_at_attempt")
        if not a or k == 0:
            continue
        if k is not None and a[0]["outcome"] == "error":
            read += 1
        elif k is None and all(x.get("outflow_rule") for x in a):
            parts += 1
        else:
            other += 1
    held = {}
    try:
        records = json.loads((PRIV / "pending.json").read_text(encoding="utf-8")).get("records") or {}
        held = {r.get("t_seen"): r for r in records.values()}
    except Exception:  # noqa: BLE001
        pass
    for o in open_rows:
        a = (held.get(o["t_seen"]) or {}).get("attempts") or []
        if a and all(x.get("outflow_rule") for x in a):
            parts += 1
        else:
            other += 1
    return {"read_errors": read, "paid_in_parts": parts, "other": other}


def _caught_up(ev, down, off):
    """Delays of the live releases that measure the check and not this computer. A poll that follows a short gap is
    still marked live, so a release first seen more than 60 s after its block is set apart as read late. Decoding is
    one queue, so one seen before the first check of an earlier backfill release ended arrived during a catch-up; one
    seen before a stop had its first check after the restart. The rest are the releases the monitor saw once caught up.
    A verdict is the confirmation, or else the first attempt that did not fail."""
    busy, kept, behind, interrupted, late = 0.0, [], [], [], []
    for e in sorted((e for e in ev if e.get("attempts")), key=lambda e: e["t_seen"]):
        t1 = e["attempts"][0]["t1"]
        if e["mode"] == "backfill":
            busy = max(busy, t1)
        elif e["mode"] != "live":
            continue
        elif e["t_seen"] + off - e["release_ts"] > 60:
            late.append(e)
        elif any(e["t_seen"] <= b and a <= t1 for a, b in down):
            interrupted.append(e)
        elif e["t_seen"] <= busy:
            behind.append(e)
        else:
            kept.append(e)

    def delay(es):
        return [(e.get("t_confirmed") or next((x["t1"] for x in e["attempts"] if x.get("outcome") != "error"),
                                              e["attempts"][-1]["t1"])) + off - e["release_ts"] for e in es]
    return {"releases": len(kept), "verdict_after_release_s": _q(delay(kept)),
            "over_600s": sum(d > 600 for d in delay(kept)),
            "behind_catch_up": len(behind), "behind_catch_up_verdict_after_release_s": _q(delay(behind)),
            "behind_catch_up_over_600s": sum(d > 600 for d in delay(behind)),
            "interrupted_by_stop": len(interrupted), "interrupted_verdict_after_release_s": _q(delay(interrupted)),
            "read_late": len(late), "as_they_happened": len(kept) + len(behind) + len(interrupted)}


def summary():
    ev, tw = _jsonl(LIVE / "events.jsonl"), _jsonl(LIVE / "twins.jsonl")
    polls, sweeps, clock = _csv(LIVE / "polls.csv"), _csv(LIVE / "sweeps.csv"), _csv(LIVE / "clock.csv")
    lines = len(ev)
    ev = _distinct(ev, _monitor_down(polls))
    offs = [float(r["offset_s"]) for r in clock]
    off = sorted(offs)[len(offs) // 2] if offs else 0.0     # clock offset: true time = wall + off
    tw_all = [float(p["t_wall"]) for p in polls]
    res = {"generated_utc": iso(time.time()), "clock_offset_s_median": round(off, 3),
           "clock_offset_s_range": [round(min(offs), 3), round(max(offs), 3)] if offs else None,
           "window_utc": [iso(min(tw_all)), iso(max(tw_all))] if tw_all else None,
           "days": round((max(tw_all) - min(tw_all)) / 86400, 2) if tw_all else 0, "polls": {}, "streams": {},
           "twins": {}, "sweeps": {}}
    for c in CHAINS:
        ps = [p for p in polls if p["chain"] == c]
        ok = sorted(float(p["t_wall"]) for p in ps if p["ok"] == "1")
        gaps = [b - a for a, b in zip(ok, ok[1:])]
        age = [float(p["t_wall"]) + off - float(p["head_ts"]) for p in ps if p["ok"] == "1" and p["head_ts"]]
        res["polls"][c] = {"attempts": len(ps), "ok": len(ok), "failed": len(ps) - len(ok),
                           "gaps_over_60s": sum(g > 60 for g in gaps), "longest_gap_s": round(max(gaps), 1) if gaps else None,
                           "time_in_gaps_over_60s_s": round(sum(g for g in gaps if g > 60), 1),
                           "head_age_s": _q(age)}
        sw = [s for s in sweeps if s["chain"] == c]
        res["sweeps"][c] = {"sweeps": sum(s["ok"] == "1" for s in sw), "failed": sum(s["ok"] != "1" for s in sw),
                            "missed_by_polls": sum(int(s["missed_wormhole"] or 0) + int(s["missed_ccip"] or 0) for s in sw),
                            "blocks_skipped": sum(int(s["blocks_skipped"] or 0) for s in sw if s["ok"] == "1")}
    for key in sorted({(e["bridge"], e["direction"]) for e in ev}):
        name = f"{key[0]} {key[1]}"
        res["streams"][name] = _stream_stats([e for e in ev if (e["bridge"], e["direction"]) == key], off)
        res["twins"][name] = _twin_stats([t for t in tw if (t["bridge"], t["direction"]) == key], off)
    res["streams"]["all"] = _stream_stats(ev, off)
    res["twins"]["all"] = _twin_stats(tw, off)
    down = _monitor_down(polls)
    span = max(tw_all) - min(tw_all) if tw_all else 0
    res["monitor"] = {"down_periods": len(down), "down_s": round(sum(b - a for a, b in down), 1),
                      "longest_down_s": round(max((b - a for a, b in down), default=0), 1),
                      "up_share": round(1 - sum(b - a for a, b in down) / span, 3) if span else None}
    opened = _open_rows(ev, tw)
    res["lines_in_events"], res["duplicate_lines_dropped"], res["open_releases"] = lines, lines - len(ev), len(opened)
    res["live_caught_up"] = _caught_up(ev + opened, down, off)
    res["alarms"] = _alarm_kinds(ev, opened)
    try:
        st = json.loads((LIVE / "status.json").read_text(encoding="utf-8"))
        res["pending_checks_at_summary"] = st.get("pending_checks")
    except Exception:  # noqa: BLE001
        pass
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "shadow_live.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    L = ["# Live shadow run of the deposit-backing check (generated)", "",
         "Generated by `shadow/live_monitor.py summary`; see its docstring for the procedure.", "",
         f"Window {res['window_utc']}, {res['days']} days; clock offset median {res['clock_offset_s_median']} s "
         f"(range {res['clock_offset_s_range']}).", ""]
    for c, p in res["polls"].items():
        L.append(f"- polls {c}: {p['ok']:,} ok, {p['failed']:,} failed; gaps over 60 s: {p['gaps_over_60s']} "
                 f"(total {p['time_in_gaps_over_60s_s']} s, longest {p['longest_gap_s']} s); head age {p['head_age_s']}; "
                 f"sweeps {res['sweeps'][c]}")
    L.append(f"- monitor: {res['monitor']}")
    L.append(f"- lines in events.jsonl {lines}, duplicates dropped {res['duplicate_lines_dropped']}, releases with checks still open {res['open_releases']}")
    L.append(f"- live releases once caught up: {res['live_caught_up']}")
    L.append(f"- alarms by kind: {res['alarms']}")
    L.append("")
    for name, s in res["streams"].items():
        L += [f"## {name}", "", "```", json.dumps(s, indent=1), json.dumps(res["twins"][name], indent=1), "```", ""]
    (RESULTS / "shadow_live.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


def status():
    p = LIVE / "status.json"
    print(p.read_text(encoding="utf-8") if p.exists() else "no status yet")


if __name__ == "__main__":
    if "--log" in sys.argv:     # under pythonw (no console), print and tracebacks go to this file
        _log = pathlib.Path(sys.argv[sys.argv.index("--log") + 1])
        _log.parent.mkdir(parents=True, exist_ok=True)
        sys.stdout = sys.stderr = open(_log, "a", encoding="utf-8", buffering=1)
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    if cmd == "run":
        mins = None
        if "--minutes" in sys.argv:
            mins = float(sys.argv[sys.argv.index("--minutes") + 1])
        run(mins, force="--force" in sys.argv)
    elif cmd == "summary":
        summary()
    elif cmd == "status":
        status()
    else:
        raise SystemExit(__doc__)
