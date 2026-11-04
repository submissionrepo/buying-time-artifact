"""E10 (QBridge, Ethereum to BSC): legitimate mints by the BSC bridge handler over the 150 days before the failure
(2026-10-16).

Inputs  results/incidents.csv            failure time (first_release_utc: the first unbacked mint on BSC)
        raw/E10/targets.json             contract addresses (raw cache): BSC bridge proxy (contractAddress of the BSC
                                         deployment transaction named in data/incidents/research/batch_B.json),
                                         `handler_bsc` (the contract that receives the minted xETH in a failure
                                         transaction; on chain this is the delegate contract, not the handler, see
                                         Roles), Ethereum bridge proxy (the to-address of a failure deposit transaction)
Outputs E10.csv                          ts_utc, leg, asset, amount, usd, kind, priced (no addresses, no hashes)
        raw/E10/                         RPC caches, prices, bsc_state.json, summary.json

Method
- Window [t_fail - 150 d, t_fail - 1 s]. The BSC bridge was deployed inside the window (2021-11-23), so the window
  holds its whole history before the failure.
- Roles (read on chain, raw/E10/bsc_state.json). The bridge's resourceIDToHandlerAddress returns one handler for
  every resource ID used on either side. The handler executes proposals and mints xETH. For deposits with a nonzero
  option it mints to the contract recorded in targets.json as `handler_bsc`, which supplies the xETH to the
  operator's lending market and the market issues its shares to the recipient ("delegate contract" below); for
  option 0 it mints to the recipient. (Correction of 2026-10-16: the first version took `handler_bsc` for the
  handler, so its completeness scans covered the delegate contract only.)
- BSC release record. The bridge proxy emits a ProposalEvent at each status change; status 3 marks execution, in
  which the handler mints xETH (Transfer from the zero address). The event exists in two versions (correction of
  2026-10-16; the first version knew only the second): until the proxy upgrade of 2021-12-15 01:40 UTC,
  ProposalEvent(uint8 originDomainID, uint64 depositNonce, uint8 status, bytes32 dataHash) with
  dataHash = keccak256(handler ++ data); afterwards ProposalEvent(uint8, uint64, uint8, bytes data). The resource ID
  and data (option, amount, recipient) are read from the executing call into the bridge (voteProposal or
  executeProposal, found in the transaction's call trace) and checked against the event (data equal, or hash equal).
  One row per executed proposal: the mint in the same transaction (kind erc20), whose amount and final recipient
  must equal the amount and recipient in the data.
- Backing (origin side). Each executed proposal's nonce is matched to the Ethereum bridge's
  Deposit(uint8 destinationDomainID, bytes32 resourceID, uint64 depositNonce, address indexed user, bytes data)
  with destination BSC and the same nonce; resource ID and data must be equal, except that for deposits whose
  recipient differs from the depositor the executed data names the depositor (matched on option and amount). The
  deposit transaction must have locked the amount: ETH that the Ethereum bridge forwarded to its handler in the
  depositETH call (call trace; this also covers deposits made through other contracts) or a token transfer from the
  depositor to the Ethereum handler in the same transaction. Mints without a backed deposit are not legitimate
  releases; they are reported in summary.json and left out of the CSV, as are zero-amount proposals (nothing moves)
  and releases to the failure's recipient.
- Completeness. (a) Every xETH Transfer from the zero address over the bridge's life lies in an executed proposal.
  (b) Topic scans over the bridge's life: every token Transfer from the zero address to the handler or the delegate
  contract, every token Transfer with either as sender, and mints and burns of every token on the handler's burn
  list. (c) xETH supply: change over the bridge's life equals mints minus burns. (d) Native BNB: balances of the
  handler, the delegate contract and the bridge at both ends, and the call trace of every executed proposal
  (value-bearing calls by the bridge, the handler or the delegate contract; a value-bearing call by another contract
  must be a loan, i.e. that contract emitted Borrow(borrower = callee, amount = value) in the same transaction).
- Origin side, per deposit (call trace of every deposit transaction): the ETH the Ethereum bridge forwarded to its
  handler, or the token amount the depositor transferred to the handler (receipt); the per-row check compares the
  mint with this amount to the wei.
- Prices: DefiLlama /chart (hourly within 2 h, else daily within 36 h). xETH has no series of its own (checked);
  it is valued at ETH because each legitimate mint equals the ETH locked by its deposit (checked per row).
Run: python -I data/legit/build_e10.py bsc|eth|scan|txs|build   (bsc also writes bsc_state.json)
"""
import bisect
import collections
import csv
import datetime
import gzip
import json
import pathlib
import sys
import time
import urllib.request

from Crypto.Hash import keccak

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT / "incidents"))
from rpc import Rpc, TRANSFER, topic_addr, addr_from_topic, RangeError, erc20_meta  # noqa: E402

EID = "E10"
RAW = HERE / "raw" / EID
T = json.loads((HERE / "targets" / f"{EID}.json").read_text())
QB, HANDLER, XETH = T["qbridge_bsc"].lower(), T["handler_bsc"].lower(), T["xeth_bsc"].lower()
DELEGATE = HANDLER  # targets.json calls it handler_bsc; on chain it is the delegate contract (see Roles)
QE = T["qbridge_eth"].lower()
LEG = "QBridge handler mints (BSC)"
ZERO_T = "0x" + "0" * 64
ZERO = "0x" + "0" * 40
PROPOSAL_EVENT = "0xe5db3e6185cae006dbadaa64fef932d1354507716ff0dbe3b04fbb221b6e7633"  # ProposalEvent(uint8,uint64,uint8,bytes)
PROPOSAL_EVENT_OLD = "0x968626a768e76ba1363efe44e322a6c4900c5f084e0b45f35e294dfddaa9e0d5"  # ProposalEvent(uint8,uint64,uint8,bytes32)
PROPOSAL_VOTE = "0x25f8daaa4635a7729927ba3f5b3d59cc3320aca7c32c9db4e7ca7b9574343640"   # ProposalVote(uint8,uint64,uint8,bytes32)
FAILED_HANDLER = "0xbd37c1f0d53bb2f33fe4c2104de272fcdeb4d2fef3acdbf1e4ddc3d6833ca376"  # FailedHandlerExecution(bytes)
DEPOSIT = "0x9685971ce323aadcdbcd895683b8947d4454b020a263e7fa49aefb0fd0c9317d"         # Deposit(uint8,bytes32,uint64,address,bytes)
UPGRADED = "0xbc7cd75a20ee27fd9adebab32041f755214dbc6bffa90cc0225b39da2e5c2d3b"        # Upgraded(address)
BORROW = "0xe1979fe4c35e0cef342fef5668e2c8e7a7e9f5d5d1ca8fee0ac6c427fa4153af"          # Borrow(address,uint256,uint256)
SEL_VOTE = "0xc0331b3e"      # voteProposal(uint8,uint64,bytes32,bytes)
SEL_EXEC = "0xd28ba851"      # executeProposal(uint8,uint64,bytes32,bytes,bool)
SEL_DEPOSIT = "0x05e2ca17"   # deposit(uint8,bytes32,bytes)
SEL_DEPOSIT_ETH = "0xf179637c"  # depositETH(uint8,bytes32,bytes)
BSC_DOMAIN = 1               # destinationDomainID of the Ethereum deposits that the BSC bridge executes
WINDOW_S = 150 * 86400
STEP = 20000
KEEP = ("address", "topics", "data", "blockNumber", "blockTimestamp", "transactionHash", "logIndex")
STATS = collections.Counter()


