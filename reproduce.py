"""Regenerate the paper's numbers, tables and figures, and rerun the analyses behind them.

    python reproduce.py                 level 1: numbers.tex, tables, data figures (under a minute)
    python reproduce.py level2          unpack the gzipped datasets, rerun every analysis, then level 1
    python reproduce.py checks          unit test of analysis_core.py and the exact checks of the paper
    python reproduce.py prototype       forge test in prototype/ (Foundry and forge-std, see README)
    python reproduce.py unpack | clean  unpack the gzipped datasets | remove the unpacked copies
    python reproduce.py dirs            create the cache directories that the level-3 collectors write to

Several tasks can be given in one call, e.g. `python reproduce.py level2 checks`.  Each step writes its
console output to outputs/<step>.log.  The shipped outputs are the ones these commands produced when the
artifact was assembled, so after a run `git status` lists the files whose content changed.
"""
import argparse
import gzip
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TEX = ROOT / "research_ideas" / "bridge_limits_paper" / "tex"
PRB = ROOT / "research_ideas" / "probes" / "bridge_limits"
OUT = ROOT / "outputs"

# Datasets shipped gzipped because of their size; the scripts read the plain files.
GZ = [
    "research_ideas/probes/bridge_limits/data/legit/E01.csv",
    "research_ideas/probes/bridge_limits/data/legit/E05.csv",
    "research_ideas/probes/bridge_limits/data/legit/E10.csv",
    "research_ideas/probes/bridge_limits/data/legit/E11.csv",
    "research_ideas/probes/bridge_limits/data/legit/E13.csv",
    "research_ideas/probes/bridge_limits/data/legit/E14.csv",
    "research_ideas/probes/bridge_limits/data/legit/E15.csv",
    "research_ideas/probes/bridge_limits/data/legit/E16.csv",
    "research_ideas/probes/bridge_limits/data/legit/E21.csv",
    "research_ideas/probes/bridge_limits/data/legit/E22.csv",
    "research_ideas/probes/bridge_limits/data/legit/E24.csv",
    "research_ideas/probes/bridge_limits/data/legit/E25.csv",
    "research_ideas/probes/bridge_limits/data/legit/E30.csv",
    "research_ideas/probes/bridge_limits/data/legit/E45.csv",
    "research_ideas/probes/bridge_limits/data/legit/E49.csv",
    "research_ideas/probes/bridge_limits/data/legit/E50.csv",
    "research_ideas/probes/bridge_limits/data/legit/E58.csv",
    "research_ideas/probes/bridge_limits/data/legit/E59.csv",
    "research_ideas/probes/bridge_limits/data/legit/E60.csv",
    "research_ideas/probes/bridge_limits/data/legit/E64.csv",
    "research_ideas/probes/bridge_limits/data/wormhole/tops_portal_hourly.csv",
    "research_ideas/probes/bridge_limits/data/wormhole/tops_cctp_v2_hourly.csv",
    "research_ideas/probes/bridge_limits/data/wormhole/hour_valuation.csv",
    "research_ideas/probes/bridge_limits/data/wormhole/adjustments_small.csv",
    "research_ideas/probes/bridge_limits/data/wormhole/transfers_classified.csv",
    "research_ideas/probes/bridge_limits/shadow/live/polls.csv",
]

LEVEL1 = [
    ("make_numbers", TEX / "make_numbers.py", []),
    ("make_tables", TEX / "make_tables.py", []),
    ("make_figures", TEX / "make_figures.py", []),
]

# Level 2 in dependency order: (step, script, arguments).
LEVEL2 = [
    ("incidents_universe", PRB / "incidents" / "01_universe.py", []),
    ("incidents_dataset", PRB / "incidents" / "05_build_dataset.py", []),
    ("coding_redact", PRB / "coding" / "redact_labels.py", []),
    ("coding_agreement", PRB / "coding" / "agreement.py", []),
    ("coverage", PRB / "coverage" / "counts.py", []),
    ("response_protocol", PRB / "response_protocol.py", []),
    ("validation_bounds", PRB / "validation_bounds.py", []),
    ("histories_check", PRB / "data" / "legit" / "check_histories.py", []),
    ("replay_incidents", PRB / "replay_incidents.py", []),
    ("wormhole_series", PRB / "wormhole" / "analyze_series.py",
     ["--data", str(PRB / "data" / "wormhole"), "--end", "2026-10-15T16:00:00Z"]),
    ("wormhole_pooling", PRB / "wormhole" / "pooling_clean.py", []),
    ("ccip_flows", PRB / "ccip" / "flows_analyze.py", []),
    ("ccip_recommend", PRB / "ccip" / "recommend_buckets.py", []),
    ("ccip_out_of_sample", PRB / "ccip" / "out_of_sample.py", []),
    ("ccip_rolling", PRB / "ccip" / "rolling_policy.py", []),
    ("ccip_rolling_v2", PRB / "ccip" / "rolling_v2.py", []),
    ("ccip_review", PRB / "ccip" / "review_policy.py", []),
    ("ccip_inbound", PRB / "ccip" / "inbound_mismatch.py", []),
    ("ccip_lags", PRB / "ccip" / "lags.py", []),
    ("ccip_census", PRB / "ccip" / "limits_distribution.py", []),
    ("replay_matched", PRB / "replay_matched.py", []),
    ("replay_variants", PRB / "replay_variants.py", []),
    ("replay_perbridge", PRB / "replay_perbridge.py", []),
    ("delay_budget", PRB / "delay_budget.py", []),
    ("testbed_summary", PRB / "prototype" / "testbed" / "summarize.py", []),
    ("testbed_forged", PRB / "prototype" / "testbed" / "summarize_forged.py", []),
    ("shadow_simulate", PRB / "shadow" / "simulate.py", []),
]

