"""Wormhole Governor parameter history from the git history of mainnet_chains.go.

Usage:
    python -I governor_history.py --repo <wormhole clone> --out <output dir>

The clone can be blobless (git clone --filter=blob:none --no-checkout); file
versions are read with `git show` and fetched on demand.  Fetch all tags first
(git fetch origin 'refs/tags/*:refs/tags/*' --filter=blob:none) so that hotfix
releases cut from side branches are included.

Outputs (in --out):
  governor_limits_by_commit.csv   one row per (commit on main touching the file, chain):
                                  full per-chain state after the commit.
  governor_limits_by_release.csv  one row per (official release tag, chain): the state
                                  shipped in that release.
  governor_settings.csv           per chain, intervals of constant (daily limit, big
                                  transaction size) on two timelines:
                                  timeline=commit  (start = commit date on main)
                                  timeline=release (start = date of the first counted
                                  release carrying the values; see below)
  governor_history_meta.json      repository head, tag list used, parse checks.

Release timeline.  Guardians run tagged releases, not main.  Official tags are those
matching v?MAJOR.MINOR[.PATCH[.HOTFIX]] with no suffix (so -aztec, -stacks, -testnet,
-test* variants are excluded).  Tags are walked in order of the tagged commit's date;
a tag is counted only if its version is >= every version counted before it, so that a
patch on an older release line does not roll the timeline back.  The state at time t
is the state of the last counted tag dated <= t.  Guardian upgrade lag after a release
is not observable and is not modelled.
"""
import argparse
import csv
import datetime as dt
import json
import re
import subprocess
import sys
from pathlib import Path

CONFIG_PATH = "node/pkg/governor/mainnet_chains.go"
SDK_PATHS = ["sdk/vaa/structs.go", "node/pkg/vaa/structs.go"]


def git(repo, *args, check=True):
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {r.stderr.strip()}")
    return r.stdout


def to_utc(iso):
    t = dt.datetime.fromisoformat(iso.replace("Z", "+00:00"))
    return t.astimezone(dt.timezone.utc)


