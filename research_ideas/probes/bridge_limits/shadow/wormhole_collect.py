"""Shadow-run dataset for the Wormhole token bridge (2026-10-16): every release of one EVM chain pair over the
42 days [2026-09-04T00:00:00Z, 2026-10-16T00:00:00Z), with its source message and the value check.

Steps (run in order; each caches what it fetches under raw/wormhole/, so reruns are cheap):
  targets     contract addresses from Wormhole's GitHub deployment lists and its documentation, confirmed on chain
  pairs       TransferRedeemed per emitter chain on each of the seven chains over the period's last week;
              the EVM pair with the most releases in both directions combined
  collect     releases on both destinations of the pair over the period (wormhole_decode.new_releases)
  traces      receivers of gas-coin releases from call traces (wormhole_decode.fill_native_recipients)
  sources     source messages and the value check of each (wormhole_decode.message_index / find_source)
  crosscheck  second-provider scans of the redeem events and of the source messages
  coverage    daily release counts against Wormholescan's operations API
  build       prices, data/wormhole_<pair>_releases.csv, data/wormhole_README.md
Run: python -I shadow/wormhole_collect.py <step> [<src> <dst>]   (one direction only, optional)
Outputs in data/ carry no addresses and no transaction hashes; raw/wormhole/ (not committed) keeps them.
"""
from __future__ import annotations

import collections
import datetime as dt
import json
import pathlib
import re
import sys
import time
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import wormhole_decode as wd  # noqa: E402

RAW = wd.RAW
CACHE = RAW / "cache"
DATA = HERE / "data"
T0 = int(dt.datetime(2026, 9, 4, tzinfo=dt.timezone.utc).timestamp())
T1 = int(dt.datetime(2026, 10, 16, tzinfo=dt.timezone.utc).timestamp())
WEEK = (T1 - 7 * 86400, T1)
CHAINS = list(wd.WH_CHAIN)
GITHUB = "https://raw.githubusercontent.com/wormhole-foundation/wormhole/main/"
GH_FILES = ["sdk/js/src/utils/consts.ts", "sdk/mainnet_consts.go"]
DOCS = "https://wormhole.com/docs/reference/contract-addresses/"
DOCS_NAME = {"ethereum": "Ethereum", "bsc": "Bsc", "polygon": "Polygon", "avalanche": "Avalanche",
             "arbitrum": "Arbitrum", "optimism": "Optimism", "base": "Base"}
GO_NAME = {"ethereum": "Ethereum", "bsc": "BSC", "polygon": "Polygon", "avalanche": "Avalanche",
           "arbitrum": "Arbitrum", "optimism": "Optimism", "base": "Base"}


def iso(ts):
    return dt.datetime.fromtimestamp(int(ts), dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def now_iso():
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def jdump(path, obj):
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=1, default=str), encoding="utf-8")
    tmp.replace(path)


def jload(path):
    return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))


def http_get(url, tries=6, timeout=60):
    last = None
    for k in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "bridge-limits-probe/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8")
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(2 * (k + 1))
    raise RuntimeError(f"{url}: {last}")


def client(chain, **kw):
    return wd.Client(chain, cache_dir=CACHE, **kw)


# ------------------------------------------------------------------------------------------------ targets
def parse_consts_ts(txt):
    """CONTRACTS.MAINNET of sdk/js/src/utils/consts.ts: {chain: (core, token_bridge)}."""
    a, b = txt.index("const MAINNET = {"), txt.index("const TESTNET = {")
    block = txt[a:b]
    out = {}
    for m in re.finditer(r'\n  (\w+): \{\s*core: (?:"([^"]*)"|undefined),\s*token_bridge: (?:"([^"]*)"|undefined)', block):
        out[m.group(1)] = ((m.group(2) or "").lower(), (m.group(3) or "").lower())
    return out


def parse_mainnet_go(txt):
    """knownTokenbridgeEmitters of sdk/mainnet_consts.go: {GoName: emitter32}."""
    a = txt.index("var knownTokenbridgeEmitters")
    b = txt.index("}", a)
    return {m.group(1): "0x" + m.group(2).lower() for m in
            re.finditer(r'vaa\.ChainID(\w+):\s*"([0-9a-fA-F]{64})"', txt[a:b])}


def parse_docs(html):
    """Mainnet tables of the documentation page: {'core': {name: addr}, 'token_bridge': {name: addr}}."""
    out = {}
    for sec, role in (("core-contracts", "core"), ("wrapped-token-transfers-wtt", "token_bridge")):
        i = html.index(f'id="{sec}"')
        j = html.index('<div class="tabbed-block">', i)
        k = html.index("</table>", j)
        out[role] = {re.sub(r"<[^>]+>", "", n).strip(): v.lower() for n, v in
                     re.findall(r"<tr><td>(.*?)</td><td><code>(.*?)</code></td></tr>", html[j:k])}
    return out


def targets():
    docs_dir = RAW / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    src = {"accessed_utc": now_iso(), "github": GITHUB, "github_files": GH_FILES, "docs": DOCS}
    try:
        meta = json.loads(http_get("https://api.github.com/repos/wormhole-foundation/wormhole/commits/main"))
        src["github_commit"] = meta.get("sha")
        src["github_commit_date"] = (meta.get("commit") or {}).get("committer", {}).get("date")
    except Exception as e:  # noqa: BLE001
        src["github_commit"] = f"unavailable: {e}"
    files = {}
    for f in GH_FILES:
        txt = http_get(GITHUB + f)
        (docs_dir / f.replace("/", "__")).write_text(txt, encoding="utf-8")
        files[f] = txt
    html = http_get(DOCS)
    (docs_dir / "contract_addresses.html").write_text(html, encoding="utf-8")
    ts_map = parse_consts_ts(files["sdk/js/src/utils/consts.ts"])
    go_map = parse_mainnet_go(files["sdk/mainnet_consts.go"])
    docs = parse_docs(html)
    T = {"built_utc": now_iso(), "sources": src, "chains": {}, "source_agreement": {}}
    for ch in CHAINS:
        core, tb = ts_map[ch]
        em = go_map[GO_NAME[ch]]
        dcore = docs["core"].get(DOCS_NAME[ch])
        dtb = docs["token_bridge"].get(DOCS_NAME[ch])
        agree = {"consts_ts_vs_docs_core": dcore == core, "consts_ts_vs_docs_token_bridge": dtb == tb,
                 "emitter_go_vs_token_bridge": em == "0x" + "0" * 24 + tb[2:]}
        T["source_agreement"][ch] = agree
        T["chains"][ch] = {"wormhole_chain_id": wd.WH_CHAIN[ch], "evm_chain_id": wd.EVM_CHAIN[ch], "core": core,
                           "token_bridge": tb, "emitter32": em, "docs_name": DOCS_NAME[ch]}
        print(ch, agree, flush=True)
    # on-chain confirmation
    for ch in CHAINS:
        c = T["chains"][ch]
        r = client(ch)
        conf = {}
        conf["evm_chain_id"] = int(r.call("eth_chainId", []), 16)
        conf["core_code_bytes"] = (len(r.call("eth_getCode", [c["core"], "latest"])) - 2) // 2
        conf["token_bridge_code_bytes"] = (len(r.call("eth_getCode", [c["token_bridge"], "latest"])) - 2) // 2
        conf["core_chainId"] = int(wd._call_word(r, c["core"], wd.SEL["chainId"]) or "0x0", 16)
        conf["token_bridge_chainId"] = int(wd._call_word(r, c["token_bridge"], wd.SEL["chainId"]) or "0x0", 16)
        conf["token_bridge_wormhole_is_core"] = wd.addr_from_word(wd._call_word(r, c["token_bridge"], wd.SEL["wormhole"]) or "0x0") == c["core"]
        weth = wd._call_word(r, c["token_bridge"], wd.SEL["WETH"])
        c["weth"] = wd.addr_from_word(weth) if weth else wd.ZERO
        reg = {}
        for o in CHAINS:
            if o == ch:
                continue
            w = wd._call_word(r, c["token_bridge"], wd.SEL["bridgeContracts"] + format(wd.WH_CHAIN[o], "064x"))
            reg[o] = (w or "").lower() == T["chains"][o]["emitter32"]
        conf["registered_emitters_match"] = reg
        ns = wd._call_word(r, c["core"], wd.SEL["nextSequence"] + "0" * 24 + c["token_bridge"][2:])
        conf["token_bridge_next_sequence"] = int(ns, 16) if ns else None
        conf["head_block"] = r.head()
        conf["ok"] = (conf["evm_chain_id"] == c["evm_chain_id"] and conf["core_code_bytes"] > 0 and
                      conf["token_bridge_code_bytes"] > 0 and conf["core_chainId"] == c["wormhole_chain_id"] and
                      conf["token_bridge_chainId"] == c["wormhole_chain_id"] and conf["token_bridge_wormhole_is_core"]
                      and all(reg.values()) and c["weth"] != wd.ZERO)
        c["confirm"] = conf
        print(ch, json.dumps(conf), flush=True)
    old = wd.load_targets() if wd.TARGETS_PATH.exists() else {}
    for k in ("pair", "pair_choice"):
        if k in old:
            T[k] = old[k]
    jdump(wd.TARGETS_PATH, T)


