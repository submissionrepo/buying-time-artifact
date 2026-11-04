"""CCIP token releases and their source messages: decoding shared by the shadow-run collector and the live monitor.

The configured pair, its routers, ramps and token pools come from raw/ccip/targets.json (written by
ccip_collect.py targets). Rpc objects follow incidents/rpc.Rpc (call, logs, receipt, block_ts, eth_call); a
`receipts(list)` batch method and a `block_ts_many(list)` method are used when the object has them.

Public interface (the live monitor imports these):
  new_releases(rpc_dst, dst_chain, from_block, to_block, diag=None) -> list of release dicts, sorted by
      (block, log index): every message from the paired source chain executed successfully on dst_chain in the
      block range whose execution released or minted tokens through a token pool, one dict per token.
  find_source(rpc_src, src_chain, release) -> source dict or None: the OnRamp's send event with the release's
      messageId on src_chain (located by the per-lane sequence number, however old), decoded, with the value check
      (did the source token pool lock or burn the amount in the same transaction) and the agreement of amount,
      token and recipient with the release.
Building blocks used by both (the collector calls them directly on bulk-scanned logs):
  exec_events, releases_from_receipt, decode_send_log, source_from_log, value_check, compare.

Contract families (topic layouts checked against verified ABIs and on-chain logs, 2026-10-16):
  1.5   EVM2EVMOnRamp CCIPSendRequested(EVM2EVMMessage) (no indexed field; one contract per lane);
        EVM2EVMOffRamp ExecutionStateChanged(uint64 indexed seq, bytes32 indexed messageId, uint8 state, bytes).
        The 1.2 ramps share these layouts.
  1.6   OnRamp CCIPMessageSent(uint64 indexed destSel, uint64 indexed seq, EVM2AnyRampMessage);
        OffRamp ExecutionStateChanged(uint64 indexed srcSel, uint64 indexed seq, bytes32 indexed messageId,
        bytes32 messageHash, uint8 state, bytes, uint256 gasUsed).
  2.0   OnRamp CCIPMessageSent(uint64 indexed destSel, address indexed sender, bytes32 indexed messageId,
        address feeToken, uint256 tokenAmountBeforeTokenPoolFees, bytes encodedMessage, Receipt[], bytes[]);
        the message id is keccak256(encodedMessage) (MessageV1Codec);
        OffRamp ExecutionStateChanged(uint64 indexed srcSel, uint64 indexed messageNumber, bytes32 indexed
        messageId, uint8 state, bytes).
  Token pools: 1.5 Locked/Burned/Released/Minted; 1.6 LockedOrBurned/ReleasedOrMinted with the token indexed;
  2.0 the same two events with the token in the data. Topic hashes depend only on the types, so the layout is
  told apart by the number of topics.
Execution states: 0 untouched, 1 in progress, 2 success, 3 failure. Within one transaction the logs of a message's
execution (pool release, token transfers, receiver callback) precede its ExecutionStateChanged log, and on the
source side the logs of a send (transfer into the pool, lock or burn) precede its send event.
"""
import json
import pathlib

from Crypto.Hash import keccak

HERE = pathlib.Path(__file__).resolve().parent
RAW = HERE / "raw" / "ccip"
TARGETS = RAW / "targets.json"

ZERO = "0x" + "0" * 40
DEAD = "0x000000000000000000000000000000000000dead"
STATE = {0: "untouched", 1: "in_progress", 2: "success", 3: "failure"}


def keccak_hex(b):
    h = keccak.new(digest_bits=256)
    h.update(b)
    return "0x" + h.hexdigest()


def topic0(sig):
    return keccak_hex(sig.encode())


SIG = {
    "exec15": "ExecutionStateChanged(uint64,bytes32,uint8,bytes)",
    "exec16": "ExecutionStateChanged(uint64,uint64,bytes32,bytes32,uint8,bytes,uint256)",
    "exec20": "ExecutionStateChanged(uint64,uint64,bytes32,uint8,bytes)",
    "sent15": "CCIPSendRequested((uint64,address,address,uint64,uint256,bool,uint64,address,uint256,bytes,"
              "(address,uint256)[],bytes[],bytes32))",
    "sent16": "CCIPMessageSent(uint64,uint64,((bytes32,uint64,uint64,uint64,uint64),address,bytes,bytes,bytes,"
              "address,uint256,uint256,(address,bytes,bytes,uint256,bytes)[]))",
    "sent20": "CCIPMessageSent(uint64,address,bytes32,address,uint256,bytes,(address,uint32,uint32,uint256,bytes)[],"
              "bytes[])",
    "transfer": "Transfer(address,address,uint256)",
    "locked": "Locked(address,uint256)",
    "burned": "Burned(address,uint256)",
    "released": "Released(address,address,uint256)",
    "minted": "Minted(address,address,uint256)",
    "lob": "LockedOrBurned(uint64,address,address,uint256)",
    "rom": "ReleasedOrMinted(uint64,address,address,address,uint256)",
    "onramp_set": "OnRampSet(uint64,address)",
    "offramp_added": "OffRampAdded(uint64,address)",
    "offramp_removed": "OffRampRemoved(uint64,address)",
}
TOPIC = {k: topic0(v) for k, v in SIG.items()}
EXEC_TOPICS = {TOPIC["exec15"]: "1.5", TOPIC["exec16"]: "1.6", TOPIC["exec20"]: "2.0"}
SENT_TOPICS = {TOPIC["sent15"]: "1.5", TOPIC["sent16"]: "1.6", TOPIC["sent20"]: "2.0"}
RELEASE_TOPICS = {TOPIC["rom"], TOPIC["released"], TOPIC["minted"]}
LOCK_TOPICS = {TOPIC["lob"], TOPIC["locked"], TOPIC["burned"]}