def sel(sig):
    h = keccak.new(digest_bits=256)
    h.update(sig.encode())
    return "0x" + h.hexdigest()[:8]


def keccak_hex(hexstr):
    h = keccak.new(digest_bits=256)
    h.update(bytes.fromhex(hexstr))
    return h.hexdigest()


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


def slim(logs):
    return [{k: lg.get(k) for k in KEEP} for lg in logs]


def cached(path, fn):
    if path.exists():
        return json.loads(path.read_text())
    v = fn()
    path.write_text(json.dumps(v))
    return v


def gz_cached(path, fn):
    if path.exists():
        with gzip.open(path, "rt") as fh:
            return json.load(fh)
    v = fn()
    tmp = path.with_suffix(".tmp")
    with gzip.open(tmp, "wt") as fh:
        json.dump(v, fh)
    tmp.replace(path)
    return v


def bsc():
    """NodeReal endpoint only (the fallback caps logs at 50 blocks); HTTP 429 answered with long waits."""
    r = Rpc("bsc_trace")
    _call = r.call

    def call(method, params, retries=8):
        for k in range(10):
            try:
                return _call(method, params, retries=retries)
            except RangeError:
                raise
            except RuntimeError as e:
                STATS["bsc_retry"] += 1
                if k == 9:
                    raise
                time.sleep(20 * (k + 1) if "429" in str(e) else 5)
    r.call = call
    return r


def words(data):
    d = data[2:]
    return [d[i:i + 64] for i in range(0, len(d), 64)]


def split_data(d):
    """(option, amount, recipient) from the 96-byte proposal / deposit data (hex without 0x)."""
    pw = [d[i:i + 64] for i in range(0, len(d), 64)]
    return (int(pw[0], 16) if pw else None, int(pw[1], 16) if len(pw) > 1 else None,
            ("0x" + pw[2][-40:]).lower() if len(pw) > 2 else None)


def bytes_field(w, k):
    """Payload of the ABI bytes field whose length word is w[k] (hex without 0x)."""
    n = int(w[k], 16)
    return "".join(w[k + 1:])[: 2 * n]


def decode_proposal(lg):
    """Both event versions: data (new) or dataHash (old)."""
    w = words(lg["data"])
    out = {"origin": int(w[0], 16), "nonce": int(w[1], 16), "status": int(w[2], 16)}
    if lg["topics"][0] == PROPOSAL_EVENT:
        out["data"] = bytes_field(w, 4)
        out["option"], out["amount"], out["recipient"] = split_data(out["data"])
    else:
        out["hash"] = w[3]
    return out


def decode_deposit(lg):
    w = words(lg["data"])
    d = bytes_field(w, 4)
    opt, amt, rec = split_data(d)
    return {"dest": int(w[0], 16), "resource": w[1], "nonce": int(w[2], 16),
            "user": addr_from_topic(lg["topics"][1]).lower(), "data": d, "option": opt, "amount": amt, "recipient": rec}


def decode_call(inp):
    """voteProposal / executeProposal input -> origin, nonce, resource, data (both share the first four words)."""
    if not inp or inp[:10] not in (SEL_VOTE, SEL_EXEC):
        return None
    w = words("0x" + inp[10:])
    off = int(w[3], 16) // 32
    return {"origin": int(w[0], 16), "nonce": int(w[1], 16), "resource": w[2], "data": bytes_field(w, off),
            "fn": "voteProposal" if inp[:10] == SEL_VOTE else "executeProposal"}


def window(r):
    def fn():
        t_fail = failure_time()
        t_start = t_fail - WINDOW_S
        b0 = r.block_at(t_start, lo=10_000_000, hi=15_000_000)
        bf = r.block_at(t_fail, lo=b0, hi=15_000_000)
        return {"t_fail": t_fail, "t_start": t_start, "t_end": t_fail - 1, "b0": b0, "b1": bf - 1,
                "ts_b0m1": r.block_ts(b0 - 1), "ts_b0": r.block_ts(b0), "ts_b1": r.block_ts(bf - 1), "ts_bf": r.block_ts(bf)}
    w = cached(RAW / "window_bsc.json", fn)
    assert w["ts_b0m1"] < w["t_start"] <= w["ts_b0"] and w["ts_b1"] < w["t_fail"] <= w["ts_bf"], w
    return w


def eth_deposits():
    logs = []
    for p in sorted(RAW.glob("eth_bridge_*.json"), key=lambda p: int(p.name.split("_")[2])):
        logs += json.loads(p.read_text())
    return logs