# ------------------------------------------------------------------------------------------------ pairs
def period_blocks(r, t0, t1):
    """[first block with ts >= t0, last block with ts < t1] on the client's chain."""
    b0 = r.block_at(t0)
    b1 = r.block_at(t1) - 1
    return b0, b1


def pairs():
    T = wd.load_targets()
    out = {"week_utc": [iso(WEEK[0]), iso(WEEK[1])], "chains": {}}
    for ch in CHAINS:
        c = T["chains"][ch]
        r = client(ch)
        b0, b1 = period_blocks(r, *WEEK)
        red = r.logs(c["token_bridge"], [wd.REDEEMED], b0, b1)
        by = collections.Counter()
        unreg = collections.Counter()
        for lg in red:
            e = wd.hx(lg["topics"][1])
            by[e] += 1
            name = wd.WH_NAME.get(e)
            if name and lg["topics"][2].lower() != T["chains"][name]["emitter32"]:
                unreg[e] += 1
        msgs = r.logs(c["core"], [wd.LMP, wd.addr_topic(c["token_bridge"])], b0, b1)
        to_by = collections.Counter()
        for lg in msgs:
            p = wd.decode_transfer(wd.decode_lmp(lg)["payload"])
            to_by[p["to_chain"] if p else "other"] += 1
        out["chains"][ch] = {"blocks": [b0, b1], "block_times": [iso(r.block_ts(b0)), iso(r.block_ts(b1))],
                             "redeemed_total": len(red), "redeemed_by_emitter_chain": {str(k): v for k, v in sorted(by.items())},
                             "redeemed_emitter_not_registered": {str(k): v for k, v in unreg.items()},
                             "messages_total": len(msgs), "messages_by_target_chain": {str(k): v for k, v in sorted(to_by.items(), key=str)},
                             "rpc_stats": dict(r.stats)}
        print(ch, json.dumps(out["chains"][ch]), flush=True)
    score = {}
    for i, a in enumerate(CHAINS):
        for b in CHAINS[i + 1:]:
            ab = out["chains"][b]["redeemed_by_emitter_chain"].get(str(wd.WH_CHAIN[a]), 0)
            ba = out["chains"][a]["redeemed_by_emitter_chain"].get(str(wd.WH_CHAIN[b]), 0)
            score[f"{a}<->{b}"] = {f"{a}->{b}": ab, f"{b}->{a}": ba, "total": ab + ba}
    ranked = sorted(score.items(), key=lambda kv: -kv[1]["total"])
    out["pair_scores"] = dict(ranked)
    best = ranked[0][0].split("<->")
    out["chosen"] = best
    jdump(RAW / "pair_counts.json", out)
    T["pair"] = best
    T["pair_choice"] = {"week_utc": out["week_utc"], "score": ranked[0][1], "runner_up": dict(ranked[1:4])}
    jdump(wd.TARGETS_PATH, T)
    for k, v in ranked[:8]:
        print(k, v)


# ------------------------------------------------------------------------------------------------ collect
META_PATH = RAW / "token_meta.json"
LOOKBACK = 3 * 86400      # source messages are scanned in bulk from T0 - LOOKBACK; older ones are located singly


def load_meta():
    """Token facts cache: one file per chain (keys start with the chain name), merged."""
    meta = jload(META_PATH) if META_PATH.exists() else {}
    for p in RAW.glob("token_meta_*.json"):
        meta.update(jload(p))
    return meta


def save_meta(meta, chains):
    for ch in chains:
        jdump(RAW / f"token_meta_{ch}.json", {k: v for k, v in meta.items() if k.startswith(ch + ":")})


def directions(T=None):
    """Both directions of the pair, or the one named on the command line (`<step> <src> <dst>`)."""
    a, b = wd.pair_of(T)
    if len(sys.argv) == 4:
        assert {sys.argv[2], sys.argv[3]} == {a, b}
        return [(sys.argv[2], sys.argv[3])]
    return [(a, b), (b, a)]


def day_blocks(r, chain):
    """Block ranges of the 42 UTC days of the period on `chain` (cached in raw/wormhole/period.json)."""
    p = RAW / "period.json"
    per = jload(p) if p.exists() else {}
    if chain not in per:
        last = r.block_at(T1)
        first = r.block_at(T0, hi=last)
        nxt = r.block_at(T0 + 86400, lo=first - 1, hi=last)
        edges = [first, nxt]
        for d in range(2, 42):      # seeded with the previous day's block count
            edges.append(r.block_at(T0 + d * 86400, lo=edges[-1] - 1, hi=last, guess=2 * edges[-1] - edges[-2]))
        edges.append(last)
        print(chain, "day edges", edges[0], edges[-1], dict(r.stats), flush=True)
        per[chain] = {"days": [[edges[d], edges[d + 1] - 1] for d in range(42)],
                      "blocks": [edges[0], edges[-1] - 1],
                      "edge_times": [iso(r.block_ts(edges[0] - 1)), iso(r.block_ts(edges[0])),
                                     iso(r.block_ts(edges[-1] - 1)), iso(r.block_ts(edges[-1]))]}
        jdump(p, per)
    return per[chain]


def rel_path(src, dst):
    return RAW / f"releases_{src}_to_{dst}.json"


def collect():
    T = wd.load_targets()
    meta = load_meta()
    for src, dst in directions(T):
        r = client(dst)
        per = day_blocks(r, dst)
        out = []
        for d, (b0, b1) in enumerate(per["days"]):
            rels = wd.new_releases(r, dst, b0, b1, src_chain=src, T=T, meta=meta, trace=False)
            for x in rels:
                if not (T0 + d * 86400 <= x["ts"] < T0 + (d + 1) * 86400):
                    raise RuntimeError(f"release time outside its day: {x['ts']} day {d}")
            out += rels
            print(src, "->", dst, iso(T0 + d * 86400)[:10], len(rels), dict(r.stats), flush=True)
            save_meta(meta, [dst])
        jdump(rel_path(src, dst), {"src": src, "dst": dst, "blocks": per["blocks"], "releases": out,
                                   "rpc_stats": dict(r.stats), "built_utc": now_iso()})
        print(src, "->", dst, "releases", len(out), collections.Counter(x["kind"] for x in out), flush=True)


def traces():
    """Receivers of gas-coin releases (unlock_native) from call traces (wormhole_decode.fill_native_recipients)."""
    T = wd.load_targets()
    for src, dst in directions(T):
        p = rel_path(src, dst)
        R = jload(p)
        r = client(dst)
        nat = [x for x in R["releases"] if x["kind"] == "unlock_native"]
        for i in range(0, len(nat), 25):
            wd.fill_native_recipients(r, dst, nat[i:i + 25], T)
            print(src, "->", dst, "traced", min(i + 25, len(nat)), "/", len(nat),
                  "with recipient", sum(1 for x in nat[:i + 25] if x.get("recipient")), dict(r.stats), flush=True)
        R["traced_utc"] = now_iso()
        jdump(p, R)


# ------------------------------------------------------------------------------------------------ sources
def src_path(src, dst):
    return RAW / f"sources_{src}_to_{dst}.json"


