"""Governor token list (CoinGecko id, decimals, configured price) on the release timeline.

Usage:
    python -I governor_token_versions.py --repo <wormhole clone> --out <dir>

For every counted release tag (governor_history.official_tags: official version tags in
order of the tagged commit's date, a tag counted only if its version is >= every version
counted before it), reads the token list files shipped in the tag:
node/pkg/governor/mainnet_tokens.go (2022), generated_mainnet_tokens.go and
manual_tokens.go (2022-11 on).  Entries have the form {chain, addr, symbol, coinGeckoId,
decimals, price}.  The Governor values a transfer at max(CoinGecko price, configured price)
(governor_prices.go), so the configured price is a floor.

Outputs in --out:
  governed_tokens_release.csv  chain, addr (32-byte hex), start, end (release dates; end
                               empty = still in force), symbol, coingecko_id, decimals,
                               price: intervals of a constant entry on the release timeline.
  governed_tokens_cg.csv       chain, addr, symbol, coingecko_id, decimals of the latest
                               entry for every token ever listed in a release.
"""
import argparse
import csv
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import governor_history as gh  # noqa: E402

FILES = ["node/pkg/governor/mainnet_tokens.go", "node/pkg/governor/manual_tokens.go",
         "node/pkg/governor/generated_mainnet_tokens.go"]
ENTRY = re.compile(r'(?<![A-Za-z])chain:\s*(\d+)\s*,\s*addr:\s*"([0-9a-f]{64})"\s*,\s*symbol:\s*"([^"]*)"\s*,'
                   r'\s*coinGeckoId:\s*"([^"]*)"\s*,\s*decimals:\s*(\d+)\s*,\s*price:\s*([0-9.eE+-]+)', re.I)


def blob_id(repo, commit, path):
    r = subprocess.run(["git", "-C", str(repo), "rev-parse", f"{commit}:{path}"], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    repo, out = Path(args.repo), Path(args.out)
    _, counted = gh.official_tags(repo)
    tag_blobs = []
    for r in counted:
        tag_blobs.append((r, [blob_id(repo, r["commit"], f) for f in FILES]))
    oids = sorted({b for _, bs in tag_blobs for b in bs if b})
    subprocess.run(["git", "-C", str(repo), "-c", "fetch.negotiationAlgorithm=noop", "fetch", "origin", "--no-tags",
                    "--no-write-fetch-head", "--recurse-submodules=no", "--filter=blob:none", "--stdin"],
                   input="\n".join(oids) + "\n", text=True, capture_output=True)
    parsed = {}
    for b in oids:
        src = subprocess.run(["git", "-C", str(repo), "cat-file", "-p", b], capture_output=True, text=True,
                             encoding="utf-8", errors="replace").stdout
        parsed[b] = [(int(m.group(1)), m.group(2).lower(), m.group(3), m.group(4), int(m.group(5)), float(m.group(6)))
                     for m in ENTRY.finditer(src)]
    # state per counted tag: (chain, addr) -> (symbol, cg, decimals, price); generated entries
    # override manual ones only where the manual list has none
    states = []
    for r, bs in tag_blobs:
        st = {}
        for b in bs:
            if not b:
                continue
            for c, a, sym, cg, dec, price in parsed.get(b, []):
                st.setdefault((c, a), (sym, cg, dec, price))
        states.append((r["date"], st))
    rows, latest = [], {}
    keys = sorted({k for _, st in states for k in st})
    for k in keys:
        cur = None
        for t, st in states:
            val = st.get(k)
            if cur is None or val != cur[1]:
                if cur is not None and cur[1] is not None:
                    rows.append((k, cur[0], t, cur[1]))
                cur = (t, val)
            if val is not None:
                latest[k] = val
        if cur is not None and cur[1] is not None:
            rows.append((k, cur[0], None, cur[1]))
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "governed_tokens_release.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["chain", "addr", "start", "end", "symbol", "coingecko_id", "decimals", "price"])
        for (c, a), s, e, (sym, cg, dec, price) in rows:
            w.writerow([c, a, s.isoformat(), "" if e is None else e.isoformat(), sym, cg, dec, price])
    with open(out / "governed_tokens_cg.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["chain", "addr", "symbol", "coingecko_id", "decimals"])
        for (c, a), (sym, cg, dec, price) in sorted(latest.items()):
            w.writerow([c, a, sym, cg, dec])
    n_ent = {b: len(v) for b, v in parsed.items()}
    print(f"counted tags {len(counted)}, distinct token-file blobs {len(oids)} "
          f"(entries per blob min {min(n_ent.values()) if n_ent else 0}, max {max(n_ent.values()) if n_ent else 0}); "
          f"tokens {len(latest)}, intervals {len(rows)}")


if __name__ == "__main__":
    sys.exit(main())
