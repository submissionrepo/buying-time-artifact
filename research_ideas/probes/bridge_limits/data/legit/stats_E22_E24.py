"""Summary statistics for the E22/E24 legit-release CSVs (feeds the README files). Prints only aggregates."""
import collections
import json
import pathlib
import sys

import pandas as pd

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent / "incidents"))


def stats(fid):
    df = pd.read_csv(HERE / f"{fid}.csv")
    df["t"] = pd.to_datetime(df["ts_utc"])
    meta = json.loads((HERE / "raw" / fid / "meta.json").read_text())
    rows = json.loads((HERE / "raw" / fid / "rows_all.json").read_text())
    print(f"== {fid}: blocks {meta['b0']}..{meta['b1']}  window {pd.to_datetime(meta['t_start'], unit='s')} .. "
          f"{pd.to_datetime(meta['t_end'], unit='s')}")
    print("exclusions:", collections.Counter((r["leg"], r["kind"], r["exclude"]) for r in rows if r["exclude"]))
    for name, g in [("ALL", df)] + list(df.groupby("leg")):
        pr = g[g.priced == "yes"]
        print(f"{name}: n={len(g)} priced={len(pr)} ({len(pr)/len(g):.3%}) usd={pr.usd.sum():,.0f} "
              f"days_with_release={g.t.dt.date.nunique()} first={g.t.min()} last={g.t.max()} "
              f"kinds={dict(g.kind.value_counts())}")
        gaps = g.t.sort_values().diff().dropna()
        print(f"   longest gap {gaps.max()} ; gaps>2d {int((gaps > pd.Timedelta(days=2)).sum())}")
    un = df[df.priced == "no"].groupby("asset").size().sort_values(ascending=False)
    print("unpriced by asset:", dict(un))
    pr = df[df.priced == "yes"]
    top = pr.sort_values("usd", ascending=False).head(5)
    print("largest:\n", top[["ts_utc", "leg", "asset", "amount", "usd"]].to_string(index=False))
    h = pr.groupby(pr.t.dt.floor("h")).usd.agg(["sum", "size"]).sort_values("sum", ascending=False).head(3)
    print("busiest hours (USD):\n", h.to_string())
    hn = df.groupby(df.t.dt.floor("h")).size().sort_values(ascending=False).head(1)
    print("busiest hour by count:", hn.to_dict())
    d = pr.groupby(pr.t.dt.floor("D")).usd.agg(["sum", "size"]).sort_values("sum", ascending=False).head(3)
    print("busiest days (USD):\n", d.to_string())
    dn = df.groupby(df.t.dt.floor("D")).size().sort_values(ascending=False).head(1)
    print("busiest day by count:", dn.to_dict())
    daily = pr.groupby(pr.t.dt.floor("D")).usd.sum().reindex(
        pd.date_range(df.t.min().floor("D"), df.t.max().floor("D"), freq="D", tz="UTC"), fill_value=0)
    print(f"daily USD: median {daily.median():,.0f} mean {daily.mean():,.0f} p90 {daily.quantile(.9):,.0f} "
          f"max {daily.max():,.0f}; zero-days {int((daily == 0).sum())}")
    print(f"single release USD: median {pr.usd.median():,.0f} p99 {pr.usd.quantile(.99):,.0f}")
    by_month = df.groupby(df.t.dt.to_period("M")).size()
    print("releases by month:", by_month.to_dict())


def recipients(fid, top=20):
    from rpc import Rpc
    rows = [r for r in json.loads((HERE / "raw" / fid / "rows_all.json").read_text()) if not r["exclude"]]
    tot = sum(r["usd"] or 0 for r in rows)
    agg = collections.defaultdict(lambda: [0, 0.0])
    for r in rows:
        agg[r["to"]][0] += 1
        agg[r["to"]][1] += r["usd"] or 0
    rpc = Rpc("ethereum")
    out = []
    for a, (n, u) in sorted(agg.items(), key=lambda t: -t[1][1])[:top]:
        code = rpc.call("eth_getCode", [a, "latest"])
        out.append({"to": a, "n": n, "usd": u, "share": u / tot, "is_contract": len(code) > 2})
    (HERE / "raw" / fid / "top_recipients.json").write_text(json.dumps(out, indent=1))
    print(f"{fid}: distinct recipients {len(agg)}; top{top} share {sum(o['share'] for o in out):.3f}; "
          f"contracts among top{top}: {sum(o['is_contract'] for o in out)} "
          f"(USD share {sum(o['share'] for o in out if o['is_contract']):.3f}); top1 {out[0]['share']:.3f}")


if __name__ == "__main__":
    for fid in sys.argv[1:]:
        stats(fid)
        recipients(fid)