def bsc_state(r, w):
    """Handler and token behind every resource ID seen on either side (read at the window end, and the handler also at
    the first and last executed proposal), the handler's burn list, token metadata, and the Ethereum handler."""
    def fn():
        res = set()
        for lg in eth_deposits():
            if lg["topics"][0] == DEPOSIT:
                res.add(decode_deposit(lg)["resource"])
        bl = bsc_logs()
        for lg in bl["bridge"]:
            if lg["topics"][0] == DEPOSIT:
                res.add(decode_deposit(lg)["resource"])
        ex_blocks = sorted(int(lg["blockNumber"], 16) for lg in bl["bridge"]
                           if lg["topics"][0] in (PROPOSAL_EVENT, PROPOSAL_EVENT_OLD) and decode_proposal(lg)["status"] == 3)
        probe_blocks = sorted({ex_blocks[0], ex_blocks[-1], w["b1"]})
        out = {"read_at_blocks": probe_blocks, "resources": {}, "tokens": {}}
        handlers = set()
        for rid in sorted(res):
            hs = {str(b): "0x" + r.eth_call(QB, sel("resourceIDToHandlerAddress(bytes32)") + rid, b)[-40:] for b in probe_blocks}
            h = hs[str(w["b1"])]
            handlers.add(h)
            tok = "0x" + r.eth_call(h, sel("resourceIDToTokenContractAddress(bytes32)") + rid, w["b1"])[-40:]
            out["resources"][rid] = {"handler_by_block": hs, "handler": h, "token": tok}
        for rid, v in out["resources"].items():
            tok = v["token"]
            if tok in out["tokens"]:
                continue
            sym, dec = erc20_meta(r, tok, {})
            out["tokens"][tok] = {"symbol": sym, "decimals": dec,
                                  "burnList": int(r.eth_call(v["handler"], sel("burnList(address)") + "0" * 24 + tok[2:], w["b1"]), 16),
                                  "whitelisted": int(r.eth_call(v["handler"], sel("contractWhitelist(address)") + "0" * 24 + tok[2:], w["b1"]), 16)}
        assert len(handlers) == 1, handlers
        out["handler"] = handlers.pop()
        # Ethereum side: the handler behind the deposit resource IDs (read at the last Ethereum block before t_fail)
        e = Rpc("ethereum")
        we = json.loads((RAW / "window_eth.json").read_text())
        out["eth"] = {}
        for rid in sorted(res):
            try:
                h = "0x" + e.eth_call(QE, sel("resourceIDToHandlerAddress(bytes32)") + rid, we["e1"])[-40:]
            except RuntimeError as ex:  # noqa: PERF203
                h = f"error: {str(ex)[:120]}"
            out["eth"][rid] = {"handler": h}
        return out
    return cached(RAW / "bsc_state.json", fn)


def collect_bsc():
    r = bsc()
    w = window(r)
    print(w, flush=True)
    start = max(w["b0"], T["qbridge_bsc_deploy_block"])
    # the failure block itself (first unbacked mint) is fetched too, as a check of t_fail
    for s in range(start, w["b1"] + 1, STEP):
        e = min(s + STEP - 1, w["b1"])
        f = RAW / f"bsc_{s}_{e}.json.gz"

        def fetch(s=s, e=e):
            return {"b0": s, "b1": e,
                    "bridge": slim(r.logs(QB, None, s, e, step=STEP)),
                    "mint_to_handler": slim(r.logs(None, [TRANSFER, ZERO_T, topic_addr(HANDLER)], s, e, step=STEP)),
                    "from_handler": slim(r.logs(None, [TRANSFER, topic_addr(HANDLER)], s, e, step=STEP)),
                    "xeth_mint": slim(r.logs(XETH, [TRANSFER, ZERO_T], s, e, step=STEP))}
        c = gz_cached(f, fetch)
        print(s, e, len(c["bridge"]), len(c["mint_to_handler"]), len(c["from_handler"]), len(c["xeth_mint"]),
              r.calls, dict(STATS), flush=True)
    # failure block check (both event versions)
    cached(RAW / "failure_block_logs.json",
           lambda: slim(r.logs(QB, None, w["b1"] + 1, w["b1"] + 1, step=1)))
    st = bsc_state(r, w)
    print("handler", st["handler"], {k[-12:]: v["token"] for k, v in st["resources"].items()}, flush=True)

    # balances (native) and xETH at both ends: handler, delegate contract, bridge (xETH reads are 0 where the token
    # had no code yet; xeth_code records that)
    def bal():
        out = {}
        for blk in (start - 1, w["b1"]):
            code = len(r.call("eth_getCode", [XETH, hex(blk)])) > 2

            def xcall(data, blk=blk, code=code):
                return int(r.eth_call(XETH, data, blk), 16) if code else 0
            out[str(blk)] = {"handler_bnb": int(r.call("eth_getBalance", [st["handler"], hex(blk)]), 16),
                             "delegate_bnb": int(r.call("eth_getBalance", [DELEGATE, hex(blk)]), 16),
                             "bridge_bnb": int(r.call("eth_getBalance", [QB, hex(blk)]), 16),
                             "handler_xeth": xcall("0x70a08231" + "0" * 24 + st["handler"][2:]),
                             "delegate_xeth": xcall("0x70a08231" + "0" * 24 + DELEGATE[2:]),
                             "xeth_supply": xcall("0x18160ddd"), "xeth_code": int(code)}
        return out
    print(cached(RAW / "balances_bsc.json", bal), flush=True)


def collect_scan():
    """Topic scans for the handler registered in the bridge (bsc_state.json) over the bridge's life, plus mints and
    burns of every burn-list token: raw/E10/bsch_<s>_<e>.json.gz."""
    r = bsc()
    w = window(r)
    st = json.loads((RAW / "bsc_state.json").read_text())
    h = st["handler"]
    burn = sorted(t for t, v in st["tokens"].items() if v["burnList"])
    start = max(w["b0"], T["qbridge_bsc_deploy_block"])
    for s in range(start, w["b1"] + 1, STEP):
        e = min(s + STEP - 1, w["b1"])
        f = RAW / f"bsch_{s}_{e}.json.gz"

        def fetch(s=s, e=e):
            return {"b0": s, "b1": e, "handler": h, "burn_tokens": burn,
                    "mint_to_reg": slim(r.logs(None, [TRANSFER, ZERO_T, topic_addr(h)], s, e, step=STEP)),
                    "from_reg": slim(r.logs(None, [TRANSFER, topic_addr(h)], s, e, step=STEP)),
                    "burn_token_mint": slim(r.logs(burn, [TRANSFER, ZERO_T], s, e, step=STEP)),
                    "burn_token_burn": slim(r.logs(burn, [TRANSFER, None, ZERO_T], s, e, step=STEP))}
        c = gz_cached(f, fetch)
        print(s, e, len(c["mint_to_reg"]), len(c["from_reg"]), len(c["burn_token_mint"]), len(c["burn_token_burn"]),
              r.calls, dict(STATS), flush=True)


