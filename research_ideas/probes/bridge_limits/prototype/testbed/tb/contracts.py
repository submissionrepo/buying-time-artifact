"""Artifacts, deployment and call helpers for the testbed contracts."""
from __future__ import annotations

import json
import os

from .abi import calldata, decode, encode_args, topic, words, dec

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "out")

ARTIFACTS = {
    "SourceDeposit": ("Bridge.sol", "SourceDeposit"),
    "Receiver": ("Bridge.sol", "Receiver"),
    "Executor": ("Bridge.sol", "Executor"),
    "OutflowLimiter": ("OutflowLimiter.sol", "OutflowLimiter"),
    "TunedLimiter": ("TunedLimiter.sol", "TunedLimiter"),
    "TestToken": ("Tokens.sol", "TestToken"),
}


def bytecode(name: str) -> str:
    f, c = ARTIFACTS[name]
    return json.load(open(os.path.join(OUT, f, c + ".json"), encoding="utf-8"))["bytecode"]["object"]


# ------------------------------------------------------------------ events
T_DEPOSITED = topic("Deposited(bytes32,address,address,uint256)")
T_RELAYED = topic("Relayed(bytes32,uint256,address,uint256)")
T_QUEUED_O = topic("Queued(uint256,address,address,uint256,uint256,uint64)")
T_QUEUED_T = topic("Queued(uint256,address,address,uint256,uint256)")
T_EXECUTED_O = topic("Executed(uint256,uint256,uint256)")
T_EXECUTED_T = topic("Executed(uint256,uint256)")
T_CANCELLED = topic("Cancelled(uint256)")
T_PAUSED = topic("Paused(address)")
T_UNPAUSED = topic("Unpaused(address)")

STATUS = {0: "None", 1: "Queued", 2: "Executed", 3: "Cancelled"}


def deploy(chain, frm, name, ctor_types=(), ctor_args=(), raw_args: bytes | None = None, gas=8_000_000):
    """Deploy with automine on; returns the contract address."""
    data = bytecode(name) + (raw_args if raw_args is not None else encode_args(list(ctor_types), list(ctor_args))).hex()
    h = chain.send(frm, None, data, gas=gas)
    r = chain.wait_receipt(h)
    assert int(r["status"], 16) == 1, (name, r)
    return r["contractAddress"]


def tuned_ctor(bridge, admin, tuner, pauser, params, hold, loosen_delay) -> bytes:
    """(address,address,address,address,(uint128,uint128)[],uint64,uint64)"""
    head = encode_args(["address"] * 4, [bridge, admin, tuner, pauser])
    head += (7 * 32).to_bytes(32, "big")  # offset of the dynamic array
    head += encode_args(["uint64", "uint64"], [hold, loosen_delay])
    tail = len(params).to_bytes(32, "big")
    for cap, refill in params:
        tail += encode_args(["uint128", "uint128"], [cap, refill])
    return head + tail


def call_int(chain, to, sig, *args, block="latest"):
    return int(chain.call(to, calldata(sig, *args), block), 16)


def call_dec(chain, to, sig, types, *args, block="latest"):
    return decode(types, chain.call(to, calldata(sig, *args), block))


REQ_TYPES = ["address", "uint64", "uint8", "address", "uint128", "uint128"]


def parse_relayed(log):
    """Relayed(bytes32 indexed id, uint256 indexed requestId, address indexed to, uint256 amount)"""
    return {"receiver": log["address"].lower(), "dep_id": log["topics"][1], "rid": int(log["topics"][2], 16),
            "to": "0x" + log["topics"][3][-40:], "amount": int(log["data"], 16),
            "bn": int(log["blockNumber"], 16), "tx": log["transactionHash"], "li": int(log["logIndex"], 16)}


def parse_deposited(log):
    return {"dep_id": log["topics"][1], "from": "0x" + log["topics"][2][-40:], "to": "0x" + log["topics"][3][-40:],
            "amount": int(log["data"], 16), "bn": int(log["blockNumber"], 16), "bh": log["blockHash"],
            "tx": log["transactionHash"]}


def parse_executed(log):
    w = words(log["data"])
    return {"limiter": log["address"].lower(), "rid": int(log["topics"][1], 16), "value": dec("uint256", w[0]),
            "bn": int(log["blockNumber"], 16), "li": int(log["logIndex"], 16), "ti": int(log["transactionIndex"], 16),
            "tx": log["transactionHash"]}
