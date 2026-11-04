"""Data figures for the paper (hz_figstyle).

fig_example.pdf  Figure 1. (a) Value an example bridge holding $100M lets out after a
                 failure, by hours since the first unauthorized release: no limit, a ramp of
                 $2M per hour at the release point (burst one hour of refill), and a 24-hour
                 hold. (b) Share of the value of the timed events whose first response came
                 by t (results/incidents.csv, bridge set). The dashed rule in (a) is the
                 median response time over failures.
"""
import csv
import statistics
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PROBES = HERE.parents[1] / 'probes' / 'bridge_limits'
sys.path.insert(0, str(ROOT))
import hz_figstyle as hz  # noqa: E402

hz.apply()
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.ticker import FixedLocator, NullLocator  # noqa: E402

MID = '0.42'


def events():
    with open(PROBES / 'results' / 'incidents.csv', encoding='utf-8') as f:
        ev = [r for r in csv.DictReader(f) if r['in_bridge_set'] == 'yes' and r['response_delay_s']]
    return [(float(r['response_delay_s']) / 3600, float(r['amount_usd'])) for r in ev]


def example():
    ev = events()
    med = statistics.median(d for d, _ in ev)
    W, b, r = 100.0, 2.0, 2.0
    t = np.geomspace(0.1, 2000, 600)
    fig, (ax, bx) = plt.subplots(2, 1, figsize=(3.45, 2.7), sharex=True,
                                 gridspec_kw={'height_ratios': [1.7, 1.0], 'hspace': 0.12})
    # (a) what the example bridge lets out
    ax.plot(t, np.minimum(W, b + r * t), color=hz.INK, lw=1.6)
    ax.plot([0.1, 2000], [W, W], color=MID, lw=1.1, ls='--')
    ax.step([0.1, 24, 2000], [0, W, W], where='post', color=MID, lw=1.1, ls=':')
    ax.axvline(med, color=hz.GUIDE, lw=0.8, ls='--', zorder=0)
    ax.plot([med], [b + r * med], marker='s', ms=4.6, mfc='white', mec=hz.INK, mew=0.9, zorder=5)
    ax.annotate(f'\\${b + r * med:.1f}M at the median response', xy=(med, b + r * med), xytext=(0.13, 34),
                fontsize=7, color='0.15', arrowprops=dict(arrowstyle='-', color='0.55', lw=0.6))
    ax.text(0.13, 104, 'no limit', fontsize=7, color='0.15', va='bottom')
    ax.text(26, 4, '24-hour hold', fontsize=7, color='0.15', va='bottom')
    ax.annotate('\\$2M per hour', xy=(16, b + r * 16), xytext=(0.9, 64), fontsize=7, color='0.15',
                arrowprops=dict(arrowstyle='-', color='0.55', lw=0.6))
    ax.set_ylim(-4, 118)
    ax.set_yticks([0, 25, 50, 75, 100])
    ax.set_ylabel('Value let out (USD M)')
    hz.tag(ax, '(a)')
    # (b) when the responses came, weighted by value (solid) and by failure (dashed); the dashed
    # curve crosses 50% at the median that panel (a) marks
    ds = sorted(ev)
    tot = sum(a for _, a in ds)
    for weight, style in (('value', dict(color=hz.INK, lw=1.2, ls='-')), ('failure', dict(color=MID, lw=1.0, ls='--'))):
        xs, ys, acc = [0.1], [0.0], 0.0
        for i, (d, a) in enumerate(ds):
            acc = acc + a if weight == 'value' else i + 1
            xs.append(d)
            ys.append(100 * acc / (tot if weight == 'value' else len(ds)))
        xs.append(2000)
        ys.append(ys[-1])
        bx.step(xs, ys, where='post', label=f'by {weight}', **style)
    bx.legend(frameon=False, fontsize=6.5, loc='lower right', handlelength=1.8, borderaxespad=0.2)
    bx.set_ylim(-4, 104)
    bx.set_yticks([0, 50, 100])
    bx.set_ylabel('Responded (%)')
    fig.align_ylabels([ax, bx])
    bx.set_xscale('log')
    bx.set_xlim(0.1, 2000)
    ticks = [0.1, 1, 24, 168, 24 * 70]
    bx.xaxis.set_major_locator(FixedLocator(ticks))
    bx.xaxis.set_minor_locator(NullLocator())
    bx.set_xticklabels(['6 min', '1 h', '1 day', '1 week', '10 weeks'])
    bx.set_xlabel('Time since the first unauthorized release')
    hz.tag(bx, '(b)')
    for a in (ax, bx):
        hz.style_ticklabels(a)
    hz.save(fig, HERE / 'figures' / 'fig_example.pdf')


