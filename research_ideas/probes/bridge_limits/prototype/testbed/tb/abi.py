"""Minimal ABI encoding and decoding for the static types the testbed uses."""
from __future__ import annotations

from .keccak import keccak256, selector, topic  # noqa: F401


def _word_uint(v: int) -> bytes:
    if v < 0:
        v += 1 << 256
    return int(v).to_bytes(32, "big")


def _word(t: str, v) -> bytes:
    if t == "address":
        return bytes(12) + bytes.fromhex(v[2:] if isinstance(v, str) else v.hex())
    if t == "bool":
        return _word_uint(1 if v else 0)
    if t == "bytes32":
        if isinstance(v, int):
            return _word_uint(v)
        b = bytes.fromhex(v[2:]) if isinstance(v, str) else bytes(v)
        return b.rjust(32, b"\0")
    if t.startswith("uint") or t.startswith("int"):
        return _word_uint(int(v))
    raise ValueError(t)


def split_types(sig: str):
    inner = sig[sig.index("(") + 1:sig.rindex(")")]
    return [x for x in inner.split(",") if x]


def encode_args(types, args) -> bytes:
    return b"".join(_word(t, a) for t, a in zip(types, args))


def calldata(sig: str, *args) -> str:
    return "0x" + (selector(sig) + encode_args(split_types(sig), args)).hex()


def words(hexdata: str):
    b = bytes.fromhex(hexdata[2:] if hexdata.startswith("0x") else hexdata)
    return [b[i:i + 32] for i in range(0, len(b), 32)]


def dec(t: str, w: bytes):
    if t == "address":
        return "0x" + w[12:].hex()
    if t == "bool":
        return int.from_bytes(w, "big") != 0
    if t == "bytes32":
        return "0x" + w.hex()
    return int.from_bytes(w, "big")


def decode(types, hexdata: str):
    ws = words(hexdata)
    return [dec(t, w) for t, w in zip(types, ws)]


def addr_topic(a: str) -> str:
    return "0x" + "0" * 24 + a[2:].lower()


def uint_topic(v: int) -> str:
    return "0x" + int(v).to_bytes(32, "big").hex()


def id32(i: int) -> str:
    return "0x" + int(i).to_bytes(32, "big").hex()
