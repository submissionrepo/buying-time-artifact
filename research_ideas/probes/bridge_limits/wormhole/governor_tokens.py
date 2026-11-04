"""Union of every token ever on the Wormhole Governor's token list (git history).

Usage:
    python -I governor_tokens.py --repo <wormhole clone> --out <dir>

Reads every version of node/pkg/governor/mainnet_tokens.go (2022-07 to 2022-11),
generated_mainnet_tokens.go and manual_tokens.go (2022-11 on) and writes
<out>/governed_tokens_union.csv: chain, addr (32-byte hex, lower case), symbol (latest),
first_seen, last_seen (commit dates on main), n_versions.  The Governor values and counts
only transfers of listed tokens, so a transfer of a token never listed is outside what it
meters at any date.
"""
import argparse
import csv
import re
import subprocess
import sys
from pathlib import Path

FILES = ["node/pkg/governor/mainnet_tokens.go", "node/pkg/governor/generated_mainnet_tokens.go",
         "node/pkg/governor/manual_tokens.go"]
# one pattern for all formats: tokenConfigEntry{chain: 1, addr: "..", symbol: ".."} (2022),
# {chain: 1, addr: ..} and {Chain: 1, Addr: ..} (later); comments are not stripped, so a
# commented-out entry would also count (none were found in the files checked)
ENTRY = re.compile(r'(?<![A-Za-z])chain:\s*(\d+)\s*,\s*addr:\s*"([0-9a-f]{64})"\s*,\s*symbol:\s*"([^"]*)"', re.I)


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8",
                          errors="replace", check=True).stdout


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    repo, out = Path(args.repo), Path(args.out)
    versions = []
    for f in FILES:
        for line in git(repo, "log", "--format=%H %cI", "--", f).splitlines():
            sha, date = line.split()
            versions.append((date, sha, f))
    # prefetch all blobs in one request
    oids = []
    for date, sha, f in versions:
        try:
            oids.append(git(repo, "rev-parse", f"{sha}:{f}").strip())
        except subprocess.CalledProcessError:
            pass
    subprocess.run(["git", "-C", str(repo), "-c", "fetch.negotiationAlgorithm=noop", "fetch", "origin", "--no-tags",
                    "--no-write-fetch-head", "--recurse-submodules=no", "--filter=blob:none", "--stdin"],
                   input="\n".join(oids) + "\n", text=True, capture_output=True)
    tokens = {}
    n_parsed = 0
    for date, sha, f in sorted(versions):
        try:
            src = git(repo, "show", f"{sha}:{f}")
        except subprocess.CalledProcessError:
            continue          # file deleted at this commit
        found = 0
        for m in ENTRY.finditer(src):
            chain, addr, sym = m.group(1), m.group(2).lower(), m.group(3)
            key = (int(chain), addr)
            t = tokens.setdefault(key, {"symbol": sym, "first_seen": date, "last_seen": date, "n": 0})
            t["symbol"], t["last_seen"] = sym, date
            t["n"] += 1
            found += 1
        n_parsed += found > 0
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "governed_tokens_union.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["chain", "addr", "symbol", "first_seen", "last_seen", "n_versions"])
        for (c, a), t in sorted(tokens.items()):
            w.writerow([c, a, t["symbol"], t["first_seen"], t["last_seen"], t["n"]])
    print(f"versions {len(versions)} (with entries {n_parsed}); tokens ever listed {len(tokens)}")


if __name__ == "__main__":
    sys.exit(main())