def replay_events():
    """Timed failures as the replay loads them (replay_incidents.load): what a release-point rule and
    a verifier-side rule see comes from replay_incidents.loss, so the figure and the text share one
    coding (a verifier-side rule also sees the class CHECK failures of the verifiers' own
    software and the redemption legs of unbacked mints)."""
    sys.path.insert(0, str(PROBES))
    import replay_incidents as ri
    rows = ri.load(str(PROBES / 'results' / 'incidents.csv'))
    return ri, [e for e in rows if not np.isnan(e['D_h'])]


def replay():
    """Figure 3: contained share of the timed failures' value, (a) token bucket with refill r and
    capacity r times one hour, (b) hold H cancelled by the response (a step function in H)."""
    ri, ev = replay_events()
    tot = sum(e['A'] for e in ev)
    rs = np.geomspace(0.05, 100, 400)          # USD M per hour
    Hs = np.geomspace(0.1, 400, 2000)          # hours
    fig, axes = plt.subplots(1, 2, figsize=(3.45, 1.85), sharey=True, gridspec_kw={'wspace': 0.12})
    for placement, style in (('release', dict(color=hz.INK, lw=1.4, ls='-')),
                             ('verifier', dict(color=MID, lw=1.1, ls='--'))):
        ramp = [100 * (1 - sum(ri.loss(e, 'ramp', r * 1e6, placement) for e in ev) / tot) for r in rs]
        hold = [100 * (1 - sum(ri.loss(e, 'cliff', H, placement) for e in ev) / tot) for H in Hs]
        axes[0].plot(rs, ramp, **style)
        axes[1].step(Hs, hold, where='post', **style)
    for ax, xlabel, tag in ((axes[0], 'Refill (USD M per hour)', '(a) bucket'), (axes[1], 'Hold (hours)', '(b) hold')):
        ax.set_xscale('log')
        ax.set_xlabel(xlabel)
        ax.set_ylim(-4, 104)
        ax.set_yticks([0, 25, 50, 75, 100])
        ax.xaxis.set_minor_locator(NullLocator())
        hz.tag(ax, tag)
        hz.style_ticklabels(ax)
    axes[0].set_ylabel('Value contained (%)')
    axes[0].set_xlim(0.05, 100)
    axes[0].xaxis.set_major_locator(FixedLocator([0.1, 1, 10, 100]))
    axes[0].set_xticklabels(['0.1', '1', '10', '100'])
    axes[1].set_xlim(0.1, 400)
    axes[1].xaxis.set_major_locator(FixedLocator([1, 6, 24, 168]))
    axes[1].set_xticklabels(['1', '6', '24', '168'])
    axes[0].text(0.07, 70, 'release point', fontsize=7, color='0.15')
    axes[0].text(0.07, 13, 'verifier side', fontsize=7, color='0.42')
    hz.save(fig, HERE / 'figures' / 'fig_replay.pdf')