def collect_eth():
    """Ethereum bridge Deposit events from one day before the BSC deployment to the failure, with the deposit
    transactions' values and receipts (token transfers), and call traces of deposits made through other contracts."""
    w = json.loads((RAW / "window_bsc.json").read_text())
    e = Rpc("ethereum")
    b = bsc()

    def eblocks():
        t_dep = b.block_ts(T["qbridge_bsc_deploy_block"])
        e0 = e.block_at(t_dep - 86400, lo=13_000_000, hi=14_200_000)
        e1 = e.block_at(w["t_fail"], lo=e0, hi=14_200_000) - 1
        return {"e0": e0, "e1": e1, "ts_e0": e.block_ts(e0), "ts_e1": e.block_ts(e1)}
    eb = cached(RAW / "window_eth.json", eblocks)
    print(eb, flush=True)
    logs = []
    for s in range(eb["e0"], eb["e1"] + 1, 10000):
        t = min(s + 9999, eb["e1"])
        logs += cached(RAW / f"eth_bridge_{s}_{t}.json", lambda s=s, t=t: slim(e.logs(QE, None, s, t, step=10000)))
    print("eth bridge logs", len(logs), collections.Counter(lg["topics"][0][:10] for lg in logs), flush=True)
    dep_tx = sorted({lg["transactionHash"] for lg in logs if lg["topics"][0] == DEPOSIT})

    def txs():
        out = {}
        for h in dep_tx:
            tx = e.tx(h)
            rc = e.receipt(h)
            out[h] = {"from": tx["from"].lower(), "to": (tx["to"] or "").lower(), "value": int(tx["value"], 16),
                      "input": tx["input"][:10], "status": rc["status"], "block": int(rc["blockNumber"], 16),
                      "logs": [{"address": lg["address"].lower(), "topics": lg["topics"], "data": lg["data"]}
                               for lg in rc["logs"]]}
        return out
    d = cached(RAW / "eth_deposit_txs.json", txs)
    print("eth deposit txs", len(d), flush=True)

    # call traces of every deposit transaction (the ETH the bridge forwards to its handler is what the deposit locked)
    et = Rpc("ethereum_trace")
    p = RAW / "eth_deposit_traces.json"
    tr = json.loads(p.read_text()) if p.exists() else {}
    for i, h in enumerate(sorted(d)):
        if h in tr:
            continue
        res = et.call("trace_transaction", [h])
        tr[h] = [{"from": (x.get("action", {}).get("from") or "").lower(), "to": (x.get("action", {}).get("to") or "").lower(),
                  "value": int(x.get("action", {}).get("value") or "0x0", 16), "input": (x.get("action", {}).get("input") or "")[:10],
                  "type": x.get("type"), "callType": x.get("action", {}).get("callType"), "error": x.get("error"),
                  "traceAddress": x.get("traceAddress")} for x in res]
        if i % 10 == 0:
            p.write_text(json.dumps(tr))
    p.write_text(json.dumps(tr))
    print("eth deposit traces", len(tr), "of", len(d), flush=True)


def collect_txs():
    """Transaction, receipt and call trace (trace_transaction) of every BSC transaction with an executed proposal
    (status 3, either event version): raw/E10/bsc_exec_txs.json."""
    r = bsc()
    ex = sorted({lg["transactionHash"] for lg in bsc_logs()["bridge"]
                 if lg["topics"][0] in (PROPOSAL_EVENT, PROPOSAL_EVENT_OLD) and decode_proposal(lg)["status"] == 3})
    p = RAW / "bsc_exec_txs.json"
    out = json.loads(p.read_text()) if p.exists() else {}
    for i, h in enumerate(ex):
        if h in out:
            continue
        tx = r.tx(h)
        rc = r.receipt(h)
        tr = r.call("trace_transaction", [h])
        out[h] = {"from": tx["from"].lower(), "to": (tx["to"] or "").lower(), "value": int(tx["value"], 16),
                  "input": tx["input"], "status": rc["status"], "block": int(rc["blockNumber"], 16),
                  "logs": [{"address": lg["address"].lower(), "topics": lg["topics"], "data": lg["data"],
                            "logIndex": int(lg["logIndex"], 16)} for lg in rc["logs"]],
                  "trace": [{"from": (x.get("action", {}).get("from") or "").lower(),
                             "to": (x.get("action", {}).get("to") or "").lower(),
                             "value": int(x.get("action", {}).get("value") or "0x0", 16),
                             "input": (lambda a: a if (x.get("action", {}).get("to") or "").lower() == QB else a[:10])(
                                 x.get("action", {}).get("input") or ""),
                             "type": x.get("type"), "callType": x.get("action", {}).get("callType"),
                             "error": x.get("error"), "traceAddress": x.get("traceAddress")} for x in tr]}
        if i % 20 == 0:
            p.write_text(json.dumps(out))
            print("txs", i, len(ex), r.calls, dict(STATS), flush=True)
    p.write_text(json.dumps(out))
    print("executed-proposal transactions", len(out), flush=True)


def bsc_logs(prefix="bsc"):
    out = collections.defaultdict(list)
    cov = []
    for p in sorted(RAW.glob(f"{prefix}_*.json.gz"), key=lambda p: int(p.name.split("_")[1])):
        with gzip.open(p, "rt") as fh:
            c = json.load(fh)
        cov.append((c["b0"], c["b1"]))
        for k, v in c.items():
            if isinstance(v, list) and k != "burn_tokens":
                out[k] += v
    out["coverage"] = cov
    return out


class Prices:
    def __init__(self, t0, t1):
        self.t0, self.t1 = t0, t1
        self.dir = RAW / "px"
        self.dir.mkdir(exist_ok=True)
        self.series = {}

    @staticmethod
    def _get(url):
        last = None
        for k in range(6):
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "bridge-limits-probe/1.0"}),
                                            timeout=60) as r:
                    return json.loads(r.read().decode())
            except Exception as e:  # noqa: BLE001
                last = e
                time.sleep(2 * (k + 1))
        raise RuntimeError(f"{url}: {last}")

    def _cached(self, name, url):
        p = self.dir / name
        if p.exists():
            return json.loads(p.read_text())
        j = self._get(url)
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


def reverted(trace, frame):
    """True if the frame or any of its ancestors errored (parity traces mark only the failing frame)."""
    ta = frame.get("traceAddress") or []
    errs = {tuple(x.get("traceAddress") or []) for x in trace if x.get("error")}
    return any(tuple(ta[:k]) in errs for k in range(len(ta) + 1))