def chain_id_map(repo):
    """Union of ChainIDxxx = n constants over several SDK versions (old chains were removed)."""
    out = {}
    revs = ["HEAD"]
    # older versions of the SDK file, to recover chains removed later
    for path in SDK_PATHS:
        log = git(repo, "log", "--format=%H", "--", path, check=False).split()
        revs += [f"{h}:{path}" for h in log[:: max(1, len(log) // 12)]]
    seen = set()
    for rev in ["HEAD:" + SDK_PATHS[0]] + revs[1:]:
        if rev in seen:
            continue
        seen.add(rev)
        txt = git(repo, "show", rev, check=False)
        for name, num in re.findall(r"\bChainID([A-Za-z0-9]+)\s+ChainID\s*=\s*(\d+)", txt):
            out.setdefault(name, int(num))
    return out


def strip_go_comments(src):
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"//[^\n]*", "", src)


def parse_config(src):
    """Return {chain_name: (daily_limit, big_tx_size or None)} from the chain list body."""
    body = strip_go_comments(src)
    m = re.search(r"func\s+[cC]hainList\(\)\s*\[\]\s*[cC]hainConfigEntry\s*\{(.*?)\n\}", body, flags=re.S)
    if not m:
        raise ValueError("chainList function not found")
    entries = {}
    problems = []
    for ent in re.findall(r"\{([^{}]*)\}", m.group(1)):
        fields = {}
        for part in ent.split(","):
            part = part.strip()
            if not part:
                continue
            k, _, v = part.partition(":")
            fields[k.strip().lower()] = v.strip()
        if "emitterchainid" not in fields:
            continue
        cm = re.fullmatch(r"vaa\.ChainID([A-Za-z0-9]+)", fields["emitterchainid"])
        if not cm:
            problems.append(f"unparsed chain {fields['emitterchainid']}")
            continue

        def num(key):
            v = fields.get(key)
            if v is None:
                return None
            v = v.replace("_", "")
            if not re.fullmatch(r"\d+", v):
                problems.append(f"unparsed number {key}={fields.get(key)}")
                return None
            return int(v)

        unknown = set(fields) - {"emitterchainid", "dailylimit", "bigtransactionsize"}
        if unknown:
            problems.append(f"unknown fields {sorted(unknown)}")
        name = cm.group(1)
        if name in entries:
            problems.append(f"duplicate entry {name}")
        entries[name] = (num("dailylimit"), num("bigtransactionsize"))
    return entries, problems


VERSION_RE = re.compile(r"^[vV]?(\d+)\.(\d+)(?:\.(\d+))?(?:\.(\d+))?$")


def official_tags(repo):
    rows = []
    for line in git(repo, "for-each-ref", "refs/tags", "--format=%(refname:short)\t%(*objectname)\t%(objectname)").splitlines():
        name, peeled, obj = line.split("\t")
        m = VERSION_RE.match(name)
        if not m:
            continue
        commit = peeled or obj
        cdate = git(repo, "log", "-1", "--format=%cI", commit).strip()
        ver = tuple(int(x) if x else 0 for x in m.groups())
        rows.append({"tag": name, "commit": commit, "date": to_utc(cdate), "version": ver})
    rows.sort(key=lambda r: (r["date"], r["version"]))
    # drop exact duplicates of the same commit and version (e.g. "2.45.0" and "v2.45.0")
    dedup, seen = [], set()
    for r in rows:
        key = (r["commit"], r["version"])
        if key in seen:
            continue
        seen.add(key)
        dedup.append(r)
    counted, vmax = [], None
    for r in dedup:
        r["counted"] = vmax is None or r["version"] >= vmax
        if r["counted"]:
            vmax = r["version"]
            counted.append(r)
    return dedup, counted


def intervals(points):
    """points: list of (time, state_dict) sorted by time -> per chain list of
    (start, end, daily, big) with end = start of next different state (None = open)."""
    per_chain = {}
    chains = sorted({c for _, s in points for c in s})
    for c in chains:
        runs = []
        cur = None
        for t, s in points:
            val = s.get(c)  # None when the chain is absent (ungoverned)
            if cur is None or val != cur[1]:
                if cur is not None:
                    runs.append((cur[0], t, cur[1]))
                cur = (t, val)
        runs.append((cur[0], None, cur[1]))
        per_chain[c] = [(a, b, v) for a, b, v in runs]
    return per_chain


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    repo, out = Path(args.repo), Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    ids = chain_id_map(repo)
    head = git(repo, "rev-parse", "HEAD").strip()
    log = git(repo, "log", "--first-parent", "--reverse", "--format=%H%x09%aI%x09%cI%x09%s", "--", CONFIG_PATH)
    commits = []
    problems_all = {}
    for line in log.splitlines():
        sha, adate, cdate, subj = line.split("\t", 3)
        src = git(repo, "show", f"{sha}:{CONFIG_PATH}")
        cfg, problems = parse_config(src)
        if problems:
            problems_all[sha] = problems
        commits.append({"sha": sha, "adate": to_utc(adate), "cdate": to_utc(cdate), "subject": subj, "cfg": cfg})

    tags, counted = official_tags(repo)
    for r in tags:
        src = git(repo, "show", f"{r['commit']}:{CONFIG_PATH}", check=False)
        if src:
            cfg, problems = parse_config(src)
            if problems:
                problems_all[r["tag"]] = problems
        else:
            cfg = {}
        r["cfg"] = cfg

    # first counted release that contains each main commit (ancestry), and the first
    # counted release whose full state equals the commit's state (catches cherry-picks)
    for c in commits:
        c["first_release_containing"] = None
        c["first_release_equal"] = None
        for r in counted:
            if r["date"] < c["cdate"] - dt.timedelta(days=1):
                continue
            if c["first_release_equal"] is None and r["cfg"] == c["cfg"]:
                c["first_release_equal"] = r
            if c["first_release_containing"] is None:
                anc = subprocess.run(["git", "-C", str(repo), "merge-base", "--is-ancestor", c["sha"], r["commit"]]).returncode == 0
                if anc:
                    c["first_release_containing"] = r
            if c["first_release_equal"] is not None and c["first_release_containing"] is not None:
                break

    def name_id(name):
        return ids.get(name, "")

    with open(out / "governor_limits_by_commit.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["date", "commit", "chain", "chain_id", "daily_limit_usd", "big_tx_size_usd",
                    "author_date", "subject", "first_release_containing", "first_release_containing_date",
                    "first_release_with_equal_state", "first_release_with_equal_state_date"])
        for c in commits:
            frc, fre = c["first_release_containing"], c["first_release_equal"]
            rows = sorted(c["cfg"].items(), key=lambda kv: (name_id(kv[0]) if name_id(kv[0]) != "" else 99999, kv[0]))
            if not rows:
                w.writerow([c["cdate"].isoformat(), c["sha"], "", "", "", "", c["adate"].isoformat(), c["subject"],
                            frc["tag"] if frc else "", frc["date"].isoformat() if frc else "",
                            fre["tag"] if fre else "", fre["date"].isoformat() if fre else ""])
            for name, (daily, big) in rows:
                w.writerow([c["cdate"].isoformat(), c["sha"], name, name_id(name), daily,
                            "" if big is None else big, c["adate"].isoformat(), c["subject"],
                            frc["tag"] if frc else "", frc["date"].isoformat() if frc else "",
                            fre["tag"] if fre else "", fre["date"].isoformat() if fre else ""])

    with open(out / "governor_limits_by_release.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["tag", "tag_commit", "date", "counted_in_timeline", "chain", "chain_id", "daily_limit_usd", "big_tx_size_usd"])
        for r in tags:
            if not r["cfg"]:
                w.writerow([r["tag"], r["commit"], r["date"].isoformat(), r["counted"], "", "", "", ""])
            for name, (daily, big) in sorted(r["cfg"].items(), key=lambda kv: (name_id(kv[0]) if name_id(kv[0]) != "" else 99999, kv[0])):
                w.writerow([r["tag"], r["commit"], r["date"].isoformat(), r["counted"], name, name_id(name), daily,
                            "" if big is None else big])

    commit_points = [(c["cdate"], c["cfg"]) for c in commits]
    release_points = [(r["date"], r["cfg"]) for r in counted]
    with open(out / "governor_settings.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["timeline", "chain", "chain_id", "start", "end", "daily_limit_usd", "big_tx_size_usd", "governed"])
        for tl, pts in (("commit", commit_points), ("release", release_points)):
            for name, runs in sorted(intervals(pts).items(), key=lambda kv: (name_id(kv[0]) if name_id(kv[0]) != "" else 99999, kv[0])):
                for a, b, v in runs:
                    daily, big = v if v is not None else (None, None)
                    w.writerow([tl, name, name_id(name), a.isoformat(), b.isoformat() if b else "",
                                "" if daily is None else daily, "" if big is None else big, v is not None])

    meta = {
        "repo_head": head,
        "config_path": CONFIG_PATH,
        "n_commits": len(commits),
        "first_commit": commits[0]["sha"], "first_commit_date": commits[0]["cdate"].isoformat(),
        "last_commit": commits[-1]["sha"], "last_commit_date": commits[-1]["cdate"].isoformat(),
        "n_official_tags": len(tags), "n_counted_tags": len(counted),
        "skipped_tags": [r["tag"] for r in tags if not r["counted"]],
        "parse_problems": problems_all,
        "chain_ids": ids,
        "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
    }
    (out / "governor_history_meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in meta.items() if k != "chain_ids"}, indent=1))


if __name__ == "__main__":
    sys.exit(main())