# function selectors
FN = {k: keccak_hex(v.encode())[:10] for k, v in {
    "typeAndVersion": "typeAndVersion()", "getOnRamp": "getOnRamp(uint64)", "getOffRamps": "getOffRamps()",
    "getStaticConfig": "getStaticConfig()", "getSourceChainConfig": "getSourceChainConfig(uint64)",
    "nextSeq15": "getExpectedNextSequenceNumber()", "nextSeq16": "getExpectedNextSequenceNumber(uint64)",
    "nextNum20": "getExpectedNextMessageNumber(uint64)", "decimals": "decimals()", "symbol": "symbol()",
    "getPool": "getPool(address)", "getToken": "getToken()"}.items()}


def family_of(type_and_version):
    """'EVM2EVMOffRamp 1.5.0' -> '1.5'; 'OffRamp 1.6.0' -> '1.6'; 'OffRamp 2.0.0' -> '2.0'; 1.2 shares 1.5's layout."""
    v = (type_and_version or "").split()[-1] if type_and_version else ""
    if v.startswith("1.2") or v.startswith("1.5"):
        return "1.5"
    if v.startswith("1.6"):
        return "1.6"
    if v.startswith("2."):
        return "2.0"
    return None


# ---------------------------------------------------------------------------------------------------- ABI decoding
def _parse_type(s):
    s = s.strip()
    if s.endswith("]"):
        i = s.rfind("[")
        n = s[i + 1:-1]
        return ("array", _parse_type(s[:i]), int(n) if n else None)
    if s.startswith("("):
        parts, depth, cur = [], 0, ""
        for ch in s[1:-1]:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            if ch == "," and depth == 0:
                parts.append(cur)
                cur = ""
            else:
                cur += ch
        if cur:
            parts.append(cur)
        return ("tuple", [_parse_type(p) for p in parts])
    if s in ("address", "bool", "bytes", "string"):
        return (s,)
    if s.startswith("bytes"):
        return ("bytesN", int(s[5:]))
    if s.startswith("uint"):
        return ("uint",)
    if s.startswith("int"):
        return ("int",)
    raise ValueError(f"type {s}")


def _dynamic(t):
    if t[0] in ("bytes", "string"):
        return True
    if t[0] == "array":
        return t[2] is None or _dynamic(t[1])
    if t[0] == "tuple":
        return any(_dynamic(c) for c in t[1])
    return False


def _head(t):
    if _dynamic(t):
        return 32
    if t[0] == "tuple":
        return sum(_head(c) for c in t[1])
    if t[0] == "array":
        return t[2] * _head(t[1])
    return 32


def _word(data, at):
    return int.from_bytes(data[at:at + 32], "big")


def _value(t, data, at):
    k = t[0]
    if k == "uint":
        return _word(data, at)
    if k == "int":
        v = _word(data, at)
        return v - (1 << 256) if v >> 255 else v
    if k == "address":
        return "0x" + data[at + 12:at + 32].hex()
    if k == "bool":
        return _word(data, at) != 0
    if k == "bytesN":
        return "0x" + data[at:at + t[1]].hex()
    if k in ("bytes", "string"):
        n = _word(data, at)
        b = data[at + 32:at + 32 + n]
        return "0x" + b.hex() if k == "bytes" else b.decode(errors="replace")
    if k == "tuple":
        return _tuple(t[1], data, at)
    if k == "array":
        if t[2] is None:
            return _tuple([t[1]] * _word(data, at), data, at + 32)
        return _tuple([t[1]] * t[2], data, at)
    raise ValueError(k)


def _tuple(types, data, start):
    out, pos = [], start
    for t in types:
        if _dynamic(t):
            out.append(_value(t, data, start + _word(data, pos)))
            pos += 32
        else:
            out.append(_value(t, data, pos))
            pos += _head(t)
    return out


def abi_decode(types, data):
    """Decode abi.encode(v1, v2, ...) of the given type strings; data is a 0x-hex string or bytes."""
    if isinstance(data, str):
        data = bytes.fromhex(data[2:] if data.startswith("0x") else data)
    return _tuple([_parse_type(t) for t in types], data, 0)


def _b(h):
    return bytes.fromhex(h[2:] if h.startswith("0x") else h)


def _addr_from_bytes(h):
    """An EVM address given as abi.encode(address) (32 bytes) or as 20 raw bytes; None if neither."""
    b = _b(h) if isinstance(h, str) else h
    if len(b) == 20:
        return "0x" + b.hex()
    if len(b) == 32 and b[:12] == b"\x00" * 12:
        return "0x" + b[12:].hex()
    return None


def _taddr(t):
    return ("0x" + t[-40:]).lower()


def _lg(lg, key):
    v = lg.get(key)
    return int(v, 16) if isinstance(v, str) else v


# ------------------------------------------------------------------------------------------------------ configuration
_CFG = {}


def load_targets(path=TARGETS):
    p = str(path)
    if p not in _CFG:
        _CFG[p] = json.loads(pathlib.Path(path).read_text())
    return _CFG[p]


def other_chain(cfg, chain):
    a, b = cfg["pair"]["chains"]
    return b if chain == a else a


def selector(cfg, chain):
    return int(cfg["chains"][chain]["selector"])


def offramps(cfg, dst_chain):
    """OffRamps on dst_chain registered for the paired source chain at any time in the period (and later ones the
    monitor discovered and added to the in-memory config)."""
    return cfg["chains"][dst_chain]["offramps"]


def onramps(cfg, src_chain):
    return cfg["chains"][src_chain]["onramps"]


def _call_str(rpc, to, block="latest"):
    h = rpc.eth_call(to, FN["typeAndVersion"], block)
    try:
        return abi_decode(["string"], h)[0]
    except Exception:  # noqa: BLE001
        return None