def build():
    import numpy as np
    w = json.loads((RAW / "window_bsc.json").read_text())
    we = json.loads((RAW / "window_eth.json").read_text())
    st = json.loads((RAW / "bsc_state.json").read_text())
    H = st["handler"]
    start = max(w["b0"], T["qbridge_bsc_deploy_block"])
    bl = bsc_logs("bsc")
    sc = bsc_logs("bsch")
    xtx = json.loads((RAW / "bsc_exec_txs.json").read_text())
    dtx = json.loads((RAW / "eth_deposit_txs.json").read_text())
    dtr = json.loads((RAW / "eth_deposit_traces.json").read_text())
    bal = json.loads((RAW / "balances_bsc.json").read_text())
    fail_logs = json.loads((RAW / "failure_block_logs.json").read_text())

    def coverage_gaps(cov):
        gaps, expect = [], start
        for a, b in sorted(cov):
            if a != expect:
                gaps.append([expect, a - 1])
            expect = b + 1
        if expect <= w["b1"]:
            gaps.append([expect, w["b1"]])
        return gaps

    # ---- Ethereum deposits to BSC -------------------------------------------------------------------------------
    deps, dep_dup = {}, 0
    for lg in eth_deposits():
        if lg["topics"][0] != DEPOSIT:
            continue
        d = decode_deposit(lg)
        if d["dest"] != BSC_DOMAIN:
            continue
        d.update({"tx": lg["transactionHash"], "block": int(lg["blockNumber"], 16), "ts": int(lg["blockTimestamp"], 16)})
        if d["nonce"] in deps:
            dep_dup += 1
        deps[d["nonce"]] = d
    eth_handler = {rid: v["handler"] for rid, v in st["eth"].items()}

    def locked(d):
        """What deposit d locked on Ethereum: ETH the bridge forwarded to its handler (call trace), or tokens
        transferred from the depositor to the handler (receipt). Returns (amount locked or None, how, ETH sent
        into the bridge with the depositETH call)."""
        t = dtx[d["tx"]]
        if t["status"] != "0x1":
            return None, "deposit transaction failed", None
        eh = eth_handler.get(d["resource"], "")
        tr = dtr.get(d["tx"]) or []
        sent = sum(fr["value"] for fr in tr if fr["to"] == QE and fr["input"] == SEL_DEPOSIT_ETH and fr["from"] == d["user"]
                   and fr["callType"] == "call" and not reverted(tr, fr))
        eth_in = sum(fr["value"] for fr in tr if fr["from"] == QE and fr["to"] == eh and fr["callType"] == "call"
                     and fr["value"] and not reverted(tr, fr))
        if eth_in:
            how = "ETH forwarded to the Ethereum handler" + ("" if t["to"] == QE else " (deposit made through a contract)")
            return eth_in, how, sent
        tok = [lg for lg in t["logs"] if lg["topics"] and lg["topics"][0] == TRANSFER and len(lg["topics"]) == 3
               and addr_from_topic(lg["topics"][1]).lower() == d["user"] and addr_from_topic(lg["topics"][2]).lower() == eh]
        if tok:
            return sum(int(lg["data"], 16) for lg in tok), "token (WETH) transferred to the Ethereum handler", sent
        if not tr:
            return None, "no call trace", sent
        if d["amount"] == 0:
            return 0, "nothing (zero amount)", sent
        return None, ("deposit() with no token transfer and no ETH" if t["input"] == SEL_DEPOSIT else "no ETH reached the handler"), sent

    # ---- executed proposals on BSC --------------------------------------------------------------------------------
    events = [lg for lg in bl["bridge"] if lg["topics"][0] in (PROPOSAL_EVENT, PROPOSAL_EVENT_OLD)]
    upgrades = [iso(int(lg["blockTimestamp"], 16)) for lg in bl["bridge"] if lg["topics"][0] == UPGRADED]
    status_n = collections.Counter(("old" if lg["topics"][0] == PROPOSAL_EVENT_OLD else "new", decode_proposal(lg)["status"])
                                   for lg in events)
    failed_handler = [lg for lg in bl["bridge"] if lg["topics"][0] == FAILED_HANDLER]
    executed = []
    for lg in events:
        p = decode_proposal(lg)
        if p["status"] != 3:
            continue
        p.update({"tx": lg["transactionHash"], "block": int(lg["blockNumber"], 16), "ts": int(lg["blockTimestamp"], 16),
                  "logIndex": int(lg["logIndex"], 16), "version": "old" if lg["topics"][0] == PROPOSAL_EVENT_OLD else "new"})
        executed.append(p)
    executed.sort(key=lambda p: (p["block"], p["logIndex"]))
    missing_tx = [p["tx"] for p in executed if p["tx"] not in xtx]
    assert not missing_tx, f"{len(missing_tx)} executed-proposal transactions not fetched (run step txs)"

    used_mints = set()
    recs = []
    native_frames = []
    for p in executed:
        t = xtx[p["tx"]]
        # the executing call into the bridge
        calls = [decode_call(fr["input"]) for fr in t["trace"] if fr["to"] == QB and not reverted(t["trace"], fr)]
        calls = [c for c in calls if c and c["origin"] == p["origin"] and c["nonce"] == p["nonce"]]
        call = None
        for c in calls:
            if p["version"] == "new" and c["data"] == p["data"]:
                call = c
            elif p["version"] == "old" and keccak_hex(st["resources"].get(c["resource"], {}).get("handler", H)[2:] + c["data"]) == p["hash"]:
                call = c
        rec = {"tx": p["tx"], "block": p["block"], "ts": p["ts"], "nonce": p["nonce"], "origin": p["origin"],
               "version": p["version"], "call_found": call is not None}
        if call is None:
            rec["class"] = "no executing call matching the event"
            recs.append(rec)
            continue
        opt, amt, rcp = split_data(call["data"])
        tok = st["resources"].get(call["resource"], {}).get("token")
        rec.update({"resource": call["resource"], "option": opt, "amount": amt, "recipient": rcp, "token": tok,
                    "data": call["data"]})
        # value-bearing calls (native BNB) in the transaction, outside reverted frames; a call by another contract that
        # emitted Borrow(borrower = callee, amount = value) in the same transaction is a loan by a lending market
        for fr in t["trace"]:
            if fr["value"] and not reverted(t["trace"], fr):
                loan = any(lg["address"] == fr["from"] and lg["topics"] and lg["topics"][0] == BORROW
                           and ("0x" + lg["data"][26:66]).lower() == fr["to"] and int(lg["data"][66:130], 16) == fr["value"]
                           for lg in t["logs"])
                native_frames.append({"tx": p["tx"], "from": fr["from"], "to": fr["to"], "value": fr["value"],
                                      "by_release_point": fr["from"] in (QB, H, DELEGATE), "loan_by_market": loan,
                                      "to_recipient": fr["to"] == rcp})
        # the mint in the receipt
        mints = [lg for lg in t["logs"] if lg["topics"] and lg["topics"][0] == TRANSFER and len(lg["topics"]) == 3
                 and lg["topics"][1] == ZERO_T and (p["tx"], lg["logIndex"]) not in used_mints]
        m = [lg for lg in mints if lg["address"] == tok and int(lg["data"], 16) == amt]
        rec["mint"] = None
        if m:
            lgm = m[0]
            used_mints.add((p["tx"], lgm["logIndex"]))
            to = addr_from_topic(lgm["topics"][2]).lower()
            rec["mint"] = {"to": to, "amount": int(lgm["data"], 16), "token": lgm["address"]}
            if to == rcp:
                rec["route"] = "minted to the recipient"
            elif to == DELEGATE:
                fwd = [lg for lg in t["logs"] if lg["topics"] and lg["topics"][0] == TRANSFER and len(lg["topics"]) == 3
                       and lg["address"] == tok and addr_from_topic(lg["topics"][1]).lower() == DELEGATE
                       and int(lg["data"], 16) == amt]
                shares = [lg for lg in t["logs"] if lg["topics"] and lg["topics"][0] == TRANSFER and len(lg["topics"]) == 3
                          and lg["topics"][1] == ZERO_T and lg["address"] != tok
                          and addr_from_topic(lg["topics"][2]).lower() == rcp]
                rec["route"] = ("minted to the delegate contract, supplied to the market, shares to the recipient"
                                if fwd and shares else "minted to the delegate contract, recipient not confirmed")
                if fwd:
                    rec["market"] = addr_from_topic(fwd[0]["topics"][2]).lower()
            else:
                rec["route"] = "minted to another address"
        # backing on Ethereum
        d = deps.get(p["nonce"]) if p["origin"] == 0 else None
        if d is None:
            rec["class"] = "no Ethereum deposit with this nonce"
        elif d["resource"] != call["resource"]:
            rec["class"] = "Ethereum deposit with this nonce has another resource ID"
        elif d["data"] == call["data"]:
            rec["match"] = "data equal"
        elif d["option"] == opt and d["amount"] == amt and rcp == d["user"] and d["recipient"] != d["user"]:
            rec["match"] = "option and amount equal; recipient replaced by the depositor"
        else:
            rec["class"] = "Ethereum deposit with this nonce has other data"
        if "match" in rec:
            lk, how, sent = locked(d)
            rec.update({"deposit_tx": d["tx"], "deposit_ts": d["ts"], "deposit_user": d["user"], "locked": lk, "locked_how": how,
                        "eth_sent": sent, "fee": (sent - lk) if (sent and lk is not None and "ETH" in how) else None})
            if amt == 0:
                rec["class"] = "zero amount"
            elif not lk:
                rec["class"] = "deposit locked nothing (" + how + ")"
            elif lk != amt:
                rec["class"] = "deposit locked another amount"
            elif rec["mint"] is None:
                rec["class"] = "backed deposit, no mint of the amount found"
            elif rec["route"] not in ("minted to the recipient",
                                      "minted to the delegate contract, supplied to the market, shares to the recipient"):
                rec["class"] = "backed deposit, recipient not confirmed"
            else:
                rec["class"] = "legitimate"
        recs.append(rec)

    # ---- rows ---------------------------------------------------------------------------------------------------
    fail_to = {T.get("failure_recipient", "").lower()}
    excluded = collections.Counter()
    prices = Prices(w["ts_b0"], w["ts_b1"])
    rows, checks, fees = [], collections.Counter(), collections.Counter()
    for rec in recs:
        if rec.get("class") != "legitimate":
            continue
        if rec["recipient"] in fail_to or rec.get("deposit_user") in fail_to:
            excluded["to or from the failure's recipient"] += 1
            rec["class"] = "excluded: failure recipient"
            continue
        if not (w["t_start"] <= rec["ts"] <= w["t_end"]):
            excluded["outside the window"] += 1
            rec["class"] = "excluded: outside the window"
            continue
        ok = rec["mint"]["amount"] == rec["locked"] == rec["amount"]
        checks["mint equals the amount locked on Ethereum (wei)" if ok else "mint differs from the amount locked"] += 1
        checks["locked as " + rec["locked_how"]] += 1
        fees[rec["fee"]] += 1
        amt = rec["mint"]["amount"] / 1e18
        p, src = prices.price("coingecko:ethereum", rec["ts"])
        rows.append({"ts": rec["ts"], "ts_utc": iso(rec["ts"]), "leg": LEG, "asset": "xETH", "amount": amt,
                     "usd": None if p is None else amt * p, "kind": "erc20", "priced": "yes" if p is not None else "no",
                     "src": src, "to": rec["recipient"], "nonce": rec["nonce"], "route": rec["route"]})
    rows.sort(key=lambda r: r["ts"])
    with open(HERE / f"{EID}.csv", "w", newline="", encoding="utf-8") as f:
        wr = csv.writer(f)
        wr.writerow(["ts_utc", "leg", "asset", "amount", "usd", "kind", "priced"])
        for r in rows:
            wr.writerow([r["ts_utc"], r["leg"], r["asset"], repr(r["amount"]), "" if r["usd"] is None else f"{r['usd']:.2f}",
                         r["kind"], r["priced"]])

    # xETH has no DefiLlama series of its own
    xh, xd = prices.load("bsc:" + XETH)

    # ---- completeness -------------------------------------------------------------------------------------------
    xmint = bl["xeth_mint"]
    xmint_in_exec = sum(1 for lg in xmint if lg["transactionHash"] in xtx)
    xmint_consumed = sum(1 for lg in xmint if (lg["transactionHash"], int(lg["logIndex"], 16)) in used_mints)
    burn_tokens = sorted(t for t, v in st["tokens"].items() if v["burnList"])
    other_burn_mints = [lg for lg in sc["burn_token_mint"] if lg["address"].lower() != XETH]
    xeth_burns = [lg for lg in sc["burn_token_burn"] if lg["address"].lower() == XETH]
    sc_xmint = [lg for lg in sc["burn_token_mint"] if lg["address"].lower() == XETH]
    mint_sum = sum(int(lg["data"], 16) for lg in xmint)
    burn_sum = sum(int(lg["data"], 16) for lg in xeth_burns)
    s0, s1 = bal[str(start - 1)]["xeth_supply"], bal[str(w["b1"])]["xeth_supply"]
    # delegate contract: every xETH it receives leaves in the same transaction
    d_in = collections.Counter()
    d_out = collections.Counter()
    for lg in bl["mint_to_handler"]:
        d_in[lg["transactionHash"]] += int(lg["data"], 16)
    for lg in bl["from_handler"]:
        d_out[lg["transactionHash"]] += int(lg["data"], 16)
    delegate_unforwarded = sum(1 for h in d_in if d_out.get(h, 0) != d_in[h])
    # BSC deposits (burns for the reverse direction), for the supply check
    bsc_dep = [decode_deposit(lg) for lg in bl["bridge"] if lg["topics"][0] == DEPOSIT]
    # failure block: first executed proposal after the window
    fb = [decode_proposal(lg) for lg in fail_logs if lg["topics"][0] in (PROPOSAL_EVENT, PROPOSAL_EVENT_OLD)]
    # Ethereum deposits never executed on BSC before the window end: highest status reached by a proposal with the
    # same nonce and data (or data hash), and whether its transaction carried a failed handler call
    fh_tx = {lg["transactionHash"] for lg in failed_handler}
    executed_nonces = {r["nonce"] for r in recs if r.get("match")}
    not_exec = {}
    for n, d in sorted(deps.items()):
        if n in executed_nonces:
            continue
        hit = []
        for lg in events:
            q = decode_proposal(lg)
            if q["origin"] != 0 or q["nonce"] != n:
                continue
            if q.get("data") == d["data"] or q.get("hash") == keccak_hex(st["resources"].get(d["resource"], {}).get("handler", H)[2:] + d["data"]):
                hit.append((q["status"], lg["transactionHash"] in fh_tx))
        not_exec[n] = {"deposit_utc": iso(d["ts"]), "amount": d["amount"] / 1e18, "max_status_on_bsc": max((s for s, _ in hit), default=0),
                       "failed_handler_call": any(f for _, f in hit), "locked": locked(d)[1]}
    # price series of the burn-list tokens on DefiLlama (BSC contract keys)
    series_points = {st["tokens"][t]["symbol"]: [len(x) for x in prices.load("bsc:" + t)] for t in burn_tokens}

    cls = collections.Counter(r.get("class") for r in recs)
    unb = [r for r in recs if r.get("class") not in ("legitimate", "zero amount", "excluded: failure recipient",
                                                      "excluded: outside the window")]
    unb_mint = [r for r in unb if r.get("mint")]
    other_moves = collections.Counter()
    for r in recs:
        if r.get("mint") is None:
            t = xtx[r["tx"]]
            for lg in t["logs"]:
                if lg["topics"] and lg["topics"][0] == TRANSFER and len(lg["topics"]) == 3:
                    kind = "mint" if lg["topics"][1] == ZERO_T else "transfer"
                    other_moves[(r.get("class"), lg["address"], kind)] += 1

    # ---- summary statistics -------------------------------------------------------------------------------------
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
    t_dep = min(int(lg["blockTimestamp"], 16) for lg in bl["bridge"] if int(lg["blockNumber"], 16) == T["qbridge_bsc_deploy_block"])
    days_live = [d for d in days_all if d >= t_dep // 86400 * 86400]
    day_vals = [day.get(d, 0.0) for d in days_all]
    day_vals_live = [day.get(d, 0.0) for d in days_live]
    ts_sorted = sorted(r["ts"] for r in rows)
    # pauses over two days, with what happened inside them on either side (BSC proposal events of any status and
    # version, Ethereum deposits to BSC); open intervals, so the releases at the ends are not counted
    ev = [(int(lg["blockTimestamp"], 16), decode_proposal(lg)) for lg in events]
    nonce_of_release = {r["ts"]: r["nonce"] for r in rows}
    gaps = []
    for a, b in zip([t_dep] + ts_sorted, ts_sorted + [w["t_end"]]):
        if b - a > 2 * 86400:
            gaps.append([iso(a), iso(b), round((b - a) / 86400, 1),
                         {"bsc_proposal_events": sum(1 for x, _ in ev if a < x < b),
                          "bsc_executed": sum(1 for x, q in ev if a < x < b and q["status"] == 3),
                          "eth_deposit_nonces": sorted(n for n, d in deps.items() if a < d["ts"] < b),
                          "nonce_released_at_end": nonce_of_release.get(b)}])
    recip = collections.Counter()
    for r in rows:
        recip[r["to"]] += r["usd"] or 0.0
    usd_arr = np.array([r["usd"] for r in pr]) if pr else np.array([0.0])
    amt_arr = np.array([r["amount"] for r in rows]) if rows else np.array([0.0])
    big = sorted(pr, key=lambda r: -r["usd"])[:5]
    eth_px = sorted({round(r["usd"] / r["amount"], 2) for r in pr if r["amount"]})
    s = {
        "id": EID, "window_utc": [iso(w["t_start"]), iso(w["t_end"])], "window_blocks_bsc": [w["b0"], w["b1"]],
        "bridge_deployed_utc": iso(t_dep), "bridge_deploy_block": T["qbridge_bsc_deploy_block"],
        "history_blocks": [start, w["b1"]], "history_days": round((w["t_end"] + 1 - t_dep) / 86400, 2),
        "ethereum_blocks": [we["e0"], we["e1"]],
        "chunks_bsc": len(bl["coverage"]), "gaps_bsc": coverage_gaps(bl["coverage"]),
        "chunks_scan": len(sc["coverage"]), "gaps_scan": coverage_gaps(sc["coverage"]),
        "handler_registered": "see bsc_state.json",
        "distinct_nonzero_handlers_read": len({h for v in st["resources"].values() for h in v["handler_by_block"].values()
                                               if int(h, 16)}),
        "resources_unregistered_at_first_execution": [k[-12:] for k, v in st["resources"].items()
                                                      if not int(v["handler_by_block"][str(min(map(int, v["handler_by_block"])))], 16)],
        "resources": {k[-12:]: {"token_symbol": st["tokens"][v["token"]]["symbol"], "burnList": st["tokens"][v["token"]]["burnList"]}
                      for k, v in st["resources"].items()},
        "proxy_upgrades_utc": upgrades,
        "proposal_events_by_version_status": {f"{a}:{b}": n for (a, b), n in sorted(status_n.items())},
        "failed_handler_executions": len(failed_handler),
        "executed_proposals": len(executed), "executing_call_found": sum(1 for r in recs if r["call_found"]),
        "classes": dict(cls),
        "match_kinds": dict(collections.Counter(r.get("match") for r in recs if r.get("match"))),
        "routes_legit": dict(collections.Counter(r["route"] for r in rows)),
        "per_row_checks": dict(checks),
        "deposit_fee_wei_counts": {str(k): v for k, v in fees.items()},
        "ethereum_deposits_to_bsc": len(deps), "ethereum_deposit_nonce_duplicates": dep_dup,
        "ethereum_deposit_nonces": [min(deps), max(deps)] if deps else None,
        "ethereum_deposits_after_window_end_on_bsc": sorted(n for n, d in deps.items() if d["ts"] > w["t_end"]),
        "ethereum_deposits_not_executed": not_exec,
        "unbacked_executed": len(unb), "unbacked_with_mint": len(unb_mint),
        "unbacked_detail": [{"ts_utc": iso(r["ts"]), "nonce": r["nonce"], "version": r["version"], "class": r.get("class"),
                             "token": (st["tokens"].get(r.get("token") or "", {}) or {}).get("symbol"),
                             "amount": (r["mint"]["amount"] if r.get("mint") else (r.get("amount") or 0)) / 1e18,
                             "minted_to_recipient_in_data": bool(r.get("mint")) and r["mint"]["to"] == r.get("recipient")}
                            for r in unb_mint],
        "unbacked_with_mint_by_token": dict(collections.Counter(
            (st["tokens"].get(r.get("token") or "", {}) or {}).get("symbol") for r in unb_mint)),
        "unbacked_with_mint_amount_by_token": {sym: sum(r["mint"]["amount"] for r in unb_mint if (
            st["tokens"].get(r.get("token") or "", {}) or {}).get("symbol") == sym) / 1e18
            for sym in {(st["tokens"].get(r.get("token") or "", {}) or {}).get("symbol") for r in unb_mint}},
        "unbacked_first_last_utc": [iso(min(r["ts"] for r in unb)), iso(max(r["ts"] for r in unb))] if unb else None,
        "unbacked_without_mint_by_token_moves": {f"{a}|{b[:8]}|{c}": n for (a, b, c), n in other_moves.items()},
        "zero_amount": [{"ts_utc": iso(r["ts"]), "nonce": r["nonce"]} for r in recs if r.get("class") == "zero amount"],
        "xeth_mints_life": len(xmint), "xeth_mints_in_executed_tx": xmint_in_exec, "xeth_mints_matched": xmint_consumed,
        "xeth_mints_scan_vs_burnscan": [len(xmint), len(sc_xmint)],
        "xeth_supply": {"start": s0 / 1e18, "end": s1 / 1e18, "mints": mint_sum / 1e18, "burns": burn_sum / 1e18,
                        "residual": (s0 + mint_sum - burn_sum - s1) / 1e18, "n_burns": len(xeth_burns)},
        "bsc_deposits": len(bsc_dep), "bsc_deposits_by_resource": dict(collections.Counter(d["resource"][-12:] for d in bsc_dep)),
        "bsc_deposit_xeth_amount": sum(d["amount"] or 0 for d in bsc_dep if st["resources"].get(d["resource"], {}).get("token") == XETH) / 1e18,
        "burn_tokens": len(burn_tokens), "other_burn_token_mints": len(other_burn_mints),
        "other_burn_token_mints_in_exec_tx": sum(1 for lg in other_burn_mints if lg["transactionHash"] in xtx),
        "mint_to_handler_scan": len(sc["mint_to_reg"]), "from_handler_scan": len(sc["from_reg"]),
        "from_handler_tokens": dict(collections.Counter(lg["address"].lower()[:10] for lg in sc["from_reg"])),
        "mint_to_delegate_scan": len(bl["mint_to_handler"]), "from_delegate_scan": len(bl["from_handler"]),
        "delegate_tx_not_forwarded": delegate_unforwarded,
        "native_value_frames_in_executed_tx": len(native_frames),
        "native_value_frames_by_bridge_handler_or_delegate": sum(1 for x in native_frames if x["by_release_point"]),
        "native_value_frames_other": {
            "n": sum(1 for x in native_frames if not x["by_release_point"]),
            "loans_by_lending_market_to_recipient": sum(1 for x in native_frames if not x["by_release_point"]
                                                         and x["loan_by_market"] and x["to_recipient"]),
            "bnb": sum(x["value"] for x in native_frames if not x["by_release_point"]) / 1e18,
            "values_bnb": sorted({x["value"] / 1e18 for x in native_frames if not x["by_release_point"]})},
        "balances": {k: {kk: (vv / 1e18) for kk, vv in v.items()} for k, v in bal.items()},
        "failure_block_proposals": [{"nonce": x["nonce"], "status": x["status"]} for x in fb],
        "xeth_series_points": [len(xh), len(xd)],
        "burn_token_series_points_hourly_daily": series_points,
        "excluded": dict(excluded),
        "n_rows": len(rows), "n_priced": len(pr), "share_priced": len(pr) / len(rows) if rows else None,
        "usd_total": float(sum(r["usd"] for r in pr)), "eth_total": float(sum(r["amount"] for r in rows)),
        "price_sources": dict(collections.Counter(r["src"] for r in pr)),
        "eth_price_range": [eth_px[0], eth_px[-1]] if eth_px else None,
        "first_release": iso(ts_sorted[0]) if ts_sorted else None, "last_release": iso(ts_sorted[-1]) if ts_sorted else None,
        "days_with_release": len({r["ts"] // 86400 for r in rows}), "n_days_window": len(days_all), "n_days_live": len(days_live),
        "largest": [{"ts_utc": r["ts_utc"], "amount": r["amount"], "usd": r["usd"], "route": r["route"]} for r in big],
        "usd_quantiles": {q: float(np.quantile(usd_arr, q)) for q in (0.5, 0.9, 0.99)},
        "eth_quantiles": {q: float(np.quantile(amt_arr, q)) for q in (0.5, 0.9, 0.99)},
        "busiest_hour_usd": (lambda h: {"hour_utc": iso(h), "usd": hour[h], "n": hour_n[h]})(max(hour, key=hour.get)) if hour else None,
        "busiest_hour_count": (lambda h: {"hour_utc": iso(h), "n": hour_n[h], "usd": hour.get(h, 0.0)})(max(hour_n, key=hour_n.get)) if hour_n else None,
        "busiest_day_usd": (lambda d: {"day_utc": iso(d)[:10], "usd": day[d], "n": day_n[d]})(max(day, key=day.get)) if day else None,
        "busiest_day_count": (lambda d: {"day_utc": iso(d)[:10], "n": day_n[d], "usd": day.get(d, 0.0)})(max(day_n, key=day_n.get)) if day_n else None,
        "daily_usd_quantiles_150d": {q: float(np.quantile(day_vals, q)) for q in (0.5, 0.9, 0.99, 1.0)},
        "daily_usd_quantiles_live": {q: float(np.quantile(day_vals_live, q)) for q in (0.5, 0.9, 0.99, 1.0)},
        "daily_usd_mean_150d": float(sum(r["usd"] for r in pr) / 150.0),
        "daily_usd_mean_live": float(sum(r["usd"] for r in pr) / max(1e-9, (w["t_end"] + 1 - t_dep) / 86400)),
        "gaps_over_2d_since_deployment": gaps,
        "n_recipients": len(recip),
        "top_recipient_usd_shares": [round(v / max(1e-9, sum(recip.values())), 4) for _, v in recip.most_common(5)],
    }
    (RAW / "summary.json").write_text(json.dumps(s, indent=1, default=str))
    # per-proposal detail stays in the raw cache (addresses and hashes)
    (RAW / "executed_detail.json").write_text(json.dumps(recs, indent=1, default=str))
    (RAW / "top_recipients.json").write_text(json.dumps(recip.most_common(10), indent=1))
    print(json.dumps(s, indent=1, default=str))


if __name__ == "__main__":
    {"bsc": collect_bsc, "eth": collect_eth, "scan": collect_scan, "txs": collect_txs, "build": build}[sys.argv[1]]()
