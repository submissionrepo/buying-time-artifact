"""Write results/review_latency_ronin.json: the counts and latencies of raw/ronin/summary.json
(written by ronin_locks.py) without receipt hashes, addresses or event topics (2026-10-16)."""
import json
import pathlib
import re

HERE = pathlib.Path(__file__).resolve().parent
src = json.loads((HERE / "raw" / "ronin" / "summary.json").read_text(encoding="utf-8"))
HEX = re.compile(r"^0x[0-9a-fA-F]{40,}$")


def clean(x):
    if isinstance(x, dict):
        return {k: clean(v) for k, v in x.items() if not HEX.match(str(k)) and not (isinstance(v, str) and HEX.match(v))}
    if isinstance(x, list):
        return [clean(v) for v in x if not (isinstance(v, str) and HEX.match(v))]
    return x


keep = ("n_locked", "n_unlocked", "n_locked_never_unlocked", "unlocks_without_lock_event", "source_agreement_blocks",
        "n_blockscout", "latency_s", "rows", "n_releases_all", "n_deposits_all", "last_release_utc", "head_fetched_utc")
out = clean({k: src[k] for k in keep if k in src})
(HERE.parent.parent / "results" / "review_latency_ronin.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
print(json.dumps({k: out[k] for k in ("n_locked", "n_unlocked", "n_releases_all", "latency_s")}, indent=1))