def discover_ramps(rpc, chain, block, cfg=None):
    """Router state at `block` on `chain`: the OnRamp toward the paired chain and the OffRamps registered for it.
    Ramps not yet in the config are added to it in memory (with type and version and linked OnRamp), so the live
    monitor follows a ramp upgrade without a new targets file. Returns (onramp, [offramps])."""
    cfg = cfg or load_targets()
    ch = cfg["chains"][chain]
    oth = other_chain(cfg, chain)
    osel = selector(cfg, oth)
    onr = _taddr(rpc.eth_call(ch["router"], FN["getOnRamp"] + format(osel, "064x"), block))
    offs = []
    for sel, a in abi_decode(["(uint64,address)[]"], rpc.eth_call(ch["router"], FN["getOffRamps"], block))[0]:
        if sel == osel:
            offs.append(a.lower())
    known_on = {r["address"] for r in ch["onramps"]}
    if onr != ZERO and onr not in known_on:
        tv = _call_str(rpc, onr, block)
        ch["onramps"].append({"address": onr, "type_and_version": tv, "family": family_of(tv), "dest": oth,
                              "discovered_at_block": block})
    known_off = {r["address"] for r in ch["offramps"]}
    for a in offs:
        if a not in known_off:
            tv = _call_str(rpc, a, block)
            ch["offramps"].append({"address": a, "type_and_version": tv, "family": family_of(tv), "source": oth,
                                   "linked_onramps": linked_onramps(rpc, a, family_of(tv), osel, block),
                                   "discovered_at_block": block})
    return onr, offs


def linked_onramps(rpc, offramp, family, src_sel, block="latest"):
    """The source-chain OnRamp(s) an OffRamp accepts messages from."""
    if family == "1.5":
        cfgw = abi_decode(["(address,uint64,uint64,address,address,address,address)"],
                          rpc.eth_call(offramp, FN["getStaticConfig"], block))[0]
        return [cfgw[3].lower()]
    if family == "1.6":
        c = abi_decode(["(address,bool,uint64,bool,bytes)"],
                       rpc.eth_call(offramp, FN["getSourceChainConfig"] + format(src_sel, "064x"), block))[0]
        a = _addr_from_bytes(c[4])
        return [a] if a else []
    if family == "2.0":
        c = abi_decode(["(address,bool,bytes[],address[],address[])"],
                       rpc.eth_call(offramp, FN["getSourceChainConfig"] + format(src_sel, "064x"), block))[0]
        return [a for a in (_addr_from_bytes(x) for x in c[2]) if a]
    return []


_META = {}


def token_meta(rpc, chain, token, cfg=None):
    """(symbol, decimals) of a token: from the targets token table, else from the token contract."""
    if not token:
        return "?", None
    token = token.lower()
    key = (chain, token)
    if key in _META:
        return _META[key]
    cfg = cfg or load_targets()
    t = (cfg.get("token_index") or {}).get(chain, {}).get(token)
    if t:
        _META[key] = (t["symbol"], int(t["decimals"]))
        return _META[key]
    sym, dec = "?", None
    try:
        dec = int(rpc.eth_call(token, FN["decimals"]), 16)
    except Exception:  # noqa: BLE001
        pass
    try:
        h = rpc.eth_call(token, FN["symbol"])
        raw = _b(h)
        sym = abi_decode(["string"], raw)[0] if len(raw) >= 96 else raw.rstrip(b"\x00").decode(errors="ignore")
    except Exception:  # noqa: BLE001
        pass
    _META[key] = (sym, dec)
    return _META[key]


# ------------------------------------------------------------------------------------------------- event decoding
def exec_event(lg):
    """ExecutionStateChanged of any family -> dict, or None for another log."""
    t = lg["topics"]
    fam = EXEC_TOPICS.get(t[0]) if t else None
    if fam is None:
        return None
    d = _b(lg["data"])
    if fam == "1.5":
        src_sel, seq, mid = None, int(t[1], 16), t[2]
        state, ret = abi_decode(["uint8", "bytes"], d)
    elif fam == "1.6":
        src_sel, seq, mid = int(t[1], 16), int(t[2], 16), t[3]
        _h, state, ret, _g = abi_decode(["bytes32", "uint8", "bytes", "uint256"], d)
    else:
        src_sel, seq, mid = int(t[1], 16), int(t[2], 16), t[3]
        state, ret = abi_decode(["uint8", "bytes"], d)
    return {"family": fam, "offramp": lg["address"].lower(), "source_selector": src_sel, "seq": seq,
            "message_id": mid.lower(), "state": state, "block": _lg(lg, "blockNumber"),
            "log_index": _lg(lg, "logIndex"), "tx": lg["transactionHash"].lower(),
            "return_data": ret[:2 + 2 * 260] if state == 3 else None}


def transfer_event(lg):
    t = lg["topics"]
    if len(t) != 3 or t[0] != TOPIC["transfer"] or len(_b(lg["data"])) != 32:
        return None
    return {"token": lg["address"].lower(), "from": _taddr(t[1]), "to": _taddr(t[2]), "value": int(lg["data"], 16),
            "log_index": _lg(lg, "logIndex")}


