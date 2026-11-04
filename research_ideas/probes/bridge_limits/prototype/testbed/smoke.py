"""Smoke test of the two-chain world: deploy, deposit, relay, execute, pause, cancel, rollback; checks
the timestamp used by eth_call on the latest block."""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tb.abi import calldata, decode, id32  # noqa: E402
from tb.contracts import REQ_TYPES, T_RELAYED, parse_relayed  # noqa: E402
from tb.world import start_anvil, stop, deploy_world, connect, RELAYER, PAUSER, KEEPER, USER, RCPT  # noqa: E402

WAD = 10 ** 18
T0 = 1_700_000_000
ps = [start_anvil(18601, 1001, T0 - 86400), start_anvil(18602, 1002, T0 - 86400)]
try:
    S = connect("http://127.0.0.1:18601", "S")
    D = connect("http://127.0.0.1:18602", "D")
    cap, refill = 1000 * WAD, WAD  # 1000 tokens, 1 token per second
    w = deploy_world(S, D, [{"name": "L0", "kind": "outflow", "hold": 0, "buckets": [(cap, refill)]},
                            {"name": "T0", "kind": "tuned", "hold": 0, "buckets": [(cap, refill), (2 * cap, refill // 2)]}])
    acc = w["acc"]
    print("deployed", {k: v for k, v in w.items() if k != "acc"})
    # deposit on S
    S.mine_at(T0)
    h = S.send(acc[USER], w["s_dep"], calldata("deposit(bytes32,uint256,address)", id32(1), 700 * WAD, acc[RCPT]), gas=250_000)
    S.mine_at(T0 + 12)
    r = S.receipt(h)
    print("deposit status", r["status"], "gas", int(r["gasUsed"], 16))
    print("deposits(1)", decode(["uint128", "address", "uint64"], S.call(w["s_dep"], calldata("deposits(bytes32)", id32(1)))))
    # relay on D to both receivers
    D.mine_at(T0 + 10)
    hs = [D.send(acc[RELAYER], L["receiver"], calldata("relay(bytes32,address,uint256)", id32(1), acc[RCPT], 700 * WAD), gas=400_000)
          for L in w["limiters"]]
    D.mine_at(T0 + 20)
    for x in hs:
        r = D.receipt(x)
        print("relay status", r["status"], "gas", int(r["gasUsed"], 16))
    logs = D.logs([L["receiver"] for L in w["limiters"]], [T_RELAYED], 0, D.head())
    print("relayed", [parse_relayed(lg)["rid"] for lg in logs])
    # eth_call timestamp check: TunedLimiter available(0) at latest vs computed
    tl = w["limiters"][1]["limiter"]
    D.mine_at(T0 + 30)
    print("T0 available(0) at latest", int(D.call(tl, calldata("available(uint256)", 0)), 16) / WAD, "latest ts",
          int(D.block()["timestamp"], 16) - T0)
    # execute both
    hx = [D.send(acc[KEEPER], w["executor"], calldata("drain(address,uint256)", L["limiter"], 10), gas=3_000_000) for L in w["limiters"]]
    D.mine_at(T0 + 32)
    for x in hx:
        r = D.receipt(x)
        print("drain status", r["status"], "gas", int(r["gasUsed"], 16), "logs", len(r["logs"]))
    for L in w["limiters"]:
        print(L["name"], "req0", decode(REQ_TYPES, D.call(L["limiter"], calldata("requests(uint256)", 0))))
        print("   available after", int(D.call(L["limiter"], calldata("available()" if L["kind"] == "outflow" else "available(uint256)", *([] if L["kind"] == "outflow" else [0]))), 16) / WAD)
    D.mine_at(T0 + 40)
    time.sleep(2)
    for L in w["limiters"]:
        print("   available at latest (ts 40, expect 308 / 304)", int(D.call(L["limiter"], calldata("available()" if L["kind"] == "outflow" else "available(uint256)", *([] if L["kind"] == "outflow" else [0]))), 16) / WAD)
    print("   T0 available(1)", int(D.call(w["limiters"][1]["limiter"], calldata("available(uint256)", 1)), 16) / WAD)
    # second relay (no deposit), pause, cancel
    hs = [D.send(acc[RELAYER], L["receiver"], calldata("relay(bytes32,address,uint256)", id32(99), acc[RCPT], 100 * WAD), gas=400_000)
          for L in w["limiters"]]
    hp = [D.send(acc[PAUSER], L["limiter"], calldata("pause()"), gas=150_000) for L in w["limiters"]]
    hc = [D.send(acc[PAUSER], L["limiter"], calldata("cancel(uint256)", 1), gas=150_000) for L in w["limiters"]]
    D.mine_at(T0 + 42)
    for name, xs in (("relay", hs), ("pause", hp), ("cancel", hc)):
        for x in xs:
            r = D.receipt(x)
            print(name, "status", r["status"], "gas", int(r["gasUsed"], 16), "txidx", int(r["transactionIndex"], 16))
    # rollback on S drops the deposit
    S.mine_at(T0 + 24)
    print("S head", S.head())
    S.rpc("anvil_rollback", [2])
    pend = S.rpc("txpool_content", []) if True else None
    print("after rollback head", S.head(), "pool pending accounts", len(pend.get("pending", {})))
    print("deposits(1) after rollback", decode(["uint128", "address", "uint64"], S.call(w["s_dep"], calldata("deposits(bytes32)", id32(1)))))
    S.mine_at(T0 + 12)
    print("re-mined head", S.head(), "deposits(1)", decode(["uint128", "address", "uint64"], S.call(w["s_dep"], calldata("deposits(bytes32)", id32(1)))))
    # snapshot/revert with pool
    sid = D.snapshot()
    for i in range(300):
        D.mine_at(T0 + 50 + 2 * i)
    print("revert", D.revert(sid), D.head())
finally:
    stop(ps)