def source_scan(r, src, T):
    """Bulk index of the source token bridge's messages over [T0 - LOOKBACK, T1) and its sequence check."""
    b0 = r.block_at(T0 - LOOKBACK)
    b1 = day_blocks(r, src)["blocks"][1]
    idx = wd.message_index(r, src, b0, b1, T)
    seqs = sorted(idx)
    missing = sorted(set(range(seqs[0], seqs[-1] + 1)) - set(seqs)) if seqs else []
    # the first message after the range must carry the next sequence, the last before it the previous one
    return idx, {"blocks": [b0, b1], "block_times": [iso(r.block_ts(b0)), iso(r.block_ts(b1))],
                 "messages": len(seqs), "first_sequence": seqs[0] if seqs else None,
                 "last_sequence": seqs[-1] if seqs else None, "missing_sequences": missing[:50],
                 "n_missing": len(missing)}


def sources():
    T = wd.load_targets()
    meta = load_meta()
    for src, dst in directions(T):
        rels = jload(rel_path(src, dst))["releases"]
        r = client(src)
        idx, scan = source_scan(r, src, T)
        print(src, "scan", json.dumps(scan), flush=True)
        # boundary check of the scan: the core's nextSequence(token bridge) before and after the range
        c = T["chains"][src]
        nb = wd._seq_at(r, c["core"], c["token_bridge"], scan["blocks"][0] - 1)
        na = wd._seq_at(r, c["core"], c["token_bridge"], scan["blocks"][1])
        scan["next_sequence_before_range"], scan["next_sequence_at_range_end"] = nb, na
        scan["range_complete"] = (nb == scan["first_sequence"] and na == scan["last_sequence"] + 1
                                  and scan["n_missing"] == 0)
        txs = sorted({idx[x["sequence"]]["transactionHash"].lower() for x in rels if x["sequence"] in idx})
        for i in range(0, len(txs), 200):
            r.batch("eth_getTransactionReceipt", [[h] for h in txs[i:i + 200]])
            print(src, "receipts", min(i + 200, len(txs)), "/", len(txs), flush=True)
        r.block_ts_many([wd.hx(idx[x["sequence"]]["blockNumber"]) for x in rels if x["sequence"] in idx])
        res = []
        for k, x in enumerate(rels):
            s = wd.find_source(r, src, x, T=T, meta=meta, index=idx)
            res.append(s)
            if k % 500 == 0:
                print(src, "->", dst, "sources", k, "/", len(rels), dict(r.stats), flush=True)
                save_meta(meta, [src])
        save_meta(meta, [src])
        jdump(src_path(src, dst), {"src": src, "dst": dst, "scan": scan, "sources": res, "rpc_stats": dict(r.stats),
                                   "built_utc": now_iso()})
        n_found = sum(1 for s in res if s)
        print(src, "->", dst, "found", n_found, "/", len(res),
              collections.Counter((s or {}).get("value_moved", "na") for s in res),
              collections.Counter((s or {}).get("amount_agrees", "na") for s in res), flush=True)


# ------------------------------------------------------------------------------------------------ crosscheck
# BSC's second log provider answers 5,000-block ranges at a few seconds each, so on BSC the second scan covers
# every sixth day of the period (the source scan is complete by its sequence and boundary checks anyway)
CROSS_DAYS = {"bsc": [0, 6, 12, 18, 24, 30, 36, 41]}


def crosscheck():
    """Second provider for (a) the redeem events of each direction and (b) the source messages."""
    T = wd.load_targets()
    out = {}
    for src, dst in directions(T):
        cd, cs = T["chains"][dst], T["chains"][src]
        rels = jload(rel_path(src, dst))["releases"]
        scan = jload(src_path(src, dst))["scan"]
        r = client(dst)
        per = day_blocks(r, dst)
        topics = [wd.REDEEMED, wd.topic_u(cs["wormhole_chain_id"]), cs["emitter32"]]
        days = CROSS_DAYS.get(dst, list(range(42)))
        mine, theirs = set(), set()
        for d in days:
            b0, b1 = per["days"][d]
            alt = r.logs(cd["token_bridge"], topics, b0, b1, endpoints=wd.ALT_LOGS[dst])
            theirs |= {(lg["transactionHash"].lower(), wd.hx(lg["logIndex"])) for lg in alt}
            mine |= {(x["tx"], x["log_index"]) for x in rels if b0 <= x["block"] <= b1}
            print(src, "->", dst, "crosscheck day", d, len(mine), len(theirs), dict(r.stats), flush=True)
        res = {"days_checked": len(days), "redeem_events_primary": len(mine), "redeem_events_second_provider": len(theirs),
               "only_primary": len(mine - theirs), "only_second": len(theirs - mine),
               "second_provider_dst": [u for u, _ in wd.ALT_LOGS[dst]]}
        if src not in CROSS_DAYS:
            rs = client(src)
            alt_m = rs.logs(cs["core"], [wd.LMP, wd.addr_topic(cs["token_bridge"])], scan["blocks"][0], scan["blocks"][1],
                            endpoints=wd.ALT_LOGS[src])
            alt_seqs = {wd.decode_lmp(lg)["sequence"] for lg in alt_m if lg["address"].lower() == cs["core"]}
            prim = set(range(scan["first_sequence"], scan["last_sequence"] + 1))
            res.update({"source_messages_primary": scan["messages"], "source_messages_second_provider": len(alt_seqs),
                        "source_only_primary": len(prim - alt_seqs), "source_only_second": len(alt_seqs - prim),
                        "second_provider_src": [u for u, _ in wd.ALT_LOGS[src]]})
        out[f"{src}->{dst}"] = res
        print(json.dumps(res), flush=True)
    jdump(RAW / "crosscheck.json", out)


# ------------------------------------------------------------------------------------------------ coverage
OPS = "https://api.wormholescan.io/api/v1/operations"


def ops_page(params, cache_dir):
    cache_dir.mkdir(parents=True, exist_ok=True)
    name = "_".join(f"{k}-{v}" for k, v in sorted(params.items())).replace(":", "").replace("/", "")
    p = cache_dir / f"{name}.json"
    if p.exists():
        return jload(p)
    url = OPS + "?" + "&".join(f"{k}={v}" for k, v in params.items())
    last = None
    for k in range(8):
        try:
            j = json.loads(http_get(url, tries=1, timeout=120))
            jdump(p, {"url": url, "accessed_utc": now_iso(), "response": j})
            time.sleep(1.0)
            return jload(p)
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(5 * (k + 1))
    raise RuntimeError(f"{url}: {last}")


def op_by_id(chain_id, emitter_hex, seq, cache_dir):
    cache_dir.mkdir(parents=True, exist_ok=True)
    p = cache_dir / f"op_{chain_id}_{seq}.json"
    if p.exists():
        return jload(p)["response"]
    url = f"{OPS}/{chain_id}/{emitter_hex}/{seq}"
    try:
        j = json.loads(http_get(url, tries=4, timeout=120))
    except Exception as e:  # noqa: BLE001
        j = {"error": str(e)}
    jdump(p, {"url": url, "accessed_utc": now_iso(), "response": j})
    time.sleep(0.5)
    return j


def api_ts(s):
    if not s:
        return None
    s = s.replace("Z", "+00:00")
    if "." in s:
        a, b = s.split(".", 1)
        frac = re.match(r"\d+", b).group(0)
        s = a + b[len(frac):]
    return int(dt.datetime.fromisoformat(s).timestamp())


COVER_PRE = 7 * 86400     # API operations are requested by source day from T0 - 7 d to T1 + 1 d


def api_ops(cs, cd, cache_dir):
    """Token bridge operations of the API by source day (the API's from/to filter the source time), one
    request series per UTC day so that no window needs more than a few pages."""
    ops, per_day = {}, {}
    em_hex = cs["emitter32"][2:]
    for d0 in range(T0 - COVER_PRE, T1 + 86400, 86400):
        page, n_day = 0, 0
        while True:
            j = ops_page({"sourceChain": cs["wormhole_chain_id"], "targetChain": cd["wormhole_chain_id"],
                          "from": iso(d0), "to": iso(d0 + 86400), "pageSize": 100, "page": page}, cache_dir)["response"]
            got = j.get("operations") or []
            for o in got:
                if (o.get("emitterAddress") or {}).get("hex", "").lower() == em_hex and o.get("emitterChain") == cs["wormhole_chain_id"]:
                    ops[int(o["sequence"])] = o
                    n_day += 1
            if len(got) < 100:
                break
            page += 1
        per_day[iso(d0)[:10]] = n_day
    return ops, per_day