def pool_release_event(lg):
    """Released / Minted (1.5 pools) or ReleasedOrMinted (1.6: token indexed; 2.0: token in data)."""
    t = lg["topics"]
    if not t or t[0] not in RELEASE_TOPICS:
        return None
    d = _b(lg["data"])
    base = {"pool": lg["address"].lower(), "log_index": _lg(lg, "logIndex")}
    if t[0] == TOPIC["rom"]:
        if len(t) == 3:
            w = abi_decode(["address", "address", "uint256"], d)
            return {**base, "event": "ReleasedOrMinted", "remote_selector": int(t[1], 16), "token": _taddr(t[2]),
                    "sender": w[0], "recipient": w[1], "amount": w[2]}
        if len(t) == 2:
            w = abi_decode(["address", "address", "address", "uint256"], d)
            return {**base, "event": "ReleasedOrMinted", "remote_selector": int(t[1], 16), "token": w[0],
                    "sender": w[1], "recipient": w[2], "amount": w[3]}
        return None
    if len(t) != 3 or len(d) != 32:
        return None
    return {**base, "event": "Released" if t[0] == TOPIC["released"] else "Minted", "remote_selector": None,
            "token": None, "sender": _taddr(t[1]), "recipient": _taddr(t[2]), "amount": _word(d, 0)}


def pool_lock_event(lg):
    """Locked / Burned (1.5 pools) or LockedOrBurned (1.6: token indexed; 2.0: token in data)."""
    t = lg["topics"]
    if not t or t[0] not in LOCK_TOPICS:
        return None
    d = _b(lg["data"])
    base = {"pool": lg["address"].lower(), "log_index": _lg(lg, "logIndex")}
    if t[0] == TOPIC["lob"]:
        if len(t) == 3:
            w = abi_decode(["address", "uint256"], d)
            return {**base, "event": "LockedOrBurned", "remote_selector": int(t[1], 16), "token": _taddr(t[2]),
                    "sender": w[0], "amount": w[1]}
        if len(t) == 2:
            w = abi_decode(["address", "address", "uint256"], d)
            return {**base, "event": "LockedOrBurned", "remote_selector": int(t[1], 16), "token": w[0],
                    "sender": w[1], "amount": w[2]}
        return None
    if len(t) != 2 or len(d) != 32:
        return None
    return {**base, "event": "Locked" if t[0] == TOPIC["locked"] else "Burned", "remote_selector": None,
            "token": None, "sender": _taddr(t[1]), "amount": _word(d, 0)}


def parse_message_v1(enc):
    """MessageV1Codec (CCIP 2.0) -> dict. Token transfer: at most one (MAX_NUMBER_OF_TOKENS = 1)."""
    b = _b(enc) if isinstance(enc, str) else enc
    if b[0] != 1:
        raise ValueError(f"MessageV1 version {b[0]}")
    m = {"source_selector": int.from_bytes(b[1:9], "big"), "dest_selector": int.from_bytes(b[9:17], "big"),
         "seq": int.from_bytes(b[17:25], "big"), "execution_gas_limit": int.from_bytes(b[25:29], "big"),
         "ccip_receive_gas_limit": int.from_bytes(b[29:33], "big"), "finality": "0x" + b[33:37].hex()}
    o = 69

    def var(o, nlen):
        n = int.from_bytes(b[o:o + nlen], "big")
        return b[o + nlen:o + nlen + n], o + nlen + n

    onramp, o = var(o, 1)
    offramp, o = var(o, 1)
    sender, o = var(o, 1)
    receiver, o = var(o, 1)
    _blob, o = var(o, 2)
    tt, o = var(o, 2)
    data, o = var(o, 2)
    if o != len(b):
        raise ValueError("MessageV1 trailing bytes")
    m.update({"onramp": _addr_from_bytes(onramp), "offramp": _addr_from_bytes(offramp),
              "sender": _addr_from_bytes(sender), "receiver": _addr_from_bytes(receiver),
              "receiver_raw": "0x" + receiver.hex(), "data_len": len(data), "tokens": []})
    if tt:
        if tt[0] != 1:
            raise ValueError(f"TokenTransferV1 version {tt[0]}")
        amount = int.from_bytes(tt[1:33], "big")
        q = 33
        f = {}
        for name in ("source_pool", "source_token", "dest_token", "token_receiver"):
            n = tt[q]
            f[name] = tt[q + 1:q + 1 + n]
            q += 1 + n
        n = int.from_bytes(tt[q:q + 2], "big")
        extra = tt[q + 2:q + 2 + n]
        if q + 2 + n != len(tt):
            raise ValueError("TokenTransferV1 length")
        m["tokens"].append({"amount": amount, "source_pool": _addr_from_bytes(f["source_pool"]),
                            "source_token": _addr_from_bytes(f["source_token"]),
                            "dest_token": _addr_from_bytes(f["dest_token"]),
                            "token_receiver": _addr_from_bytes(f["token_receiver"]),
                            "source_decimals": _decimals_from_extra(extra), "extra_data": "0x" + extra.hex()})
    return m


def _decimals_from_extra(extra):
    """Source pools of version >= 1.5.1 put abi.encode(uint8 localDecimals) in the token transfer's extra data."""
    b = _b(extra) if isinstance(extra, str) else extra
    if len(b) == 32 and int.from_bytes(b, "big") < 256:
        return int.from_bytes(b, "big")
    return None


