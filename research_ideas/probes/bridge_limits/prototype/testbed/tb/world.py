"""Start the two anvil nodes and deploy the testbed: a deposit contract on the source chain; on the
destination chain, one or more limiters at the release point, each behind its own receiver, with
the relayer as the receiver's only caller and the monitor account as the independent pauser."""
from __future__ import annotations

import os
import shutil
import subprocess
import time

from .abi import calldata
from .contracts import deploy, tuned_ctor
from .rpc import Chain

ANVIL = shutil.which("anvil") or os.path.expanduser("~/.foundry/bin/anvil" + (".exe" if os.name == "nt" else ""))
ZERO = "0x" + "0" * 40

# development accounts (the same on both chains)
ADMIN, RELAYER, PAUSER, KEEPER, USER, TUNER, RCPT, ATT_RCPT, ATT, SPARE = range(10)
ROLES = {ADMIN: "admin/deployer", RELAYER: "relayer key used by the honest relayer", PAUSER: "monitor (pauser)",
         KEEPER: "keeper (calls executeNext)", USER: "depositor", TUNER: "tuner (TunedLimiter)",
         RCPT: "legitimate recipient", ATT_RCPT: "recipient of unbacked releases",
         ATT: "second relayer key, held by the unauthorized party", SPARE: "unused"}


def start_anvil(port, chain_id, genesis_ts, block_time=None, log_path=None, keep_states=512):
    """keep_states: states kept in memory (anvil --prune-history N); rollback and snapshots need them."""
    args = [ANVIL, "--port", str(port), "--chain-id", str(chain_id), "--timestamp", str(int(genesis_ts)),
            "--prune-history", str(keep_states), "--gas-limit", "200000000", "--silent"]
    if block_time is None:
        args.append("--no-mining")
    else:
        args += ["--block-time", str(block_time)]
    out = open(log_path, "w") if log_path else subprocess.DEVNULL
    return subprocess.Popen(args, stdout=out, stderr=subprocess.STDOUT)


def stop(procs):
    for p in procs:
        try:
            p.terminate()
        except Exception:
            pass
    for p in procs:
        try:
            p.wait(timeout=10)
        except Exception:
            try:
                p.kill()
            except Exception:
                pass


def wait_tx(chain, h):
    r = chain.wait_receipt(h)
    assert int(r["status"], 16) == 1, r
    return r


def deploy_world(S: Chain, D: Chain, limiters_cfg, loosen_delay=2 * 86400):
    """limiters_cfg: list of dicts {name, kind ('outflow'|'tuned'), hold, buckets [(cap, refill), ...]}
    (capacity and refill in base units; refill per second). Returns the world description."""
    acc = S.accounts()
    assert acc == D.accounts()
    S.automine(True)
    D.automine(True)
    s_token = deploy(S, acc[ADMIN], "TestToken")
    s_dep = deploy(S, acc[ADMIN], "SourceDeposit", ["address"], [s_token])
    wait_tx(S, S.send(acc[USER], s_token, calldata("faucet(address,uint256)", acc[USER], 10 ** 36), gas=200_000))
    wait_tx(S, S.send(acc[USER], s_token, calldata("approve(address,uint256)", s_dep, 2 ** 256 - 1), gas=200_000))
    d_token = deploy(D, acc[ADMIN], "TestToken")
    executor = deploy(D, acc[ADMIN], "Executor")
    lims = []
    for L in limiters_cfg:
        rec = deploy(D, acc[ADMIN], "Receiver", ["address", "address", "address"], [acc[RELAYER], acc[ATT], d_token])
        if L["kind"] == "outflow":
            (cap, refill), = L["buckets"]
            lim = deploy(D, acc[ADMIN], "OutflowLimiter",
                         ["address", "address", "address", "address", "uint128", "uint128", "uint64"],
                         [rec, acc[ADMIN], acc[PAUSER], ZERO, cap, refill, L["hold"]])
        else:
            lim = deploy(D, acc[ADMIN], "TunedLimiter",
                         raw_args=tuned_ctor(rec, acc[ADMIN], acc[TUNER], acc[PAUSER], L["buckets"], L["hold"], loosen_delay))
        wait_tx(D, D.send(acc[ADMIN], rec, calldata("setLimiter(address)", lim), gas=200_000))
        wait_tx(D, D.send(acc[ADMIN], lim, calldata("listAsset(address,uint256,bool)", d_token, 10 ** 18, False), gas=200_000))
        wait_tx(D, D.send(acc[ADMIN], d_token, calldata("faucet(address,uint256)", lim, 10 ** 36), gas=200_000))
        lims.append({"name": L["name"], "kind": L["kind"], "hold": L["hold"], "buckets": [list(b) for b in L["buckets"]],
                     "receiver": rec.lower(), "limiter": lim.lower()})
    S.automine(False)
    D.automine(False)
    return {"acc": [a.lower() for a in acc], "s_token": s_token.lower(), "s_dep": s_dep.lower(),
            "d_token": d_token.lower(), "executor": executor.lower(), "limiters": lims}


def connect(url, name, tries=200):
    last = None
    for _ in range(tries):
        try:
            c = Chain(url, name)
            c.head()
            return c
        except Exception as e:  # node still starting
            last = e
            time.sleep(0.1)
    raise RuntimeError(f"cannot connect to {url}: {last}")