def coverage():
    """Daily release counts against Wormholescan's operations API, and the reasons for each difference."""
    T = wd.load_targets()
    out = {}
    for src, dst in directions(T):
        cs, cd = T["chains"][src], T["chains"][dst]
        em_hex = cs["emitter32"][2:]
        rels = jload(rel_path(src, dst))["releases"]
        srcs = jload(src_path(src, dst))["sources"]
        cache_dir = RAW / "api" / f"{src}_to_{dst}"
        ops, per_day = api_ops(cs, cd, cache_dir)
        print(src, "->", dst, "api operations", len(ops), flush=True)
        for x in rels:      # releases of messages older than the request window: ask by id
            if x["sequence"] not in ops:
                o = op_by_id(cs["wormhole_chain_id"], em_hex, x["sequence"], cache_dir)
                if isinstance(o, dict) and o.get("id"):
                    o["_by_id"] = True
                    ops[x["sequence"]] = o
        # redemptions on the destination outside the period, to place the API's operations without a target
        r = client(dst)
        per = day_blocks(r, dst)
        topics = [wd.REDEEMED, wd.topic_u(cs["wormhole_chain_id"]), cs["emitter32"]]
        pre_b0 = r.block_at(T0 - COVER_PRE)
        pre = r.logs(cd["token_bridge"], topics, pre_b0, per["blocks"][0] - 1)
        post_b1 = r.final_block()
        post = r.logs(cd["token_bridge"], topics, per["blocks"][1] + 1, post_b1)
        pre_seq = {wd.hx(lg["topics"][3]) for lg in pre}
        post_seq = {wd.hx(lg["topics"][3]) for lg in post}
        post_end_utc = iso(r.block_ts(post_b1))
        mine = {x["sequence"]: x for x in rels}
        api_rel, api_tc_out, api_no_tc = {}, {}, {}
        for s, o in ops.items():
            tc = o.get("targetChain") or {}
            t = api_ts(tc.get("timestamp"))
            if t is None:
                api_no_tc[s] = o
            elif T0 <= t < T1 and tc.get("chainId") == cd["wormhole_chain_id"]:
                api_rel[s] = {"t": t, "status": tc.get("status"),
                              "tx": ((tc.get("transaction") or {}).get("txHash") or "").lower(), "by_id": bool(o.get("_by_id"))}
            else:
                api_tc_out[s] = t
        days = [iso(T0 + d * 86400)[:10] for d in range(42)]
        dm = collections.Counter(iso(x["ts"])[:10] for x in rels)
        da = collections.Counter(iso(v["t"])[:10] for v in api_rel.values())
        both = sorted(set(mine) & set(api_rel))
        only_mine = sorted(set(mine) - set(api_rel))
        only_api = sorted(set(api_rel) - set(mine))
        why_mine = collections.Counter()
        for s in only_mine:
            if s not in ops:
                why_mine["operation not in the API"] += 1
            elif s in api_no_tc:
                why_mine["API has the operation but no destination record"] += 1
            else:
                why_mine["API records the destination outside the period"] += 1
        # source-day share of the API's operations that carry a destination record
        tc_share = collections.defaultdict(lambda: [0, 0])
        for s, o in ops.items():
            st = api_ts((o.get("sourceChain") or {}).get("timestamp"))
            if st is None:
                continue
            k = iso(st)[:10]
            tc_share[k][0] += 1
            tc_share[k][1] += int(bool(o.get("targetChain")))
        # operations whose source message lies in the period and which the API shows without a destination record
        no_tc_in = [s for s, o in api_no_tc.items()
                    if T0 <= (api_ts((o.get("sourceChain") or {}).get("timestamp")) or 0) < T1]
        place = collections.Counter()
        for s in no_tc_in:
            if s in mine:
                place["released in the period (in this dataset)"] += 1
            elif s in post_seq:
                place["released after the period"] += 1
            elif s in pre_seq:
                place["released before the period"] += 1
            else:
                place[f"not released by {post_end_utc}"] += 1
        # API operations sourced in the period that this dataset does not release in the period
        src_in = [s for s, o in ops.items() if T0 <= (api_ts((o.get("sourceChain") or {}).get("timestamp")) or 0) < T1]
        not_mine = collections.Counter()
        for s in src_in:
            if s in mine:
                continue
            not_mine["released after the period" if s in post_seq else "released before the period" if s in pre_seq
                     else f"not released by {post_end_utc}"] += 1
        # source-side reconciliation: every message of the source token bridge to this destination published in
        # the period (from the bulk source scan), placed by when the destination released it
        scan = jload(src_path(src, dst))["scan"]
        rsrc = client(src)
        idx = wd.message_index(rsrc, src, scan["blocks"][0], scan["blocks"][1], T)
        msg_ts = rsrc.block_ts_many([wd.hx(lg["blockNumber"]) for lg in idx.values()])
        recon = collections.Counter()
        for s, lg in idx.items():
            p = wd.decode_transfer(wd.decode_lmp(lg)["payload"])
            if not p or p["to_chain"] != cd["wormhole_chain_id"]:
                continue
            t = msg_ts[wd.hx(lg["blockNumber"])]
            when = "published in the period" if T0 <= t < T1 else "published in the 3 days before the period"
            where = ("released in the period" if s in mine else "released after the period" if s in post_seq else
                     "released before the period" if s in pre_seq else f"not released by {post_end_utc}")
            recon[f"{when}: {where}"] += 1
        old_rel = sum(1 for x in rels if x["sequence"] < (scan["first_sequence"] or 0))
        tx_mismatch = sum(1 for s in both if api_rel[s]["tx"] and api_rel[s]["tx"] != mine[s]["tx"])
        tdiff = [api_rel[s]["t"] - mine[s]["ts"] for s in both]
        # the API's own source record against the source chain (time and source transaction)
        src_by_seq = {x["sequence"]: s for x, s in zip(rels, srcs) if s}
        src_tx_diff = sum(1 for s in mine if s in ops and s in src_by_seq and
                          ((ops[s].get("sourceChain") or {}).get("transaction") or {}).get("txHash", "").lower() != src_by_seq[s]["tx"])
        out[f"{src}->{dst}"] = {
            "query": {"sourceChain": cs["wormhole_chain_id"], "targetChain": cd["wormhole_chain_id"],
                      "source_days_utc": [iso(T0 - COVER_PRE), iso(T1 + 86400)], "by_id_requests": sum(1 for o in ops.values() if o.get("_by_id"))},
            "api_operations_token_bridge": len(ops), "api_with_destination_record_in_period": len(api_rel),
            "api_without_destination_record": len(api_no_tc), "mine": len(mine), "both": len(both),
            "only_mine": len(only_mine), "only_mine_why": dict(why_mine), "only_api": len(only_api),
            "only_api_detail": [{"api_target_utc": iso(api_rel[s]["t"]), "status": api_rel[s]["status"],
                                 "released_after_period": s in post_seq, "released_before_period": s in pre_seq} for s in only_api][:50],
            "redeem_tx_differs": tx_mismatch, "source_tx_differs": src_tx_diff,
            "api_minus_chain_time_s": {"min": min(tdiff) if tdiff else None, "max": max(tdiff) if tdiff else None,
                                       "n_nonzero": sum(1 for x in tdiff if x)},
            "source_reconciliation": dict(sorted(recon.items())), "releases_of_messages_older_than_scan": old_rel,
            "api_sourced_in_period": len(src_in), "api_sourced_in_period_not_released_in_period": dict(not_mine),
            "api_no_destination_record_sourced_in_period": dict(place),
            "destination_record_share_by_source_day": {k: [v[1], v[0]] for k, v in sorted(tc_share.items())},
            "daily": [{"day": d, "mine": dm.get(d, 0), "api": da.get(d, 0)} for d in days],
            "days_differing": sum(1 for d in days if dm.get(d, 0) != da.get(d, 0)),
            "redemption_scan_outside_period": {"before_from_utc": iso(T0 - COVER_PRE), "after_to_utc": post_end_utc,
                                               "before": len(pre), "after": len(post)}}
        print(json.dumps({k: v for k, v in out[f"{src}->{dst}"].items()
                          if k not in ("daily", "destination_record_share_by_source_day")}, default=str)[:3000], flush=True)
    # other routes on two source days: is the missing destination record specific to this pair?
    other = {}
    for s_id, t_id in OTHER_ROUTES:
        for day in OTHER_DAYS:
            d0 = int(dt.datetime.fromisoformat(day + "T00:00:00+00:00").timestamp())
            n, w, page = 0, 0, 0
            while True:
                j = ops_page({"sourceChain": s_id, "targetChain": t_id, "from": iso(d0), "to": iso(d0 + 86400),
                              "pageSize": 100, "page": page}, RAW / "api" / "other_routes")["response"]
                got = j.get("operations") or []
                for o in got:
                    if "PORTAL_TOKEN_BRIDGE" in (((o.get("content") or {}).get("standarizedProperties") or {}).get("appIds") or []):
                        n += 1
                        w += int(bool(o.get("targetChain")))
                if len(got) < 100:
                    break
                page += 1
            other[f"{s_id}->{t_id} {day}"] = [w, n]
    out["other_routes_token_bridge_with_destination_record"] = other
    print(json.dumps(other), flush=True)
    jdump(RAW / "coverage.json", out)