def decode_send_log(lg):
    """The OnRamp's send event of any family -> message dict (ids lowercase; amounts in source token units)."""
    t = lg["topics"]
    fam = SENT_TOPICS.get(t[0]) if t else None
    if fam is None:
        return None
    base = {"family": fam, "onramp": lg["address"].lower(), "block": _lg(lg, "blockNumber"),
            "log_index": _lg(lg, "logIndex"), "tx": lg["transactionHash"].lower()}
    d = _b(lg["data"])
    if fam == "1.5":
        m = abi_decode(["(uint64,address,address,uint64,uint256,bool,uint64,address,uint256,bytes,(address,uint256)[],"
                        "bytes[],bytes32)"], d)[0]
        toks = []
        for i, (tok, amt) in enumerate(m[10]):
            std = {}
            if i < len(m[11]) and len(_b(m[11][i])) >= 32:
                try:
                    s = abi_decode(["(bytes,bytes,bytes,uint32)"], m[11][i])[0]
                    std = {"source_pool": _addr_from_bytes(s[0]), "dest_token": _addr_from_bytes(s[1]),
                           "source_decimals": _decimals_from_extra(s[2]), "extra_data": s[2]}
                except Exception:  # noqa: BLE001  (1.2 ramps carried the pool's raw return data)
                    std = {}
            toks.append({"amount": amt, "source_token": tok.lower(), "source_pool": std.get("source_pool"),
                         "dest_token": std.get("dest_token"), "token_receiver": None,
                         "source_decimals": std.get("source_decimals"), "extra_data": std.get("extra_data")})
        return {**base, "message_id": m[12].lower(), "source_selector": m[0], "dest_selector": None, "seq": m[3],
                "nonce": m[6], "sender": m[1].lower(), "receiver": m[2].lower(), "data_len": len(_b(m[9])),
                "tokens": toks, "amount_before_pool_fees": None, "id_check": None}
    if fam == "1.6":
        m = abi_decode(["((bytes32,uint64,uint64,uint64,uint64),address,bytes,bytes,bytes,address,uint256,uint256,"
                        "(address,bytes,bytes,uint256,bytes)[])"], d)[0]
        hdr = m[0]
        toks = [{"amount": x[3], "source_token": None, "source_pool": x[0].lower(),
                 "dest_token": _addr_from_bytes(x[1]), "token_receiver": None,
                 "source_decimals": _decimals_from_extra(x[2]), "extra_data": x[2]} for x in m[8]]
        return {**base, "message_id": hdr[0].lower(), "source_selector": hdr[1], "dest_selector": hdr[2],
                "seq": hdr[3], "nonce": hdr[4], "sender": m[1].lower(), "receiver": _addr_from_bytes(m[3]),
                "data_len": len(_b(m[2])), "tokens": toks, "amount_before_pool_fees": None, "id_check": None}
    w = abi_decode(["address", "uint256", "bytes", "(address,uint32,uint32,uint256,bytes)[]", "bytes[]"], d)
    enc = w[2]
    mv = parse_message_v1(enc)
    mid = t[3].lower()
    return {**base, "message_id": mid, "source_selector": mv["source_selector"], "dest_selector": mv["dest_selector"],
            "seq": mv["seq"], "nonce": None, "sender": mv["sender"], "receiver": mv["receiver"],
            "data_len": mv["data_len"], "tokens": mv["tokens"], "amount_before_pool_fees": w[1],
            "id_check": keccak_hex(_b(enc)) == mid, "encoded_offramp": mv["offramp"], "encoded_onramp": mv["onramp"]}


# ---------------------------------------------------------------------------------------------- destination side
def _receipts(rpc, hashes):
    f = getattr(rpc, "receipts", None)
    if f is not None:
        return f(list(hashes))
    return {h: rpc.receipt(h) for h in hashes}


def _block_ts(rpc, blocks):
    f = getattr(rpc, "block_ts_many", None)
    if f is not None:
        return f(sorted(set(blocks)))
    return {b: rpc.block_ts(b) for b in sorted(set(blocks))}


def exec_events(rpc_dst, dst_chain, from_block, to_block, cfg=None):
    """Decoded ExecutionStateChanged events in the block range from the configured OffRamps on dst_chain, for
    messages from the paired source chain (any state)."""
    cfg = cfg or load_targets()
    src_sel = selector(cfg, other_chain(cfg, dst_chain))
    offs = offramps(cfg, dst_chain)
    out = []
    lane15 = [r["address"] for r in offs if r["family"] == "1.5"]
    multi = [r["address"] for r in offs if r["family"] in ("1.6", "2.0")]
    if lane15:
        out += rpc_dst.logs(lane15, [TOPIC["exec15"]], from_block, to_block)
    if multi:
        out += rpc_dst.logs(multi, [[TOPIC["exec16"], TOPIC["exec20"]], "0x" + format(src_sel, "064x")],
                            from_block, to_block)
    ev = []
    fams = {r["address"]: r["family"] for r in offs}
    for lg in out:
        e = exec_event(lg)
        if e is None or fams.get(e["offramp"]) != e["family"]:
            continue
        if e["source_selector"] is not None and e["source_selector"] != src_sel:
            continue
        ev.append(e)
    ev.sort(key=lambda e: (e["block"], e["log_index"]))
    return ev


def known_pools(cfg, chain):
    return set((cfg.get("pools") or {}).get(chain) or [])


