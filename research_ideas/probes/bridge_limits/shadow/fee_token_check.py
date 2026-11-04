"""The releases the shadow check could not match on Wormhole (2026-10-17): do they match when the check counts every
outflow of the token from custody?

wormhole_decode.releases_in_receipt reads a release as at most two token movements after the redeem event (a relayer
fee and the rest), the rule of the 42-day dataset and of the live monitor. The 13 releases the check did not
confirm on 2026-09-04 to 2026-10-16 all carried three movements. This script reads each one's receipt (from the
collector's cache) and tests the alternative rule: the sum of all transfers of the released token out of the token
bridge between the redeem event and the next one equals the signed amount, and one of those transfers goes to the
recipient named in the source message. Output: results/shadow_fee_tokens.json (no addresses or hashes).
"""
from __future__ import annotations

import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import wormhole_decode as wd  # noqa: E402

RAW = HERE / "raw" / "wormhole"


def main():
    T = wd.load_targets()
    out = []
    for src, dst in (("ethereum", "bsc"), ("bsc", "ethereum")):
        rels = json.loads((RAW / f"releases_{src}_to_{dst}.json").read_text(encoding="utf-8"))["releases"]
        sl = json.loads((RAW / f"sources_{src}_to_{dst}.json").read_text(encoding="utf-8"))
        sl = sl["sources"] if isinstance(sl, dict) and "sources" in sl else sl
        rpc = wd.Client(dst, cache_dir=RAW / "cache")
        tb = T["chains"][dst]["token_bridge"]
        for r, s in zip(rels, sl):
            if not s or s.get("amount_agrees") == "yes":
                continue
            p = s["payload"]
            rc = rpc.receipt(r["tx"])
            logs = sorted(rc["logs"], key=lambda x: wd.hx(x["logIndex"]))
            i = next(k for k, x in enumerate(logs) if wd.hx(x["logIndex"]) == r["log_index"])
            j = next((k for k in range(i + 1, len(logs)) if logs[k]["topics"] and logs[k]["topics"][0] == wd.REDEEMED
                      and logs[k]["address"].lower() == tb), len(logs))
            outs = []
            for x in logs[i + 1:j]:
                t = x["topics"]
                if x["address"].lower() == r["token"] and t and t[0] == wd.TRANSFER and len(t) == 3 \
                        and wd.addr_from_word(t[1]) == tb:
                    outs.append((wd.addr_from_word(t[2]), int(x["data"], 16)))
            want = wd.denormalize(p["amount"], r["decimals"])
            to = wd.addr_from_word(p["to"]) if wd.word_is_address(p["to"]) else None
            shares = sorted((round(v / want, 4) for _, v in outs), reverse=True) if want else []
            out.append({"direction": f"{src}->{dst}", "release_utc": wd_iso(r["ts"]), "token": r["symbol"],
                        "outflows": len(outs), "outflow_sum_equals_signed_amount": sum(v for _, v in outs) == want,
                        "recipient_receives_an_outflow": any(a == to for a, _ in outs),
                        "recipient_share": round(sum(v for a, v in outs if a == to) / want, 4) if want else None,
                        "outflow_shares": shares})
    res = {"releases": len(out), "all_match_by_outflow_sum": all(x["outflow_sum_equals_signed_amount"] and
                                                                  x["recipient_receives_an_outflow"] for x in out),
           "tokens": sorted({x["token"] for x in out}), "rows": out}
    (HERE.parent / "results" / "shadow_fee_tokens.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in res.items() if k != "rows"}, indent=1))
    for x in out:
        print(x)


def wd_iso(t):
    import datetime as dt
    return dt.datetime.fromtimestamp(int(t), dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


if __name__ == "__main__":
    main()