# Wormhole chain ids: 1 Solana, 2 Ethereum, 4 BSC, 23 Arbitrum, 30 Base
OTHER_ROUTES = [(1, 2), (30, 2), (23, 2), (4, 2), (2, 4), (4, 30), (2, 30), (1, 30)]
OTHER_DAYS = ["2026-09-15", "2026-10-14"]
CHAIN_NAME = {1: "Solana", 2: "Ethereum", 4: "BSC", 23: "Arbitrum", 30: "Base"}


# ------------------------------------------------------------------------------------------------ build
class Prices:
    """DefiLlama coins API /chart, as data/legit/build_e59.py's Prices: the hourly series (nearest point within
    2 h of the release), else the daily series (within 36 h), else unpriced. Cached under raw/wormhole/px."""

    def __init__(self, t0, t1):
        self.t0, self.t1 = t0, t1
        self.dir = RAW / "px"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.series = {}

    def _cached(self, name, url):
        p = self.dir / name
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
        j = json.loads(http_get(url))
        p.write_text(json.dumps(j), encoding="utf-8")
        time.sleep(0.3)
        return j

    def load(self, cid):
        if cid in self.series:
            return self.series[cid]
        safe = re.sub(r"[^A-Za-z0-9]", "_", cid)
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
                         f"https://coins.llama.fi/chart/{cid}?start={self.t0 - 2 * 86400}&span=50&period=1d")
        daily = [(q["timestamp"], q["price"]) for q in (j.get("coins", {}).get(cid, {}).get("prices") or [])]
        self.series[cid] = (sorted(set(hourly)), sorted(set(daily)))
        return self.series[cid]

    @staticmethod
    def near(series, ts, tol):
        import bisect
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
            return p, "1h"
        p = self.near(d, ts, 36 * 3600)
        if p is not None:
            return p, "1d"
        return None, ""


def coin_ids(x, T):
    """DefiLlama coin ids for a release, best first: the token released on the destination for an unlock, the
    origin token (on its own chain) for a mint, the other one as fallback."""
    dst_ll = wd.LLAMA[T["chains"][x["dst_chain"]]["wormhole_chain_id"]]
    oc, oa = x.get("origin_chain"), x.get("origin_address")
    origin = None
    if oc in wd.LLAMA and oa:
        if oc == 1:
            origin = "solana:" + wd.b58(bytes.fromhex(oa[2:]))
        elif wd.word_is_address(oa):
            origin = f"{wd.LLAMA[oc]}:{wd.addr_from_word(oa)}"
    here = f"{dst_ll}:{x['token']}" if x.get("token") else None
    order = [origin, here] if x["kind"] == "mint" else [here, origin]
    return [c for c in dict.fromkeys(order) if c]


def quantiles(xs, qs=(0.0, 0.01, 0.05, 0.25, 0.5, 0.75, 0.95, 0.99, 1.0)):
    if not xs:
        return {}
    xs = sorted(xs)
    out = {}
    for q in qs:
        k = (len(xs) - 1) * q
        lo, hi = int(k), min(len(xs) - 1, int(k) + 1)
        out[str(q)] = xs[lo] + (xs[hi] - xs[lo]) * (k - lo)
    return out