def releases_from_receipt(receipt, execs, src_sel, pools=frozenset(), registry=None):
    """Token releases of the given successful executions (decoded ExecutionStateChanged events, all in this
    receipt's transaction). A message's logs are those after the previous ExecutionStateChanged log of the
    transaction (any OffRamp) and before its own. In that span the token pool's Released / Minted /
    ReleasedOrMinted event gives pool, recipient and amount, and the token's Transfer to the recipient for the
    amount gives the token and whether it was minted (sender = zero address) or paid out of custody.
    A pool event counts when it names the paired source chain (ReleasedOrMinted), or was called by the executing
    OffRamp, or comes from a pool registered for a lane token (`pools`); a second pool event for the same recipient
    and amount that finds no transfer of its own (a pool behind a proxy reporting the same release) is dropped.
    When a span has no such event and `registry` (token, block -> set of the token's pools) is given, a token
    minted or paid out by its registered pool counts if that pool emitted a log in the span (pool_event None).
    Returns (releases, problems): problems lists dropped events and executions that minted tokens without a pool
    event."""
    logs = sorted(receipt["logs"], key=lambda x: _lg(x, "logIndex"))
    bounds = [_lg(x, "logIndex") for x in logs if x["topics"] and x["topics"][0] in EXEC_TOPICS]
    out, problems = [], []
    for e in execs:
        prev = max([b for b in bounds if b < e["log_index"]], default=-1)
        span = [x for x in logs if prev < _lg(x, "logIndex") < e["log_index"]]
        trs = [t for t in (transfer_event(x) for x in span) if t]
        raw_pevs = [p for p in (pool_release_event(x) for x in span) if p]
        pevs = [p for p in raw_pevs if p["remote_selector"] == src_sel
                or (p["remote_selector"] is None and (p["sender"] == e["offramp"] or p["pool"] in pools))]
        for p in raw_pevs:
            if p not in pevs:
                problems.append({"message_id": e["message_id"], "tx": e["tx"], "issue": "pool-like event ignored",
                                 "event": p["event"], "emitter": p["pool"]})
        used, kept = set(), []
        for p in pevs:
            cand = [t for t in trs if t["to"] == p["recipient"] and t["value"] == p["amount"]
                    and (p["token"] is None or t["token"] == p["token"]) and t["log_index"] not in used]
            cand.sort(key=lambda t: (t["from"] not in (ZERO, p["pool"]), abs(t["log_index"] - p["log_index"])))
            tr = cand[0] if cand else None
            if tr is None and any(q["recipient"] == p["recipient"] and q["amount"] == p["amount"] and qt
                                  for q, qt in kept):
                problems.append({"message_id": e["message_id"], "tx": e["tx"], "issue": "duplicate pool event dropped",
                                 "event": p["event"], "emitter": p["pool"]})
                continue
            if tr:
                used.add(tr["log_index"])
            kept.append((p, tr))
        for i, (p, tr) in enumerate(kept):
            token = (p["token"] or (tr or {}).get("token") or "").lower() or None
            mint_tr = [t for t in trs if t["token"] == token and t["from"] == ZERO and t["value"] == p["amount"]]
            if p["event"] == "Minted" or mint_tr:
                kind = "pool_mint"
            elif p["event"] == "Released" or (tr and tr["from"] != ZERO):
                kind = "pool_release"
            else:
                kind = "pool_release_or_mint"
            note = []
            if tr is None:
                note.append("no token transfer to the recipient for the amount")
            elif tr["from"] not in (ZERO, p["pool"]):
                note.append("paid from a custody contract other than the pool")
            if p["sender"] != e["offramp"]:
                note.append("pool called by a contract other than the OffRamp")
            out.append({"message_id": e["message_id"], "seq": e["seq"], "offramp": e["offramp"],
                        "offramp_family": e["family"], "block": e["block"], "tx": e["tx"],
                        "exec_log_index": e["log_index"], "token_index": i, "token": token,
                        "amount_raw": p["amount"], "recipient": p["recipient"], "pool": p["pool"],
                        "pool_event": p["event"], "kind": kind,
                        "transfer_from": tr["from"] if tr else None, "note": "; ".join(note)})
        if not kept and registry is not None and not any(x["topics"] and x["topics"][0] in SENT_TOPICS for x in span):
            # pools that emit no standard release event (e.g. a pool that only reports its rate-limit consumption):
            # a token minted, or paid out by its registered pool, counts when that registered pool emitted a log in
            # the same span. The OffRamp releases tokens before it calls the receiver, so only logs before the first
            # log of a contract that is neither a CCIP token nor a registered pool of one are considered (the
            # receiver's own transfers, and its onward sends, come later); spans with a send event are skipped.
            emitters = {x["address"].lower() for x in span}
            span_tokens = {t["token"] for t in trs}
            pool_side = {e["offramp"]}
            for tok in span_tokens:
                ps = registry(tok, e["block"])
                if ps:
                    pool_side |= ps | {tok}
            cutoff = e["log_index"]
            for x in span:
                a = x["address"].lower()
                if a in pool_side:
                    continue
                if registry(a, e["block"]):  # another CCIP token
                    pool_side.add(a)
                    continue
                cutoff = _lg(x, "logIndex")
                break
            trs_early = [t for t in trs if t["log_index"] < cutoff]
            emitters = {x["address"].lower() for x in span if _lg(x, "logIndex") < cutoff}
            i = 0
            for t in trs_early:
                tp = registry(t["token"], e["block"]) if (t["from"] == ZERO or t["from"] in emitters) else set()
                hit = tp & emitters
                if not hit or t["to"] in tp or t["to"] in (ZERO, DEAD):
                    continue
                if t["from"] == ZERO or any(u["token"] == t["token"] and u["from"] == ZERO and u["to"] in tp
                                            for u in trs_early):
                    kind = "pool_mint"
                elif t["from"] in tp:
                    kind = "pool_release"
                else:
                    continue
                out.append({"message_id": e["message_id"], "seq": e["seq"], "offramp": e["offramp"],
                            "offramp_family": e["family"], "block": e["block"], "tx": e["tx"],
                            "exec_log_index": e["log_index"], "token_index": i, "token": t["token"],
                            "amount_raw": t["value"], "recipient": t["to"], "pool": sorted(hit)[0],
                            "pool_event": None, "kind": kind, "transfer_from": t["from"],
                            "note": "pool emitted no standard release event"})
                kept.append((None, t))
                i += 1
        if not kept and any(t["from"] == ZERO or t["from"] in pools for t in trs):
            problems.append({"message_id": e["message_id"], "tx": e["tx"],
                             "issue": "tokens minted or paid by a pool in the execution without a pool release event",
                             "transfers": len(trs)})
    return out, problems


