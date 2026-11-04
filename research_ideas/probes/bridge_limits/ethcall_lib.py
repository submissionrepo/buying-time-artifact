"""Minimal JSON-RPC eth_call helper for the stake-vs-value reads (2026-10-16).

No web3 dependency: function selectors come from Keccak-256 (pycryptodome),
arguments and return values are ABI-encoded/decoded by hand for the few
static types used here. Every call is logged (RPC, block, raw return data)
so a reader can replay it.
"""
import json
import time
import urllib.request

from Crypto.Hash import keccak

RPCS = ["https://ethereum-rpc.publicnode.com", "https://rpc.mevblocker.io"]
LOG = []


def k256(data: bytes) -> bytes:
    h = keccak.new(digest_bits=256)
    h.update(data)
    return h.digest()


def selector(sig: str) -> str:
    return k256(sig.encode()).hex()[:8]


def topic(sig: str) -> str:
    return "0x" + k256(sig.encode()).hex()


def rpc(method, params, url=None, timeout=60):
    urls = [url] if url else RPCS
    last = None
    for u in urls:
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method,
                           "params": params}).encode()
        req = urllib.request.Request(u, data=body, headers={
            "Content-Type": "application/json", "User-Agent": "Mozilla/5.0"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                out = json.loads(r.read().decode())
            if "error" in out:
                last = (u, out["error"])
                continue
            return u, out["result"]
        except Exception as e:  # network error: try next RPC
            last = (u, repr(e))
            continue
    raise RuntimeError(f"rpc failed {method}: {last}")


def enc_word(t, v):
    if t == "address":
        return v.lower().replace("0x", "").rjust(64, "0")
    if t.startswith("uint") or t.startswith("int"):
        v = int(v)
        if v < 0:
            v = (1 << 256) + v
        return format(v, "064x")
    if t == "bytes32":
        return v.replace("0x", "").ljust(64, "0")
    if t == "bool":
        return format(1 if v else 0, "064x")
    raise ValueError(t)


def encode(types, args):
    """Static types only; a tuple of static types is written as consecutive words."""
    out = ""
    for t, v in zip(types, args):
        if isinstance(t, (list, tuple)):
            for tt, vv in zip(t, v):
                out += enc_word(tt, vv)
        else:
            out += enc_word(t, v)
    return out


def eth_call(to, sig, types=(), args=(), block="latest", note=""):
    data = "0x" + selector(sig) + encode(types, args)
    u, res = rpc("eth_call", [{"to": to, "data": data}, block])
    LOG.append({"utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "rpc": u, "block": block, "to": to, "sig": sig,
                "args": [str(a) for a in args], "data": data, "result": res,
                "note": note})
    return res


def words(hexstr):
    h = hexstr[2:] if hexstr.startswith("0x") else hexstr
    return [h[i:i + 64] for i in range(0, len(h), 64)]


def as_uint(w):
    return int(w, 16)


def as_int(w):
    v = int(w, 16)
    return v - (1 << 256) if v >= (1 << 255) else v


def as_addr(w):
    return "0x" + w[-40:]


def as_string(hexstr):
    """Decode an ABI-encoded single string return value."""
    ws = words(hexstr)
    if not ws:
        return ""
    off = as_uint(ws[0]) // 32
    n = as_uint(ws[off])
    raw = bytes.fromhex("".join(ws[off + 1:])[: 2 * n])
    return raw.decode("utf-8", "replace")


def block_info(tag="latest"):
    u, b = rpc("eth_getBlockByNumber", [tag, False])
    return {"rpc": u, "number": int(b["number"], 16),
            "timestamp": int(b["timestamp"], 16),
            "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                 time.gmtime(int(b["timestamp"], 16)))}


def dump(path, extra=None):
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"calls": LOG, "extra": extra or {}}, f, indent=1)