def ccip_mismatch():
    """Figure 4: today's inbound bucket's release within D over the zero-delay minimum E^(D), per lane
    (data/ccip/derived/inbound_mismatch.json; sorted by the six-hour ratio). The lane whose outbound
    bucket bound so often that its traffic traces it is marked."""
    import json
    rec = json.loads((PROBES / 'data' / 'ccip' / 'derived' / 'inbound_mismatch.json').read_text(encoding='utf-8'))
    lanes = sorted((r for r in rec if r['in']), key=lambda r: r['in']['6 h'])
    x = np.arange(1, len(lanes) + 1)
    one = [r['in']['1 h'] for r in lanes]
    six = [r['in']['6 h'] for r in lanes]
    fig, ax = plt.subplots(figsize=(3.45, 2.1))
    ax.axhline(1, color=hz.GUIDE, lw=0.8, ls='--', zorder=0)
    for xi, a, b in zip(x, one, six):
        ax.plot([xi, xi], [a, b], color='0.75', lw=0.8, zorder=1)
    ax.plot(x, one, ls='none', marker='o', ms=4.2, mfc='white', mec=MID, mew=0.9, zorder=3, label='$D = 1$ h')
    ax.plot(x, six, ls='none', marker='o', ms=4.2, mfc=hz.INK, mec='white', mew=0.5, zorder=4, label='$D = 6$ h')
    k = next(i for i, r in enumerate(lanes) if r['lane'] == 'lane-08')
    ax.annotate('traffic traces\nits own bucket', xy=(x[k], six[k]), xytext=(x[k] + 1.2, 0.2), fontsize=6.5, color='0.15',
                arrowprops=dict(arrowstyle='-', color='0.55', lw=0.6))
    ax.set_yscale('log')
    ax.set_ylim(0.1, 20)
    ax.yaxis.set_major_locator(FixedLocator([0.1, 0.3, 1, 3, 10]))
    ax.set_yticklabels(['0.1', '0.3', '1', '3', '10'])
    ax.yaxis.set_minor_locator(NullLocator())
    ax.set_xticks(x)
    ax.set_xticklabels([])
    ax.set_xlabel('CCIP token lanes, sorted by the six-hour ratio')
    ax.set_ylabel('Inbound bucket / minimum')
    ax.text(0.6, 1.12, 'looser than the traffic needs', fontsize=7, color='0.15', va='bottom')
    ax.text(0.6, 0.89, 'tighter', fontsize=7, color='0.15', va='top')
    ax.legend(frameon=False, fontsize=7, loc='upper left', bbox_to_anchor=(0.0, 1.02))
    hz.style_ticklabels(ax)
    hz.save(fig, HERE / 'figures' / 'fig_ccip.pdf')


def perbridge_frontier():
    """Limits fitted to each failed bridge's own traffic (results/replay_perbridge.json), not in the
    paper at present.  Share of the failures' value kept against the share of legitimate value
    delayed or sent to review in the 30 days before each failure, over the margins 1 to 3;
    (a) by value, (b) averaged over failures."""
    import json
    pb = json.loads((PROBES / 'results' / 'replay_perbridge.json').read_text(encoding='utf-8'))
    A = pb['aggregate']
    margins = ['1.0', '1.25', '1.5', '2.0', '3.0']
    designs = [('bucket 6h m={}', 'bucket', dict(color=hz.INK, lw=1.3, ls='-', marker='o', ms=3.4, mfc=hz.INK, mec='white', mew=0.5)),
               ('review 1h m={} q=0.999', 'review, 1 in 1,000', dict(color=MID, lw=1.1, ls='--', marker='s', ms=3.4, mfc='white', mec=MID, mew=0.9)),
               ('review 1h m={} q=0.99', 'review, 1 in 100', dict(color='0.6', lw=1.0, ls=':', marker='^', ms=3.6, mfc='white', mec='0.45', mew=0.9))]
    fig, axes = plt.subplots(1, 2, figsize=(3.45, 1.95), sharey=True, gridspec_kw={'wspace': 0.12})
    for ax, weight, tag in ((axes[0], 'value', '(a) by value'), (axes[1], 'event', '(b) by failure')):
        for pattern, label, style in designs:
            keys = [pattern.format(m) for m in margins]
            xs = [100 * A[k]['test_o1']['total_delayed_share'] for k in keys]
            ys = [100 * A[k]['loss'][weight] for k in keys]
            ax.plot(xs, ys, label=label, **style)
        ax.axhline(100 * A['floor']['loss'][weight], color=hz.GUIDE, lw=0.8, ls='-.', zorder=0)
        ax.set_xlim(-2, 100)
        ax.set_ylim(50, 100)
        hz.tag(ax, tag)
        hz.style_ticklabels(ax)
    axes[0].set_ylabel('Value kept (%)')
    fig.text(0.53, -0.04, 'Legitimate value delayed or reviewed, last 30 days (%)', ha='center', fontsize=8)
    axes[0].text(40, 100 * A['floor']['loss']['value'] - 4.5, 'floor, in sample', fontsize=6.5, color='0.35')
    axes[1].legend(frameon=False, fontsize=6.5, loc='center right', bbox_to_anchor=(1.05, 0.6), handlelength=1.5, borderaxespad=0.0)
    hz.save(fig, HERE / 'figures' / 'fig_perbridge.pdf')


if __name__ == '__main__':
    example()
    replay()
    ccip_mismatch()
    perbridge_frontier()