def registry_lookup(rpc, cfg, chain):
    """token -> set of its pools on `chain`: the targets token table (documented pool and the TokenAdminRegistry's
    pool at the period ends) plus the registry's answer at the given block (cached in memory)."""
    known = {}
    for per in (cfg.get("tokens") or {}).values():
        e = per.get(chain) or {}
        if e.get("token"):
            known[e["token"]] = {x for x in (e.get("pool"), e.get("registry_pool_at_period_start"),
                                             e.get("registry_pool_at_period_end")) if x and x != ZERO}
    tar = cfg["chains"][chain]["token_admin_registry"]
    memo = {}

    def f(token, block):
        s = set(known.get(token, set()))
        if (token, block) not in memo:
            try:
                memo[(token, block)] = _taddr(rpc.eth_call(tar, FN["getPool"] + "0" * 24 + token[2:], block))
            except Exception:  # noqa: BLE001
                memo[(token, block)] = ZERO
        if memo[(token, block)] != ZERO:
            s.add(memo[(token, block)])
        return s
    return f


def new_releases(rpc_dst, dst_chain, from_block, to_block, diag=None, discover=True):
    """Releases of the configured pair on dst_chain in [from_block, to_block] (inclusive), with block timestamps,
    token symbol and decimals. With discover=True the router's OffRamps at to_block are added to the configuration
    first (a ramp upgrade after the targets file was written). `diag`, if a dict, receives the executions by state
    and the executions whose span moved tokens without a pool event."""
    cfg = load_targets()
    src_chain = other_chain(cfg, dst_chain)
    src_sel = selector(cfg, src_chain)
    if discover:
        discover_ramps(rpc_dst, dst_chain, to_block, cfg)
    ev = exec_events(rpc_dst, dst_chain, from_block, to_block, cfg)
    ok = [e for e in ev if e["state"] == 2]
    by_tx = {}
    for e in ok:
        by_tx.setdefault(e["tx"], []).append(e)
    recs = _receipts(rpc_dst, list(by_tx))
    rel, problems = [], []
    pools = known_pools(cfg, dst_chain)
    reg = registry_lookup(rpc_dst, cfg, dst_chain)
    for txh, es in by_tx.items():
        r, p = releases_from_receipt(recs[txh], es, src_sel, pools, reg)
        rel += r
        problems += p
    ts = _block_ts(rpc_dst, [r["block"] for r in rel])
    for r in rel:
        sym, dec = token_meta(rpc_dst, dst_chain, r["token"], cfg)
        r.update({"direction": f"{src_chain}->{dst_chain}", "src_chain": src_chain, "dst_chain": dst_chain,
                  "ts": ts[r["block"]], "symbol": sym, "decimals": dec,
                  "amount": (r["amount_raw"] / 10 ** dec) if dec is not None else None})
    rel.sort(key=lambda r: (r["block"], r["exec_log_index"], r["token_index"]))
    if isinstance(diag, dict):
        diag.setdefault("executions", []).extend(ev)
        diag.setdefault("no_pool_event", []).extend(problems)
        released = {(r["message_id"]) for r in rel}
        diag.setdefault("success_without_release", []).extend(
            [e for e in ok if e["message_id"] not in released])
    return rel


# ---------------------------------------------------------------------------------------------------- source side
def _seq_counter(rpc_src, onramp, family, dest_sel, block):
    """The OnRamp's next sequence (message) number toward dest_sel as of the end of `block`; 0 before deployment."""
    if family == "1.5":
        data = FN["nextSeq15"]
    elif family == "1.6":
        data = FN["nextSeq16"] + format(dest_sel, "064x")
    else:
        data = FN["nextNum20"] + format(dest_sel, "064x")
    try:
        h = rpc_src.eth_call(onramp, data, block)
    except RuntimeError:
        return 0
    return int(h, 16) if h and h != "0x" else 0


def locate_send_block(rpc_src, onramp, family, dest_sel, seq, before_block, lo_hint=None):
    """Block in which the OnRamp sent sequence number `seq`: the first block whose end state has next > seq.
    Searches back from `before_block` (exponential steps, then bisection). None if seq was never sent there."""
    hi = before_block
    if _seq_counter(rpc_src, onramp, family, dest_sel, hi) <= seq:
        return None
    step = 256
    lo = hi - step if lo_hint is None else lo_hint
    while lo > 0 and _seq_counter(rpc_src, onramp, family, dest_sel, lo) > seq:
        hi = lo
        step *= 4
        lo = max(0, lo - step)
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if _seq_counter(rpc_src, onramp, family, dest_sel, mid) > seq:
            hi = mid
        else:
            lo = mid
    return hi


def send_logs_in_block(rpc_src, onramp, family, dest_sel, block, message_id=None, seq=None):
    if family == "1.5":
        topics = [TOPIC["sent15"]]
    elif family == "1.6":
        topics = [TOPIC["sent16"], "0x" + format(dest_sel, "064x")] + (
            ["0x" + format(seq, "064x")] if seq is not None else [])
    else:
        topics = [TOPIC["sent20"], "0x" + format(dest_sel, "064x"), None] + ([message_id] if message_id else [])
    return rpc_src.logs(onramp, topics, block, block)