CHECKS = [("test_analysis_core", PRB / "test_analysis_core.py", [])] + [
    (p.stem, p, []) for p in sorted(PRB.glob("first_layer_*.py"))]

# Cache directories written by the level-3 collectors (not shipped).
CACHE_DIRS = [
    "research_ideas/probes/bridge_limits/data/legit/raw/E01",
    "research_ideas/probes/bridge_limits/data/legit/raw/E05",
    "research_ideas/probes/bridge_limits/data/legit/raw/E10",
    "research_ideas/probes/bridge_limits/data/legit/raw/E11",
    "research_ideas/probes/bridge_limits/data/legit/raw/E13",
    "research_ideas/probes/bridge_limits/data/legit/raw/E14",
    "research_ideas/probes/bridge_limits/data/legit/raw/E15",
    "research_ideas/probes/bridge_limits/data/legit/raw/E16",
    "research_ideas/probes/bridge_limits/data/legit/raw/E21",
    "research_ideas/probes/bridge_limits/data/legit/raw/E22",
    "research_ideas/probes/bridge_limits/data/legit/raw/E24",
    "research_ideas/probes/bridge_limits/data/legit/raw/E25",
    "research_ideas/probes/bridge_limits/data/legit/raw/E30",
    "research_ideas/probes/bridge_limits/data/legit/raw/E45",
    "research_ideas/probes/bridge_limits/data/legit/raw/E49",
    "research_ideas/probes/bridge_limits/data/legit/raw/E50",
    "research_ideas/probes/bridge_limits/data/legit/raw/E58",
    "research_ideas/probes/bridge_limits/data/legit/raw/E59",
    "research_ideas/probes/bridge_limits/data/legit/raw/E60",
    "research_ideas/probes/bridge_limits/data/legit/raw/E64",
    "research_ideas/probes/bridge_limits/data/review_latency/raw/ronin",
    "research_ideas/probes/bridge_limits/data/incidents/prices",
]


def run(name, script, args, cwd=ROOT):
    OUT.mkdir(exist_ok=True)
    env = os.environ.copy()
    env.update(PYTHONUTF8="1", PYTHONIOENCODING="utf-8", MPLBACKEND="Agg")
    t0 = time.monotonic()
    log = OUT / f"{name}.log"
    with log.open("w", encoding="utf-8") as fh:
        res = subprocess.run([sys.executable, "-I", str(script), *args], cwd=cwd, env=env,
                             stdout=fh, stderr=subprocess.STDOUT)
    dt = time.monotonic() - t0
    print(f"{name:<22} exit {res.returncode}  {dt:7.1f} s  outputs/{name}.log", flush=True)
    if res.returncode:
        print(log.read_text(encoding="utf-8")[-4000:])
        raise SystemExit(f"{name} failed")
    return dt


def unpack():
    for rel in GZ:
        src = ROOT / (rel + ".gz")
        dst = ROOT / rel
        if dst.exists() and dst.stat().st_mtime >= src.stat().st_mtime:
            continue
        with gzip.open(src, "rb") as fi, open(dst, "wb") as fo:
            shutil.copyfileobj(fi, fo, 1 << 20)
        print(f"unpacked {rel}", flush=True)


def clean():
    for rel in GZ:
        p = ROOT / rel
        if p.exists():
            p.unlink()
            print(f"removed {rel}")


def git_status():
    if not (ROOT / ".git").exists() or shutil.which("git") is None:
        return
    res = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True)
    lines = [x for x in res.stdout.splitlines() if x.strip()]
    print(f"\ngit status: {len(lines)} changed or new file(s)" + (":" if lines else ""))
    for x in lines[:60]:
        print("  " + x)


def prototype(forge):
    proto = PRB / "prototype"
    if not (proto / "lib" / "forge-std" / "src").is_dir():
        raise SystemExit("forge-std is missing: see README (git clone ... prototype/lib/forge-std)")
    OUT.mkdir(exist_ok=True)
    t0 = time.monotonic()
    with (OUT / "prototype_forge_test.log").open("w", encoding="utf-8") as fh:
        res = subprocess.run([forge, "test"], cwd=proto, stdout=fh, stderr=subprocess.STDOUT)
    print(f"forge test exit {res.returncode} in {time.monotonic() - t0:.0f} s; outputs/prototype_forge_test.log")
    if res.returncode:
        raise SystemExit("forge test failed")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("tasks", nargs="*", default=["level1"],
                    help="level1 (default), level2, checks, prototype, unpack, clean, dirs")
    ap.add_argument("--forge", default=shutil.which("forge"), help="path of the forge executable")
    a = ap.parse_args()
    for task in a.tasks:
        if task == "level1":
            for step in LEVEL1:
                run(*step)
        elif task == "level2":
            unpack()
            total = sum(run(*step) for step in LEVEL2 if step[1].exists())
            total += sum(run(*step) for step in LEVEL1)
            print(f"level 2 and level 1: {total / 60:.1f} min")
        elif task == "checks":
            for step in CHECKS:
                run(*step)
        elif task == "prototype":
            if not a.forge:
                raise SystemExit("Foundry's forge was not found; install Foundry 1.8.5 or pass --forge PATH")
            prototype(a.forge)
        elif task == "unpack":
            unpack()
        elif task == "clean":
            clean()
        elif task == "dirs":
            for rel in CACHE_DIRS:
                (ROOT / rel).mkdir(parents=True, exist_ok=True)
            print(f"created {len(CACHE_DIRS)} cache directories")
        else:
            ap.error(f"unknown task {task}")
    git_status()


if __name__ == "__main__":
    main()