def build():
    import csv
    from decimal import Decimal
    T = wd.load_targets()
    a, b = wd.pair_of(T)
    pair_tag = f"{a}_{b}"
    prices = Prices(T0, T1)
    rows, summ = [], {"pair": [a, b], "period_utc": [iso(T0), iso(T1)], "directions": {}}
    for src, dst in directions(T):
        R = jload(rel_path(src, dst))
        S = jload(src_path(src, dst))
        rels, srcs = R["releases"], S["sources"]
        assert len(rels) == len(srcs)
        d = {"releases": len(rels), "kinds": collections.Counter(), "payload_ids": collections.Counter(),
             "matched": 0, "value_moved": collections.Counter(), "value_detail": collections.Counter(),
             "amount_agrees": 0, "usd": 0.0, "unpriced": 0, "price_res": collections.Counter(), "fee_releases": 0,
             "vaa_found": 0, "vaa_payload_equal": collections.Counter(), "vaa_ts_equal": collections.Counter(),
             "older_than_period": 0, "located_singly": 0, "agree_parts": collections.Counter(), "problems": [],
             "tokens_usd": collections.Counter(), "tokens_n": collections.Counter(), "notes": collections.Counter()}
        ages = []
        idx_lo = S["scan"]["first_sequence"]
        for x, s in zip(rels, srcs):
            notes = list(x.get("notes") or [])
            d["kinds"][x["kind"]] += 1
            if x.get("vaa"):
                d["vaa_found"] += 1
            amount = wd.units(x["amount_raw"], x["decimals"]) if x["kind"] != "none" else "0"
            usd, res = None, ""
            for cid in coin_ids(x, T):
                p, res = prices.price(cid, x["ts"])
                if p is not None:
                    usd = float(Decimal(amount) * Decimal(str(p)))
                    break
            if usd is None:
                d["unpriced"] += 1
                notes.append("no price")
            else:
                d["usd"] += usd
                d["price_res"][res] += 1
                d["tokens_usd"][x["symbol"]] += usd
            d["tokens_n"][x["symbol"]] += 1
            if s:
                p = s.get("payload") or {}
                d["matched"] += 1
                d["payload_ids"][p.get("payload_id")] += 1
                d["value_moved"][s["value_moved"]] += 1
                d["value_detail"][s["value_detail"]] += 1
                d["vaa_payload_equal"][str(s.get("vaa_payload_equal"))] += 1
                d["vaa_ts_equal"][str(s.get("vaa_ts_equal"))] += 1
                if s["amount_agrees"] == "yes":
                    d["amount_agrees"] += 1
                for k, v in (s.get("agree") or {}).items():
                    d["agree_parts"][f"{k}={v}"] += 1
                if p.get("payload_id") == 3:
                    notes.append("payload 3")
                if p.get("fee"):
                    d["fee_releases"] += 1
                    notes.append("relayer fee in the message")
                age = x["ts"] - s["ts"]
                ages.append(age)
                if s["ts"] < T0:
                    d["older_than_period"] += 1
                    notes.append(f"message published {(T0 - s['ts']) / 86400:.1f} d before the period")
                if idx_lo is None or s["sequence"] < idx_lo:
                    d["located_singly"] += 1
                bad = [k for k, v in (s.get("agree") or {}).items() if v is False]
                if bad:
                    notes.append("disagrees: " + ", ".join(bad))
                if s.get("note"):
                    notes.append(s["note"])
                if s.get("vaa_payload_equal") is False:
                    notes.append("signed payload differs from the source message")
                row_src = (iso(s["ts"]), s["block"], age, s["value_moved"], s["value_detail"], s["amount_agrees"])
            else:
                notes.append("no source message with this sequence")
                row_src = ("", "", "", "na", "none", "no")
            for n in notes:
                d["notes"][re.sub(r"[0-9.]+ d before", "N d before", n)] += 1
            if not s or s["value_moved"] != "yes" or s["amount_agrees"] != "yes":
                d["problems"].append({"release_utc": iso(x["ts"]), "token": x["symbol"], "amount": amount,
                                      "usd": usd, "kind": x["kind"], "matched": "yes" if s else "no",
                                      "value_moved": row_src[3], "amount_agrees": row_src[5], "note": "; ".join(notes)})
            rows.append({"pair": f"{src}->{dst}", "release_ts_utc": iso(x["ts"]), "release_block": x["block"],
                         "token": x["symbol"], "amount": amount, "usd": "" if usd is None else f"{usd:.2f}",
                         "kind": x["kind"], "matched": "yes" if s else "no", "src_ts_utc": row_src[0],
                         "src_block": row_src[1], "deposit_age_s": row_src[2], "value_moved": row_src[3],
                         "value_detail": row_src[4], "amount_agrees": row_src[5], "note": "; ".join(notes),
                         "_k": (x["ts"], x["block"], x["log_index"], src)})
        d["deposit_age_s"] = quantiles(ages)
        d["tokens_usd"] = dict(d["tokens_usd"].most_common(12))
        d["tokens_n"] = dict(d["tokens_n"].most_common(12))
        for k in ("kinds", "payload_ids", "value_moved", "value_detail", "price_res", "vaa_payload_equal",
                  "vaa_ts_equal", "agree_parts", "notes"):
            d[k] = {str(kk): vv for kk, vv in d[k].items()}
        d["scan"] = S["scan"]
        d["daily_counts"] = dict(sorted(collections.Counter(iso(x["ts"])[:10] for x in rels).items()))
        summ["directions"][f"{src}->{dst}"] = d
        print(src, "->", dst, json.dumps({k: v for k, v in d.items() if k not in ("problems", "daily_counts", "notes")},
                                          default=str)[:2500], flush=True)
    rows.sort(key=lambda r: r["_k"])
    cols = ["pair", "release_ts_utc", "release_block", "token", "amount", "usd", "kind", "matched", "src_ts_utc",
            "src_block", "deposit_age_s", "value_moved", "value_detail", "amount_agrees", "note"]
    DATA.mkdir(parents=True, exist_ok=True)
    with open(DATA / f"wormhole_{pair_tag}_releases.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for r in rows:
            w.writerow([r[c] for c in cols])
    jdump(RAW / "summary.json", summ)
    print("rows", len(rows))
    write_readme(T, summ, pair_tag)


def fmt_age(s):
    s = float(s)
    if s < 120:
        return f"{s:,.0f} s"
    if s < 7200:
        return f"{s / 60:,.1f} min"
    if s < 2 * 86400:
        return f"{s / 3600:,.1f} h"
    return f"{s / 86400:,.1f} d"


def write_readme(T, summ, pair_tag):
    a, b = summ["pair"]
    pc = jload(RAW / "pair_counts.json")
    cover_all = jload(RAW / "coverage.json") if (RAW / "coverage.json").exists() else {}
    cover = {k: v for k, v in cover_all.items() if "->" in k and isinstance(v, dict) and "mine" in v}
    cross = jload(RAW / "crosscheck.json") if (RAW / "crosscheck.json").exists() else {}
    per = jload(RAW / "period.json")
    src = T["sources"]
    dirs = list(summ["directions"])
    D = summ["directions"]
    L = []
    A = L.append
    A(f"# Wormhole token bridge releases, {a} and {b}, 2026-09-04 to 2026-10-16")
    A("")
    A(f"Shadow-run input for the deposit-backing check. Built by `shadow/wormhole_collect.py` on {now_iso()[:10]} "
      f"from public RPC endpoints; `shadow/wormhole_decode.py` holds the decoding, shared with the live monitor.")
    A(f"Data: `wormhole_{pair_tag}_releases.csv`, one row per release in [{iso(T0)}, {iso(T1)}), sorted by time. "
      "The CSV and this README carry no addresses and no transaction hashes; the raw caches that do (RPC answers, "
      "API pages, contract addresses) stay in `shadow/raw/wormhole/` and are not committed.")
    A("")
    A("## Pair")
    A("")
    A(f"TransferRedeemed events of the token bridge on each of the seven candidate chains over "
      f"{pc['week_utc'][0][:10]} to {pc['week_utc'][1][:10]} (the period's last week), counted by emitter chain. "
      "A pair's score is the releases in both directions combined:")
    A("")
    A("| pair | first -> second | second -> first | both |")
    A("|---|---:|---:|---:|")
    for k, v in list(pc["pair_scores"].items())[:6]:
        x, y = k.split("<->")
        A(f"| {x} and {y} | {v[f'{x}->{y}']:,} | {v[f'{y}->{x}']:,} | {v['total']:,} |")
    A("")
    tot = {ch: v["redeemed_total"] for ch, v in pc["chains"].items()}
    A(f"{a.capitalize()} and {b.upper() if b == 'bsc' else b.capitalize()} lead by a factor of "
      f"{list(pc['pair_scores'].values())[0]['total'] / list(pc['pair_scores'].values())[1]['total']:.1f} over the next pair. "
      "Redeem events on each chain in that week, all emitter chains: " +
      ", ".join(f"{ch} {n:,}" for ch, n in sorted(tot.items(), key=lambda kv: -kv[1])) +
      ". Most of the rest come from non-EVM chains (Solana, Near, Sui), which fall outside the EVM pair.")
    A("")
    A("## Contracts and their roles")
    A("")
    A("- Core contract (one per chain). Every message goes through it; it emits `LogMessagePublished(sender, "
      "sequence, nonce, payload, consistencyLevel)`, and its sequence counts up by one per sender.")
    A("- Token bridge (one per chain), the sender of transfer messages. On the source chain it takes a token "
      "native to that chain into custody, wrapping the gas coin first, or burns a wrapped token it issued, and "
      "publishes a transfer message. On the destination chain it completes the transfer from the guardian-signed "
      "message: it emits `TransferRedeemed(emitterChainId, emitterAddress, sequence)` and then releases the tokens.")
    A("- Wrapped gas coin (WETH on Ethereum, WBNB on BSC), the custody form of the gas coin; the token bridge "
      "names it (`WETH()`).")
    A("")
    A(f"Addresses: `CONTRACTS.MAINNET` in `sdk/js/src/utils/consts.ts` and `knownTokenbridgeEmitters` in "
      f"`sdk/mainnet_consts.go` of the wormhole-foundation/wormhole GitHub repository (main, commit "
      f"{str(src.get('github_commit'))[:12]}, {str(src.get('github_commit_date'))[:10]}), and the mainnet tables "
      f"of the documentation's contract-addresses page (core contracts; Wrapped Token Transfers, the documentation's "
      f"name for the token bridge), accessed {src['accessed_utc'][:10]}. For all seven chains the three lists agree "
      "(core and token bridge in the SDK and the documentation; the token bridge's emitter in the Go list is the "
      "token bridge's address).")
    A("")
    A("On chain, for each of the seven chains: the endpoint's chain id is the expected EVM chain; both contracts "
      "have code; the core contract's and the token bridge's `chainId()` return the Wormhole chain id; the token "
      "bridge's `wormhole()` is the core contract; the token bridge's `bridgeContracts(c)` returns the other six "
      "token bridges' emitters; the token bridge names a wrapped gas coin. In the pair week the core contract "
      "emitted LogMessagePublished from the token bridge (" +
      ", ".join(f"{ch} {v['messages_total']:,}" for ch, v in pc["chains"].items()) +
      ") and the token bridge emitted TransferRedeemed on every chain. Every redeem event's emitter equals the "
      "registered token bridge of its chain.")
    A("")
    A("## Method")
    A("")
    A(f"Period: [{iso(T0)}, {iso(T1)}) by release block time; the block ranges are the first block at or after "
      "each midnight UTC (" + "; ".join(f"{ch} blocks {v['blocks'][0]:,} to {v['blocks'][1]:,}, last block before the "
      f"period at {v['edge_times'][0]}, first after at {v['edge_times'][3]}" for ch, v in per.items()) + ").")
    A("")
    A("1. Releases. Every TransferRedeemed of the destination token bridge whose emitter chain and emitter are the "
      "source chain's token bridge (topics filter), then the receipt of its transaction. The token movement is "
      "taken from the logs after the event and before the next TransferRedeemed in the same transaction (the token "
      "bridge emits the event, then pays a relayer fee if the message names one, then pays the recipient): a "
      "Transfer out of the token bridge (`unlock`), a mint of a token for which the token bridge's "
      "`isWrappedAsset` is true (`mint`), or a Withdrawal of the wrapped gas coin by the token bridge "
      "(`unlock_native`; the gas coin itself is paid by an internal call, read from a `debug_traceTransaction` "
      "call trace). A burn by the token bridge in the same stretch belongs to an outgoing transfer and is "
      "skipped. `amount` is the whole release in token units (recipient plus relayer fee), `token` the "
      "symbol of the released token (the gas coin's symbol for `unlock_native`). Transfers with payload "
      "(payload 3), redeemed by the contract named in the message, are included like plain transfers.")
    A("2. Source messages. LogMessagePublished of the source core contract with the source token bridge as sender, "
      "scanned in bulk from three days before the period to its end and indexed by sequence. A release whose "
      "sequence is older than the scan is located with the timestamp of the signed message found in the "
      "release transaction's input (the guardians copy the source block's time into it): a log query around "
      "that time on the source chain. The transfer payload is decoded: payload id, normalized amount "
      "(8 decimals), token address and chain, recipient, target chain, relayer fee (payload 1) or sender "
      "(payload 3).")
    A("3. Value moved. In the source transaction, between the token bridge's previous message and this one: for "
      "a token native to the source chain, a Transfer of that token into the token bridge, or a Deposit of the "
      "wrapped gas coin credited to it (`lock`); for a wrapped token, a Transfer of the wrapped token from the "
      "token bridge to the zero address (`burn`), the wrapped token being the source token bridge's "
      "`wrappedAsset(tokenChain, tokenAddress)`. `value_moved` is yes when such a movement exists and its amount, "
      "normalized to 8 decimals, equals the message's amount.")
    A("4. Agreement. `amount_agrees` is yes when the message's amount, de-normalized to the released token's "
      "decimals, equals the release (recipient plus fee), the message's token (chain and address) equals the "
      "released token's origin (for a wrapped token its `chainId()` and `nativeContract()`, read on the "
      "destination), and the message's recipient equals the release's recipient. The target chain and, for "
      "two-part releases, the fee are checked as well and listed in the notes when they differ.")
    A("5. Prices. DefiLlama coins API, as `data/legit/build_e59.py` does: the hourly chart point nearest the "
      "release within 2 hours, else the daily point within 36 hours. The coin is the released token for an "
      "unlock and the origin token on its own chain for a mint, each falling back to the other.")
    A("6. `deposit_age_s` is the release block time minus the source block time.")
    A("")
    A("## Counts")
    A("")
    A("| | " + " | ".join(dirs) + " |")
    A("|---|" + "---:|" * len(dirs))

    def row(label, f):
        A(f"| {label} | " + " | ".join(f(D[k]) for k in dirs) + " |")
    row("releases", lambda d: f"{d['releases']:,}")
    row("USD value (priced releases)", lambda d: f"{d['usd'] / 1e6:,.2f}M")
    row("unpriced releases", lambda d: f"{d['unpriced']:,}")
    row("kind unlock / mint / unlock_native", lambda d: " / ".join(f"{d['kinds'].get(k, 0):,}" for k in ("unlock", "mint", "unlock_native"))
        + (f" (none {d['kinds']['none']})" if d['kinds'].get('none') else ""))
    row("payload 1 / payload 3", lambda d: f"{d['payload_ids'].get('1', 0):,} / {d['payload_ids'].get('3', 0):,}")
    row("relayer fee in the message", lambda d: f"{d['fee_releases']:,}")
    row("matched to a source message", lambda d: f"{d['matched']:,}")
    row("value moved: lock / burn", lambda d: f"{d['value_detail'].get('lock', 0):,} / {d['value_detail'].get('burn', 0):,}")
    row("value moved = yes", lambda d: f"{d['value_moved'].get('yes', 0):,}")
    row("amount, token and recipient agree", lambda d: f"{d['amount_agrees']:,}")
    row("message published before the period", lambda d: f"{d['older_than_period']:,}")
    row("located singly (older than the bulk scan)", lambda d: f"{d['located_singly']:,}")
    for q, lab in (("0.0", "min"), ("0.01", "p1"), ("0.5", "median"), ("0.99", "p99"), ("1.0", "max")):
        row(f"deposit age {lab}", lambda d, q=q: fmt_age(d["deposit_age_s"][q]) if d["deposit_age_s"] else "")
    A("")
    for k in dirs:
        top = ", ".join(f"{s} {v / 1e6:,.1f}M" for s, v in list(D[k]["tokens_usd"].items())[:6])
        A(f"Largest tokens by value, {k}: {top}.")
    A("")
    A("## Releases that did not match or whose value did not move")
    A("")
    probs = [(k, p) for k in dirs for p in D[k]["problems"]]
    if not probs:
        A("None: every release matched a source message whose value moved and whose amount, token and recipient "
          "agree with the release.")
    else:
        for k, p in probs:
            usd = "" if p["usd"] is None else f", USD {p['usd']:,.0f}"
            A(f"- {k}, {p['release_utc']}: {p['amount']} {p['token']} ({p['kind']}{usd}); matched {p['matched']}, "
              f"value moved {p['value_moved']}, agrees {p['amount_agrees']}; {p['note']}")
    A("")
    A("## Checks")
    A("")
    for k in dirs:
        s = D[k]["scan"]
        A(f"- Source scan, {k}: {s['messages']:,} messages of the source token bridge in blocks {s['blocks'][0]:,} to "
          f"{s['blocks'][1]:,} ({s['block_times'][0]} to {s['block_times'][1]}), sequences {s['first_sequence']:,} to "
          f"{s['last_sequence']:,} with {s['n_missing']} missing; the core contract's `nextSequence(token bridge)` "
          f"is {s.get('next_sequence_before_range')} just before the range and {s.get('next_sequence_at_range_end')} "
          f"at its end, so the scan holds every message of the range: {'yes' if s.get('range_complete') else 'NO'}.")
    for k in dirs:
        d = D[k]
        A(f"- Signed message in the release transaction's input, {k}: found for {d['vaa_found']:,} of "
          f"{d['releases']:,} releases; its payload equals the source message's payload "
          f"{d['vaa_payload_equal'].get('True', 0):,} times (differs {d['vaa_payload_equal'].get('False', 0)}, "
          f"payload not read {d['vaa_payload_equal'].get('None', 0)}); its timestamp equals the source block time "
          f"{d['vaa_ts_equal'].get('True', 0):,} times (differs {d['vaa_ts_equal'].get('False', 0)}).")
    for k, c in cross.items():
        A(f"- Second provider, {k}: redeem events over the period {c['redeem_events_second_provider']:,} against "
          f"{c['redeem_events_primary']:,} (only in the first scan {c['only_primary']}, only in the second "
          f"{c['only_second']}); source messages over the scan range {c['source_messages_second_provider']:,} against "
          f"{c['source_messages_primary']:,} (only first {c['source_only_primary']}, only second {c['source_only_second']}).")
    for k in dirs:
        d = D[k]
        A(f"- Agreement components, {k}: " + ", ".join(f"{kk} {vv:,}" for kk, vv in sorted(d["agree_parts"].items())) + ".")
    A("")
    if cover:
        A("## Coverage against Wormholescan")
        A("")
        A("Wormholescan's operations API (`api.wormholescan.io/api/v1/operations`, sourceChain and targetChain set, "
          "requested one source day at a time; its from/to filter the source time) for source days "
          f"{iso(T0 - COVER_PRE)[:10]} to {iso(T1 + 86400)[:10]}, token bridge operations only, plus a request by id for "
          "each release whose operation was not in those pages. An operation counts as an API release in the "
          "period when its destination record (targetChain) has a timestamp in the period.")
        A("")
        A("| | " + " | ".join(cover) + " |")
        A("|---|" + "---:|" * len(cover))
        for lab, f in (("releases in this dataset", lambda c: f"{c['mine']:,}"),
                       ("API releases in the period", lambda c: f"{c['api_with_destination_record_in_period']:,}"),
                       ("in both", lambda c: f"{c['both']:,}"),
                       ("only in this dataset", lambda c: f"{c['only_mine']:,}"),
                       ("only in the API", lambda c: f"{c['only_api']:,}"),
                       ("API operations without a destination record", lambda c: f"{c['api_without_destination_record']:,}"),
                       ("days whose counts differ (of 42)", lambda c: f"{c['days_differing']}"),
                       ("destination transaction differs (in both)", lambda c: f"{c['redeem_tx_differs']}"),
                       ("source transaction differs", lambda c: f"{c['source_tx_differs']}")):
            A(f"| {lab} | " + " | ".join(f(c) for c in cover.values()) + " |")
        A("")
        for k, c in cover.items():
            A(f"- {k}: releases only in this dataset, by reason: " +
              (", ".join(f"{kk} {vv:,}" for kk, vv in c["only_mine_why"].items()) or "none") + ". "
              f"API operations sourced in the period without a destination record: " +
              (", ".join(f"{kk} {vv:,}" for kk, vv in c["api_no_destination_record_sourced_in_period"].items()) or "none") + ". "
              f"API operations sourced in the period that this dataset does not release in the period: " +
              (", ".join(f"{kk} {vv:,}" for kk, vv in c["api_sourced_in_period_not_released_in_period"].items()) or "none") +
              f". Times in both: API minus chain {c['api_minus_chain_time_s']['min']} to {c['api_minus_chain_time_s']['max']} s.")
        A("")
        for k, c in cover.items():
            A(f"- Source-side reconciliation, {k} (every message of the source token bridge to the destination in the "
              "bulk source scan, placed by when the destination released it, from redeem scans of the destination "
              f"over the week before the period and from its end to {c['redemption_scan_outside_period']['after_to_utc']}): " +
              ", ".join(f"{kk} {vv:,}" for kk, vv in c["source_reconciliation"].items()) +
              f"; releases in the period of messages older than the scan: {c['releases_of_messages_older_than_scan']}.")
        A("")
        A("Daily counts (this dataset / API):")
        A("")
        A("| day | " + " | ".join(cover) + " |")
        A("|---|" + "---:|" * len(cover))
        days = [x["day"] for x in list(cover.values())[0]["daily"]]
        for i, dday in enumerate(days):
            A(f"| {dday} | " + " | ".join(f"{c['daily'][i]['mine']} / {c['daily'][i]['api']}" for c in cover.values()) + " |")
        A("")
        for line in coverage_explanation(cover_all):
            A(line)
        A("")
        if COVERAGE_EXPLANATION:
            A(COVERAGE_EXPLANATION.strip())
            A("")
    A("## Columns")
    A("")
    A("`pair` (source->destination), `release_ts_utc` and `release_block` (destination block), `token` (symbol of "
      "the released token), `amount` (token units), `usd` (at the release hour; empty when unpriced), `kind` "
      "(unlock, mint, unlock_native), `matched` (a source message with the release's sequence from the source "
      "token bridge exists), `src_ts_utc` and `src_block` (the message's block), `deposit_age_s`, `value_moved` "
      "(yes, no, or na when unmatched), `value_detail` (lock, burn, none), `amount_agrees`, `note` (payload 3, "
      "relayer fee, message older than the period, disagreements, no price).")
    A("")
    A("## Interface for the live monitor (`shadow/wormhole_decode.py`)")
    A("")
    A("- `new_releases(rpc_dst, dst_chain, from_block, to_block)`: list of release dicts for the configured pair "
      "(the other chain of the pair is the source), sorted by block and log index. Keys: `dst_chain`, "
      "`src_chain`, `emitter_chain`, `emitter`, `sequence`, `block`, `ts`, `tx`, `log_index`, `kind`, `token`, "
      "`symbol`, `decimals`, `amount_raw` (base units, recipient plus fee), `fee_raw`, `recipient`, `fee_to`, "
      "`moves`, `origin_chain`, `origin_address`, `vaa` (timestamp, nonce, consistency and payload of the signed "
      "message read from the transaction input, or None), `notes`.")
    A("- `find_source(rpc_src, src_chain, release)`: None when the source chain has no message from its token "
      "bridge with the release's sequence; otherwise a dict with `block`, `ts`, `tx`, `sequence`, `payload` "
      "(decoded transfer), `value_moved`, `value_detail`, `moved_raw`, `amount_agrees`, `agree` (amount, token, "
      "recipient, to_chain, fee), `vaa_payload_equal`, `vaa_ts_equal`, `note`.")
    A("- `rpc_*` is an `incidents/rpc.py` `Rpc`, or `wormhole_decode.Client(chain, cache_dir=None)`, which adds "
      "the endpoints tested on 2026-10-16, JSON-RPC batches, per-endpoint log ranges and a call trace for "
      "gas-coin payouts. `message_index(rpc_src, src_chain, b0, b1)` builds the sequence index the collector "
      "passes to `find_source` as `index=`.")
    A("")
    A("## Reproduce")
    A("")
    A("`python -I shadow/wormhole_collect.py targets | pairs | collect | traces | sources | crosscheck | coverage | build` "
      "(in that order; every step caches under `shadow/raw/wormhole/`).")
    (DATA / "wormhole_README.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("README written")


def coverage_explanation(cover):
    """Why the daily counts differ, from coverage.json: the source days on which the API stops carrying
    destination records, and where each release missing from the API's releases stands in the API."""
    out = ["Why the counts differ:", ""]
    other = cover.get("other_routes_token_bridge_with_destination_record") or {}
    cover = {k: v for k, v in cover.items() if "->" in k and isinstance(v, dict) and "mine" in v}
    for k, c in cover.items():
        share = c["destination_record_share_by_source_day"]
        days = sorted(share)
        gap_from = None
        for i, d in enumerate(days):
            rest = [e for e in days[i:] if share[e][1] > 0]
            if rest and all(share[e][0] == 0 for e in rest):
                gap_from = d
                break
        with_rec = sum(v[0] for v in share.values())
        n_ops = sum(v[1] for v in share.values())
        s = (f"- {k}: {with_rec:,} of the API's {n_ops:,} token bridge operations (source days "
             f"{days[0]} to {days[-1]}) carry a destination record.")
        if gap_from:
            pre = [e for e in days if e < gap_from]
            n_pre = sum(share[e][1] for e in pre)
            w_pre = sum(share[e][0] for e in pre)
            s += (f" None does from source day {gap_from} on ({sum(share[e][1] for e in days if e >= gap_from):,} "
                  f"operations), against {w_pre:,} of {n_pre:,} before; the API's daily releases therefore fall to "
                  "zero while this dataset's do not.")
        why = c["only_mine_why"]
        if why:
            s += " Releases here that the API does not count as releases in the period: " + \
                 ", ".join(f"{kk.lower()} {vv:,}" for kk, vv in why.items()) + "."
        if c["only_api"]:
            s += f" API releases in the period missing here: {c['only_api']}."
        else:
            s += " Every API release in the period is in this dataset."
        out.append(s)
    if other:
        out.append("")
        parts = []
        for key, (w, n) in other.items():
            route, day = key.split(" ")
            a_, b_ = (int(x) for x in route.split("->"))
            parts.append(f"{CHAIN_NAME.get(a_, a_)} to {CHAIN_NAME.get(b_, b_)} on {day}: {w} of {n}")
        out.append("Other routes, token bridge operations with a destination record by source day (same API, "
                   "requested 2026-10-16): " + "; ".join(parts) + ". The missing records follow the destination "
                   "chain (Ethereum), not this pair. The counts in this dataset come from the redeem events on chain, "
                   "and the source-side reconciliation above places every message of the source token bridge to the "
                   "destination without the API.")
    return out


COVERAGE_EXPLANATION = ""


if __name__ == "__main__":
    steps = {"targets": targets, "pairs": pairs, "collect": collect, "traces": traces, "sources": sources,
             "crosscheck": crosscheck, "coverage": coverage, "build": build}
    steps[sys.argv[1]]()