def value_check(receipt, msg):
    """Did the source token pool take the tokens in the send transaction? For each token transfer of the message:
    tokens moved into the pool (Transfer of the source token to the pool) and either burned (Transfer from the pool
    to the zero or dead address for the amount) -> pool_burn, or kept (in the pool or moved on to a lock box) ->
    pool_lock; no movement into the pool -> none. The pool's own LockedOrBurned / Locked / Burned event for the
    amount is recorded alongside. Only logs between the previous send event of the transaction and this one count."""
    logs = sorted(receipt["logs"], key=lambda x: _lg(x, "logIndex"))
    bounds = [_lg(x, "logIndex") for x in logs if x["topics"] and x["topics"][0] in SENT_TOPICS]
    prev = max([b for b in bounds if b < msg["log_index"]], default=-1)
    span = [x for x in logs if prev < _lg(x, "logIndex") < msg["log_index"]]
    trs = [t for t in (transfer_event(x) for x in span) if t]
    locks = [p for p in (pool_lock_event(x) for x in span) if p]
    out = []
    for tk in msg["tokens"]:
        pool, amt = tk.get("source_pool"), tk["amount"]
        pev = [p for p in locks if (pool is None or p["pool"] == pool) and p["amount"] == amt]
        token = tk.get("source_token") or (pev[0]["token"] if pev and pev[0]["token"] else None)
        if token is None and pool is not None:
            ins = [t for t in trs if t["to"] == pool]
            token = ins[0]["token"] if ins else None
        if pool is None and token is not None:
            cands = [p["pool"] for p in locks if p["amount"] == amt]
            pool = cands[0] if cands else None
        tin = sum(t["value"] for t in trs if t["token"] == token and t["to"] == pool and t["from"] != pool)
        onward = [t for t in trs if t["token"] == token and t["from"] == pool and t["to"] not in (ZERO, DEAD)
                  and t["value"] == amt]
        holders = {pool} | {t["to"] for t in onward}  # the pool, or a contract it handed the amount to (legacy pool)
        burn = [t for t in trs if t["token"] == token and t["from"] in holders and t["to"] in (ZERO, DEAD)
                and t["value"] == amt]
        if token is not None and pool is not None and tin >= amt and amt > 0:
            detail = "pool_burn" if (burn or (pev and pev[0]["event"] == "Burned")) else "pool_lock"
        else:
            detail = "none"
        out.append({"source_token": token, "source_pool": pool, "amount_raw": amt, "into_pool_raw": tin,
                    "burned": bool(burn), "moved_on_from_pool": bool(onward) and detail == "pool_lock",
                    "pool_event": pev[0]["event"] if pev else None, "detail": detail})
    return out


def convert_amount(amount, src_dec, dst_dec):
    """The destination pool's conversion of a source-denominated amount into local units (TokenPool >= 1.5.1)."""
    if src_dec is None or dst_dec is None or src_dec == dst_dec:
        return amount
    if dst_dec > src_dec:
        return amount * 10 ** (dst_dec - src_dec)
    return amount // 10 ** (src_dec - dst_dec)


def compare(msg, release, dst_decimals):
    """Amount, token and recipient of the source message against the release (same token index)."""
    i = release.get("token_index", 0)
    if i >= len(msg["tokens"]):
        return {"agrees": False, "token": False, "amount": False, "recipient": False, "expected_raw": None}
    tk = msg["tokens"][i]
    rcpt = tk.get("token_receiver") or msg["receiver"]
    exp = convert_amount(tk["amount"], tk.get("source_decimals"), dst_decimals)
    ok_t = tk.get("dest_token") is not None and tk["dest_token"] == release["token"]
    ok_a = exp == release["amount_raw"]
    ok_r = rcpt is not None and rcpt == release["recipient"]
    return {"agrees": ok_t and ok_a and ok_r, "token": ok_t, "amount": ok_a, "recipient": ok_r,
            "expected_raw": exp, "source_amount_raw": tk["amount"], "source_decimals": tk.get("source_decimals")}


def source_from_log(rpc_src, src_chain, lg, release=None, receipt=None):
    """Decode a located send log, read its transaction and run the value check (and the comparison with the
    release when one is given)."""
    msg = decode_send_log(lg)
    if msg is None:
        return None
    rec = receipt or _receipts(rpc_src, [msg["tx"]])[msg["tx"]]
    msg["ts"] = _block_ts(rpc_src, [msg["block"]])[msg["block"]]
    msg["tx_status"] = int(rec.get("status", "0x1"), 16) if isinstance(rec.get("status"), str) else rec.get("status")
    msg["value"] = value_check(rec, msg)
    for v in msg["value"]:
        if v["source_token"]:
            v["symbol"], v["decimals"] = token_meta(rpc_src, src_chain, v["source_token"])
    dets = sorted({v["detail"] for v in msg["value"]})
    msg["value_moved"] = "yes" if msg["value"] and all(v["detail"] != "none" for v in msg["value"]) else "no"
    msg["value_detail"] = "+".join(dets) if dets else "none"
    if release is not None:
        msg["compare"] = compare(msg, release, release.get("decimals"))
    return msg


def find_source(rpc_src, src_chain, release):
    """The send event with the release's messageId on src_chain, decoded and value-checked, or None.
    The OnRamp is the one linked to the OffRamp that executed the release; the send block is found from the
    OnRamp's sequence counter (archive eth_call), searching back from the release time, so the age of the message
    does not matter."""
    cfg = load_targets()
    dst_chain = other_chain(cfg, src_chain)
    dest_sel = selector(cfg, dst_chain)
    off = next((r for r in offramps(cfg, dst_chain) if r["address"] == release["offramp"]), None)
    cands = (off or {}).get("linked_onramps") or [r["address"] for r in onramps(cfg, src_chain)
                                                     if r["family"] == release["offramp_family"]]
    fams = {r["address"]: r["family"] for r in onramps(cfg, src_chain)}
    before = rpc_src.block_at(release["ts"]) if hasattr(rpc_src, "block_at") else None
    for onr in cands:
        fam = fams.get(onr, release["offramp_family"])
        b = locate_send_block(rpc_src, onr, fam, dest_sel, release["seq"], before)
        if b is None:
            continue
        for lg in send_logs_in_block(rpc_src, onr, fam, dest_sel, b, release["message_id"], release["seq"]):
            m = decode_send_log(lg)
            if m and m["message_id"] == release["message_id"]:
                return source_from_log(rpc_src, src_chain, lg, release)
    return None
