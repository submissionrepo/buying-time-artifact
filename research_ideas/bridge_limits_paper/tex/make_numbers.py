"""Generate numbers.tex (LaTeX macros) and numbers.json from the research outputs.

Every number in the paper comes from here. Sources are under
research_ideas/probes/bridge_limits/: the event table (results/incidents.csv), the event
replay (replay_incidents.py), the CCIP lane census, static fits, out-of-sample tests and
rolling recalibration (data/ccip/derived/), the Wormhole envelopes, transfer shares and
Governor usage (data/wormhole/), the stake reads (data/stake/), the prototype's gas
snapshot (prototype/snapshots/GasBench.json), plus rules.csv in this directory (deployed
rules, from results/limiter_code_facts.md section 3). The asserts pin values that the paper's
text states.
Run from any directory with the Python environment of requirements.txt.
"""
import csv
import json
import math
import statistics
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROBES = HERE.parents[1] / 'probes' / 'bridge_limits'
sys.path.insert(0, str(PROBES))
import replay_incidents  # noqa: E402

WORDS = {0: 'no', 1: 'one', 2: 'two', 3: 'three', 4: 'four', 5: 'five', 6: 'six', 7: 'seven',
         8: 'eight', 9: 'nine', 10: 'ten', 11: 'eleven', 12: 'twelve', 13: 'thirteen', 14: 'fourteen',
         15: 'fifteen', 16: 'sixteen', 17: 'seventeen', 18: 'eighteen', 19: 'nineteen', 20: 'twenty'}


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def rows(path):
    with open(path, encoding='utf-8') as f:
        return list(csv.DictReader(f))


def pct(x, digits=1):
    return f'{100 * x:.{digits}f}'


def utc(s):
    return datetime.strptime(s, '%Y-%m-%dT%H:%M:%SZ')


def musd(x, digits=1):
    return f'{x / 1e6:,.{digits}f}'


def hms(s):
    """Duration as in the event table's summaries: d h min, h min, min s or s."""
    s = int(round(s))
    d, r = divmod(s, 86400)
    h, r = divmod(r, 3600)
    m, sec = divmod(r, 60)
    if d:
        return f'{d}\\,d {h}\\,h'
    if h:
        return f'{h}\\,h {m}\\,min'
    if m:
        return f'{m}\\,min {sec}\\,s'
    return f'{sec}\\,s'


def quart(xs):
    q = statistics.quantiles(xs, n=4, method='inclusive')
    return q[0], statistics.median(xs), q[2]


def main():
    n = {}

    # --- events (bridge set of the event table) ---
    allrows = rows(PROBES / 'results' / 'incidents.csv')
    ev = [r for r in allrows if r['in_bridge_set'] == 'yes']
    amount = {r['id']: float(r['amount_usd']) for r in ev}
    total = sum(amount.values())
    n['nRecords'] = str(len(allrows))
    n['nExcluded'] = str(len(allrows) - len(ev))
    n['nEvents'] = str(len(ev))
    n['valueEventsB'] = f'{total / 1e9:.1f}'
    n['valueEventsM'] = musd(total, 0)
    n['eventsFirstYear'] = min(r['date'] for r in ev)[:4]
    n['eventsLastYear'] = max(r['date'] for r in ev)[:4]
    dur = [float(r['outflow_duration_s']) for r in ev if r['outflow_duration_s']]
    resp = {r['id']: float(r['response_delay_s']) for r in ev if r['response_delay_s']}
    med_dur, med_resp = statistics.median(dur), statistics.median(resp.values())
    assert (int(med_dur) // 60, int(med_dur) % 60) == (7, 52), med_dur          # results file section 5
    assert (int(med_resp) // 3600, int(med_resp) % 3600 // 60) == (3, 42), med_resp
    n['medOutflowMin'] = str(round(med_dur / 60))
    n['medOutflowWords'] = WORDS[round(med_dur / 60)]
    n['medRespH'], n['medRespM'] = str(int(med_resp) // 3600), str(int(med_resp) % 3600 // 60)
    n['nTimedEvents'] = str(len(resp))
    n['nUntimedEvents'] = str(len(ev) - len(resp))
    # timing table: median and quartiles of each lag (bridge set)
    timing = [('outflow_duration_s', 'Last release'),
              ('time_to_90pct_s', '90\\% of the value out'),
              ('first_alert_lag_s', 'Alert by a third party'),
              ('detection_lag_s', 'Acknowledgment'),
              ('pause_lag_s', 'Pause'),
              ('response_delay_s', 'First response')]
    tab = []
    for key, label in timing:
        xs = [float(r[key]) for r in ev if r[key]]
        q1, q2, q3 = quart(xs)
        tab.append({'label': label, 'n': len(xs), 'q1': hms(q1), 'median': hms(q2), 'q3': hms(q3)})
    (HERE / 'timing.json').write_text(json.dumps(tab, indent=1) + '\n', encoding='utf-8')
    # value released within ten minutes of the first release, events where the share is determined
    det = [(amount[r['id']], float(r['share_10m'])) for r in ev if r['share_10m'] and '-' not in r['share_10m']]
    share10 = sum(a for a, _ in det) and sum(a * s for a, s in det) / sum(a for a, _ in det)
    assert abs(share10 - 0.683) < 5e-4, share10
    n['shareTenMinPct'] = pct(share10, 0)
    n['nShareTenMin'] = str(len(det))
    # pauses: how many came after the last release
    paused = [r for r in ev if r['pause_utc']]
    after = [r for r in paused if r['last_release_utc'] and utc(r['pause_utc']) > utc(r['last_release_utc'])]
    n['nPaused'], n['nPausedAfterLast'] = str(len(paused)), str(len(after))
    # response basis of the first response
    basis = defaultdict(int)
    for r in ev:
        if r['response_delay_s']:
            basis[r['response_basis']] += 1
    n['nRespAck'] = str(basis['acknowledgment'])
    n['nRespPause'] = str(basis['pause'] + basis['pause report'])
    # responses later than a deadline, by events and by value
    tv = sum(amount[i] for i in resp)
    for hours, tag in ((1, 'One'), (6, 'Six'), (24, 'Day'), (48, 'TwoDays')):
        late = [i for i, d in resp.items() if d > hours * 3600]
        n[f'late{tag}EventsPct'] = pct(len(late) / len(resp), 0)
        n[f'late{tag}ValuePct'] = pct(sum(amount[i] for i in late) / tv, 0)
    # value by failure class and by release side (all events of the bridge set)
    for c in 'VDSO':
        n[f'class{c}Pct'] = pct(sum(amount[r['id']] for r in ev if r['failure_class'] == c) / total, 0 if c != 'O' else 1)
        n[f'nClass{c}'] = str(sum(r['failure_class'] == c for r in ev))
    for side, tag in (('escrow', 'Escrow'), ('mint', 'Mint'), ('both', 'Both')):
        n[f'side{tag}Pct'] = pct(sum(amount[r['id']] for r in ev if r['release_side'] == side) / total, 0)

    # --- event replay (Theorems on shape and placement) ---
    res = replay_incidents.summarize(replay_incidents.load(str(PROBES / 'results' / 'incidents.csv')))
    assert res['n_timed'] == len(resp)
    (HERE / 'replay.json').write_text(json.dumps(res, indent=1) + '\n', encoding='utf-8')
    n['valueTimedB'] = f"{res['value_timed'] / 1e9:.1f}"
    n['valueTimedM'] = musd(res['value_timed'], 0)
    n['valueUntimedM'] = musd(total - res['value_timed'], 0)
    curve = lambda key, p: next(x['contained_share'] for x in res['curves'][key] if x['param'] == p)
    n['rampOneMPct'] = pct(curve('release:ramp', 1e6))
    n['rampPointOneMPct'] = pct(curve('release:ramp', 1e5))
    n['rampTenMPct'] = pct(curve('release:ramp', 1e7))
    n['rampThirtyMPct'] = pct(curve('release:ramp', 3e7))
    n['cliffDayPct'] = pct(curve('release:cliff', 24))
    n['cliffOneHPct'] = pct(curve('release:cliff', 1))
    n['cliffSixHPct'] = pct(curve('release:cliff', 6))
    n['cliffThreeDPct'] = pct(curve('release:cliff', 72))
    n['freezeOneMPct'] = pct(curve('release:freeze', 1e6))
    n['freezeTenMPct'] = pct(curve('release:freeze', 1e7))
    n['freezeHundredMPct'] = pct(curve('release:freeze', 1e8))
    verifier_best = max(x['contained_share'] for k, v in res['curves'].items() if k.startswith('verifier:') for x in v)
    # the verifier-side ceiling is the share of the timed value that passes the verifiers
    # (replay_incidents.verifier_share), the limit of every verifier-side rule as its parameters
    # tighten; the grid maximum approaches it from below
    timed_rows = [e for e in replay_incidents.load(str(PROBES / 'results' / 'incidents.csv')) if e['D_h'] == e['D_h']]
    ceiling = sum(e['A'] * replay_incidents.verifier_share(e) for e in timed_rows) / sum(e['A'] for e in timed_rows)
    assert ceiling >= verifier_best - 1e-12
    n['verifierMaxPct'] = pct(ceiling)
    rest3 = sorted(timed_rows, key=lambda e: -e['A'])[3:]
    assert all(replay_incidents.verifier_share(e) == 0.0 for e in sorted(timed_rows, key=lambda e: -e['A'])[:3])
    n['verifierCeilNoTopThreePct'] = pct(sum(e['A'] * replay_incidents.verifier_share(e) for e in rest3) / sum(e['A'] for e in rest3))
    n['verifierRampThirtyMPct'] = pct(curve('verifier:ramp', 3e7))
    n['valueClassSTimedM'] = musd(res['value_by_class_timed']['S'], 0)
    # the release point no longer sees the two check failures whose flaw also reached a
    # limit in the releasing contract (incident_coding.csv), which moves the 24-hour hold from 80.9
    # one limit per release contract, so a failure that released through k contracts
    # meets k limits (replay_incidents.py, PER_CHANNEL); the ramp of 1M an hour moves from 89.8
    print('check', n['rampOneMPct'], n['cliffDayPct'], n['verifierMaxPct'])
    assert n['rampOneMPct'] == '87.2' and n['cliffDayPct'] == '80.7'

    # --- traffic-matched replay, robustness, price of a single bucket (replay_matched.py) ---
    rm = read(PROBES / 'results' / 'replay_matched.json')
    assert rm['n_timed'] == len(resp)
    mt = rm['matched']
    n['matchSmallTwelvePct'] = pct(mt['small|12 months']['contained'])
    n['matchFullTwelvePct'] = pct(mt['full|12 months']['contained'])
    n['matchSmallTwentyFourPct'] = pct(mt['small|24 months']['contained'])
    n['matchFullTwentyFourPct'] = pct(mt['full|24 months']['contained'])
    n['matchEnvFourHM'] = musd(mt['small|12 months']['E_at']['4h'])
    n['matchEnvFourHTwentyFourM'] = musd(mt['small|24 months']['E_at']['4h'])
    rob = rm['robust']
    ramp = rob['uniform ramp 1e+06']
    n['robRampTimesTwoPct'] = pct(ramp['D_times_2'])
    n['robRampPlusSixPct'] = pct(ramp['D_plus_6h'])
    n['robRampPausesPct'] = pct(ramp['pauses_only'])
    n['robPausesN'] = str(ramp['n_pauses'])
    n['robRampEventPct'] = pct(ramp['event_weighted'], 0)
    n['robRampNoLargestPct'] = pct(ramp['without_largest'])
    n['robLargestSharePct'] = pct(ramp['largest_share_of_value'], 0)
    n['robCliffEventPct'] = pct(rob['uniform cliff 24']['event_weighted'], 0)
    n['robMatchEventPct'] = pct(rob['matched small|12 months']['event_weighted'], 0)
    n['robMatchFullEventPct'] = pct(rob['matched full|12 months']['event_weighted'], 0)
    n['matchEnvFourHFullM'] = musd(mt['full|12 months']['E_at']['4h'])
    n['matchEnvFourHFullTwentyFourM'] = musd(mt['full|24 months']['E_at']['4h'], 0)
    ver = rob['verifier ramp 1e+06']
    variant_keys = ('base', 'D_times_2', 'D_plus_1h', 'D_plus_6h', 'pauses_only', 'event_weighted', 'without_largest')
    n['robVerifierMaxPct'] = pct(max(ver[k] for k in variant_keys))
    n['robVerifierTopThreePct'] = pct(ver['without_top3'])
    (HERE / 'robust.json').write_text(json.dumps(rob, indent=1) + '\n', encoding='utf-8')
    fc = rm['flow_condition']
    n['stakeFlowMedianM'] = musd(fc['full|12 months']['E_at_median_D'])
    n['stakeFlowMeanM'] = musd(fc['full|12 months']['mean_over_D'])
    n['stakeFlowReviewMeanM'] = musd(fc['small|12 months']['mean_over_D'])
    sbw = rm['single_bucket_wormhole']
    n['oneBucketWormThreeH'] = f"{sbw['3h']['ratio']:.2f}"
    n['oneBucketWormSixH'] = f"{sbw['6h']['ratio']:.2f}"
    n['oneBucketWormDay'] = f"{sbw['24h']['ratio']:.2f}"
    for D, tag in (('1h', 'One'), ('6h', 'Six')):
        sb = rm[f'single_bucket_ccip_{D}']
        n[f'oneBucketCcip{tag}Med'] = f"{sb['median']:.2f}"
        n[f'oneBucketCcip{tag}Max'] = f"{sb['max']:.2f}"
        n[f'oneBucketCcip{tag}MedPct'] = pct(sb['median'] - 1, 0)

    # --- placement with control, response times as a variable, weightings, best bucket, K buckets ---
    r2 = read(PROBES / 'results' / 'replay_variants.json')
    P = r2['placement']
    for rule, tag in (('bucket 1M/h', 'Ramp'), ('hold 24 h', 'Hold'), ('matched benchmark', 'Match')):
        n[f'pl{tag}SepPct'] = pct(P[rule]['release_separated'])
        n[f'pl{tag}GovPct'] = pct(P[rule]['release_governed'])
        n[f'pl{tag}PessPct'] = pct(P[rule]['release_pessimistic'])
        n[f'pl{tag}VerPct'] = pct(P[rule]['verifier'])
        n[f'pl{tag}ContractPct'] = pct(P[rule]['release_contract_only'])
        R = r2['response'][rule]
        for k, kt in (('x2', 'Two'), ('x5', 'Five'), ('x10', 'Ten'), ('outflow_detected_never', 'Outflow'),
                      ('no_independent_pause_never', 'NoPause'), ('alert_time', 'Alert'), ('alarm_10min', 'Alarm'),
                      ('alarm_1h', 'AlarmHour'), ('all57_untimed_never', 'All')):
            n[f'rt{tag}{kt}Pct'] = pct(R[k])
        Wt = r2['weights'][rule]
        n[f'wt{tag}EventPct'] = pct(Wt['event'], 0)
        n[f'wt{tag}NetPct'] = pct(Wt['net'])
    sh = r2['shares']
    n['vKeysCtrlN'], n['vN'] = str(sh['n_V_keys_ctrl_yes']), str(sh['n_V'])
    n['vKeysCtrlValuePct'] = pct(sh['V_keys_ctrl_yes_value'])
    n['dFlawReachN'], n['dN'] = str(sh['n_D_flaw_reach_yes']), str(sh['n_D'])
    n['noPauseValuePct'] = pct(sh['no_independent_pause_value'], 0)
    n['outflowDetectedN'] = str(sh['n_outflow_detected'])
    n['outflowDetectedValuePct'] = pct(sh['outflow_detected_value'], 0)
    n['breakevenRamp'] = f"{r2['breakeven_factor_bucket']:g}"
    n['breakevenMatch'] = f"{r2['breakeven_factor_matched']:g}"
    bb = r2['best_bucket']
    n['meanRespH'] = f"{bb['mean_D_h']:.0f}"
    b1, b2 = bb['by_W']['1e+09'], bb['by_W']['2e+09']
    n['bestOneBDStarH'] = f"{b1['mean_D_below_crossing_h']:.0f}"
    n['bestOneBGainPct'] = pct(b1['expected_loss_median_matched'] / b1['expected_loss'] - 1, 0)
    n['bestTwoBDStarH'] = f"{b2['mean_D_below_crossing_h']:.0f}"
    n['bestTwoBGainPct'] = pct(b2['expected_loss_median_matched'] / b2['expected_loss'] - 1, 0)
    kb = r2['k_buckets']
    n['kBucketsHullPct'] = pct(kb['max_ratio_to_majorant'] - 1, 0)
    n['kBucketsEnvPct'] = pct(kb['max_ratio_to_envelope'] - 1, 0)

    # --- failure coding (results/incident_coding.csv) ---
    cod = rows(PROBES / 'results' / 'incident_coding.csv')
    from collections import Counter
    dc = Counter(r['detection_channel'] for r in cod)
    ph = Counter(r['pause_holder'] for r in cod)
    n['detThirdParty'], n['detOperator'], n['detUnknown'] = str(dc['third_party_alert']), str(dc['operator_monitoring']), str(dc['unknown'])
    n['detShortfall'] = str(dc['escrow_or_balance_shortfall'] + dc['user_report_or_failed_withdrawal'])
    n['pauseIndependent'], n['pauseNone'], n['pauseControlled'], n['pauseUnknown'] = (
        str(ph['independent_of_failure']), str(ph['no_pause_function']), str(ph['controlled_by_failing_party']), str(ph['unknown']))
    n['classAgree'] = str(sum(r['class_agrees'].strip().lower() in ('yes', 'true', '1') for r in cod))
    rec_usd = sum(float(r['recovered_usd'] or 0) for r in cod)
    n['nRecovered'] = str(sum(float(r['recovered_usd'] or 0) > 0 for r in cod))
    n['recoveredM'] = musd(rec_usd, 0)
    n['recoveredPct'] = pct(rec_usd / total, 0)
    nch = Counter(r['n_chains_released'].strip() for r in cod)
    n['nSingleChain'] = str(nch['1'])
    n['nBorderline'] = str(sum(r['borderline'].strip() not in ('', 'none') for r in cod))

    # --- CCIP inbound buckets, review path, historical configurations ---
    rv = read(PROBES / 'data' / 'ccip' / 'derived' / 'review_policy.json')['pooled']
    v2 = read(PROBES / 'data' / 'ccip' / 'derived' / 'rolling_v2.json')['pooled']['in']
    base_key = '1 h m=1.0 q=None'
    n['ccipInTodayDelayedPct'] = pct(rv[base_key]['current_delayed_share'])
    n['ccipInTodayMeanDelayH'] = f"{rv[base_key]['current_mean_delay_h_per_dollar']:.2f}"
    n['ccipInTodayWaitPFifty'] = f"{v2['current_wait_p50_h']:.1f}"
    rk = rv['1 h m=1.5 q=0.99']
    n['ccipRevDelayedPct'] = pct(rk['delayed_share'])
    n['ccipRevMeanDelayH'] = f"{rk['mean_delay_h_per_dollar']:.3f}"
    n['ccipRevPerMonth'] = f"{rk['reviews_per_lane_month']:.1f}"
    n['ccipRevValuePct'] = pct(rk['review_share'], 0)
    n['ccipRevCapOne'] = f"{rk['median_cap_ratio']['1 h']:.2f}"
    n['ccipRevCapSix'] = f"{rk['median_cap_ratio']['6 h']:.2f}"
    # a reviewed transfer waits the review's latency L; the review variant delays legitimate
    # value for fewer hours per dollar than today's buckets while L is below the break-even latency
    today_h = rv[base_key]['current_mean_delay_h_per_dollar']

    def breakeven(v):
        return (today_h - v['mean_delay_h_per_dollar']) / v['review_share']
    n['ccipRevBreakevenH'] = f'{breakeven(rk):.1f}'
    n['ccipRevAtOneH'] = f"{rk['mean_delay_h_per_dollar'] + rk['review_share']:.2f}"
    one_h = {k: v for k, v in rv.items() if k.startswith('1 h ') and not k.endswith('q=None')}
    lower_both = {k for k, v in one_h.items() if v['median_cap_ratio']['1 h'] < 1 and v['median_cap_ratio']['6 h'] < 1}
    n['ccipRevVariants'] = WORDS[len(one_h)]
    n['ccipRevLowerBoth'] = WORDS[len(lower_both)].capitalize()
    n['ccipRevBreakevenMinH'] = f'{min(breakeven(one_h[k]) for k in lower_both):.1f}'
    n['ccipRevBreakevenMaxH'] = f'{max(breakeven(one_h[k]) for k in lower_both):.1f}'
    # how long reviews take where a bridge has one today (data/review_latency/ronin_locks.py:
    # withdrawals the Ronin gateway locked for review since its 2022 relaunch, matched to their unlocks)
    rl = read(PROBES / 'results' / 'review_latency_ronin.json')
    assert rl['n_locked'] == rl['n_unlocked'] == rl['latency_s']['n'] and rl['n_locked_never_unlocked'] == 0
    lat_h = sorted(r['latency_s'] / 3600 for r in rl['rows'])
    n['roninReviewN'] = WORDS[rl['n_locked']]
    n['roninReleasesAll'] = f"{rl['n_releases_all']:,}"
    n['roninReviewMinH'] = f'{lat_h[0]:.0f}'
    n['roninReviewMedH'] = f"{rl['latency_s']['median'] / 3600:.0f}"
    n['roninReviewMaxD'] = f'{lat_h[-1] / 24:.1f}'
    lags = read(PROBES / 'data' / 'ccip' / 'derived' / 'lags.json')['chain-047']  # chain-047: Ethereum
    n['ccipEthLagPOneMin'] = f"{lags['p01']:.0f}"
    n['ccipEthLagMedMin'] = f"{lags['p50']:.0f}"
    nr = rv['6 h m=1.5 q=None']
    n['ccipNoRevDelayedPct'] = pct(nr['delayed_share'])
    n['ccipNoRevMeanDelayH'] = f"{nr['mean_delay_h_per_dollar']:.1f}"
    n['ccipNoRevWaitPFifty'] = f"{nr['wait_p50_h']:.0f}"
    n['ccipNoRevCapSix'] = f"{nr['median_cap_ratio']['6 h']:.2f}"
    n['ccipLanesDisabledHalf'] = str(v2['n_lanes_disabled_over_half'])
    n['ccipInLanes'] = str(v2['n_with_bucket'])
    (HERE / 'review.json').write_text(json.dumps(rv, indent=1) + '\n', encoding='utf-8')

    # --- CCIP: census of outbound buckets (lanes.json) ---
    lim = read(PROBES / 'data' / 'ccip' / 'derived' / 'limits_distribution.json')
    act = lim['stats']['active']
    n['ccipEntries'] = f"{lim['n_entries']:,}"
    n['ccipEnabled'] = f"{lim['n_enabled']:,}"
    n['ccipActive'] = f"{lim['class_counts']['active']:,}"
    n['ccipNearZero'] = str(lim['class_counts']['near-zero capacity'])
    n['ccipRefillOneH'] = str(lim['refill_bins_active']['1.00-1.01 h'])
    n['ccipRefillDay'] = str(lim['refill_bins_active']['23.5-24.5 h'])
    n['ccipMedRefillH'] = f"{act['refill_h']['p50']:.1f}"
    n['ccipMedCapK'] = f"{act['capacity_usd']['p50'] / 1e3:,.0f}"
    n['ccipCapQOneK'] = f"{act['capacity_usd']['p25'] / 1e3:,.0f}"
    n['ccipCapQThreeM'] = f"{act['capacity_usd']['p75'] / 1e6:.2f}"
    n['ccipMedRateK'] = f"{act['rate_usd_per_h']['p50'] / 1e3:,.0f}"
    n['ccipTokens'] = str(lim['n_tokens_enabled'])
    assert n['ccipMedCapK'] == '623' and n['ccipMedRefillH'] == '6.0'

    # --- CCIP: the studied lanes (selection rule in ccip/selection.json) ---
    sel = read(PROBES / 'ccip' / 'selection.json')
    n['ccipSelLanes'] = str(len(sel['lanes']))
    n['ccipSelSharePct'] = pct(sel['share_of_window_value'])

    # --- CCIP: the deployed bucket against the zero-delay minimum at D (static, in sample) ---
    rec = read(PROBES / 'data' / 'ccip' / 'derived' / 'recommended_buckets.json')
    n['ccipFitLanes'] = str(len(rec))
    withb = [r for r in rec if r['current_enabled']]
    n['ccipFitLanesBucket'] = str(len(withb))
    for D, tag in (('1 h', 'One'), ('6 h', 'Six')):
        ratios = [r[D]['current_over_hull'] for r in withb]
        n[f'ccipLoose{tag}'] = str(sum(x > 1 for x in ratios))
        n[f'ccipTight{tag}'] = str(sum(x < 1 for x in ratios))
        n[f'ccipRatioMin{tag}'] = f'{min(ratios):.2f}'
        n[f'ccipRatioMax{tag}'] = f'{max(ratios):.2f}'
        n[f'ccipInSampleDelayed{tag}'] = str(sum(r[D]['in_sample_delayed'] for r in rec))
    assert (n['ccipLooseOne'], n['ccipTightOne'], n['ccipLooseSix'], n['ccipTightSix']) == ('7', '10', '9', '8')

    # --- CCIP: static fit, first half against second half ---
    oos = read(PROBES / 'data' / 'ccip' / 'derived' / 'out_of_sample.json')
    shares6 = [r['6 h']['delayed_value'] / r['test_value'] for r in oos]
    n['ccipOosLanes'] = str(len(oos))
    n['ccipOosZero'] = str(sum(s == 0 for s in shares6))
    n['ccipOosMaxPct'] = pct(max(shares6), 0)
    n['ccipOosOverHalf'] = str(sum(s > 0.5 for s in shares6))

    # --- CCIP: rolling recalibration of buckets matched to the response time ---
    lanes = read(PROBES / 'data' / 'ccip' / 'derived' / 'rolling_policy.json')
    n['ccipLanes'] = str(len(lanes))

    def rolling(key):
        wb = [r for r in lanes if not math.isnan(r[key]['current_delayed_share'])]
        tvb = sum(r[key]['test_value'] * r['price_usd'] for r in wb)
        pol = sum(r[key]['delayed_share'] * r[key]['test_value'] * r['price_usd'] for r in wb) / tvb
        cur = sum(r[key]['current_delayed_share'] * r[key]['test_value'] * r['price_usd'] for r in wb) / tvb
        ratios = sorted(r[key]['mean_beta'] / r[key]['current_beta'] for r in lanes
                        if not math.isnan(r[key]['current_beta']) and r[key]['current_beta'] > 0
                        and not math.isnan(r[key]['mean_beta']))
        return pol, cur, ratios[len(ratios) // 2], len(wb)

    rolling_rows = []
    for key in ('1 h m=1.0', '1 h m=1.5', '1 h m=2.0', '6 h m=1.0', '6 h m=1.5', '6 h m=2.0'):
        pol, cur, ratio, nb = rolling(key)
        rolling_rows.append({'key': key, 'delayed': pol, 'current': cur, 'ratio': ratio, 'lanes': nb})
    (HERE / 'rolling.json').write_text(json.dumps(rolling_rows, indent=1) + '\n', encoding='utf-8')
    get = {r['key']: r for r in rolling_rows}
    cur = get['6 h m=1.5']['current']
    assert all(abs(r['current'] - cur) < 1e-12 for r in rolling_rows)
    n['ccipLanesBucket'] = str(get['6 h m=1.5']['lanes'])
    n['ccipCurrentDelayedPct'] = pct(cur)
    n['ccipSixDelayedPct'], n['ccipSixRatio'] = pct(get['6 h m=1.5']['delayed']), f"{get['6 h m=1.5']['ratio']:.2f}"
    n['ccipSixTwoDelayedPct'], n['ccipSixTwoRatio'] = pct(get['6 h m=2.0']['delayed']), f"{get['6 h m=2.0']['ratio']:.2f}"
    n['ccipOneTwoDelayedPct'], n['ccipOneTwoRatio'] = pct(get['1 h m=2.0']['delayed']), f"{get['1 h m=2.0']['ratio']:.2f}"
    assert (n['ccipCurrentDelayedPct'], n['ccipSixDelayedPct'], n['ccipSixRatio']) == ('21.2', '8.3', '0.66')

    # --- Wormhole: envelopes, pooling, large transfers, Governor usage ---
    pc = read(PROBES / 'data' / 'wormhole' / 'derived' / 'pooling_clean.json')
    full12, small12 = pc['series_full_hourly.csv|12 months'], pc['series_small_hourly.csv|12 months']
    inv = [1 / full12['pooling'][k]['ratio'] for k in ('1', '2', '3', '6', '12', '24')]
    n['poolLow'], n['poolHigh'] = f'{min(inv):.1f}', f'{max(inv):.1f}'
    rat = [full12['pooling'][k]['ratio'] for k in ('1', '2', '3', '6', '12', '24')]
    n['poolRatioLowPct'], n['poolRatioHighPct'] = pct(min(rat), 0), pct(max(rat), 0)
    n['wormChains'] = str(len(full12['per_chain']))
    n['wormChainsWords'] = WORDS[len(full12['per_chain'])]
    n['wormEnvOneHFullM'] = musd(full12['sum']['1'])
    n['wormEnvOneHSmallM'] = musd(small12['sum']['1'])
    n['wormEnvRatio'] = f"{full12['sum']['1'] / small12['sum']['1']:.1f}"
    n['wormEnvDayFullM'] = musd(full12['sum']['24'])
    n['wormEnvDaySmallM'] = musd(small12['sum']['24'])
    summ = read(PROBES / 'data' / 'wormhole' / 'flows' / 'summary.json')
    sh = [x for x in summ['shares'] if x['scope'] == '24m']
    n['wormBigN'] = str(sum(x['n_big'] for x in sh))
    n['wormBigValuePct'] = pct(sum(x['big_usd'] for x in sh) / sum(x['full_usd'] for x in sh))
    sh12 = [x for x in summ['shares'] if x['scope'] == '365d']   # the window of the 12-month envelopes
    n['wormBigTwelveN'] = str(sum(x['n_big'] for x in sh12))
    n['wormBigTwelveValuePct'] = pct(sum(x['big_usd'] for x in sh12) / sum(x['full_usd'] for x in sh12))
    usage = [r for r in rows(PROBES / 'data' / 'wormhole' / 'flows' / 'usage.csv')
             if r['timeline'] == 'release' and r['scope'] == '24m']
    above, hours = defaultdict(int), defaultdict(int)
    for r in usage:
        above[r['chain']] += int(float(r['hours_above_cap']))
        hours[r['chain']] += int(float(r['hours']))
    assert above['Sui'] == 415 and above['Ethereum'] == 13
    n['govSuiHours'] = str(above['Sui'])
    n['govSuiPct'] = pct(above['Sui'] / hours['Sui'])
    n['govEthHours'] = str(above['Ethereum'])
    others = sorted((v for k, v in above.items() if k != 'Sui'), reverse=True)
    n['govOtherMaxHours'] = str(others[0])
    n['govChains'] = str(len(above))

    # --- stake against value held ---
    val = read(PROBES / 'data' / 'stake' / 'onchain' / 'valuation_20261016T000856Z.json')
    pol = val['polygon']
    n['stakeMaxRatio'] = f"{pol['validator_set_stake_usd'] / pol['escrow_usd_total_partial']:.2f}"
    ax = read(PROBES / 'data' / 'stake' / 'api' / 'axelar_reads_20261016T000617Z.json')
    axl_usd = ax['validators']['sum_tokens_uaxl'] / 1e6 * val['prices_used']['axelar']['llama']
    large = [pol['validator_set_stake_usd'], val['chainlink']['total_usd'], axl_usd]
    n['stakeLargeMinM'] = musd(min(large), 0)
    n['stakeLargeMaxM'] = musd(max(large), 0)
    n['stakeLargeN'] = WORDS[len(large)]
    flow_mean = read(PROBES / 'results' / 'replay_matched.json')['flow_condition']['full|12 months']['mean_over_D']
    n['stakeLargeCoverWords'] = WORDS[sum(x >= flow_mean for x in large)].capitalize()
    n['stakeLargeCoverLow'] = WORDS[sum(x >= flow_mean for x in large)]
    # Chainlink's LINK staking secures a price feed, not CCIP (stake.csv), so the text names it apart;
    # of the validator stakes, Polygon's covers the mean flow and Axelar's does not
    n['stakeLinkM'] = musd(val['chainlink']['total_usd'], 0)
    n['stakePolygonM'] = musd(pol['validator_set_stake_usd'], 0)
    n['stakeAxelarM'] = musd(axl_usd, 0)
    assert pol['validator_set_stake_usd'] >= flow_mean > axl_usd
    sym = val['symbiotic']
    funded = sorted((v['totalStake_usd'] for v in sym.values()
                     if v.get('slasher_type') is not None and v['totalStake_usd'] > 1e5), reverse=True)
    n['stakeSlashableMaxM'] = musd(funded[0])
    n['stakeEmptyVaults'] = str(sum(1 for v in sym.values() if v['totalStake_usd'] == 0))
    n['stakeEmptyVaultsWords'] = WORDS[sum(1 for v in sym.values() if v['totalStake_usd'] == 0)]
    n['stakeBlock'] = f"{val['meta']['block']['number']:,}"
    n['stakeAxelarHeight'] = f"{int(ax['latest_block']['height']):,}"

    # --- deployed rules (Table of rules) ---
    rules = rows(HERE / 'rules.csv')
    n['nRules'] = str(len(rules))
    bounded = [r for r in rules if r['bound_without_response'] == 'yes']
    n['nRulesBounded'] = str(len(bounded))
    n['nRulesBoundedWords'] = WORDS[len(bounded)]
    n['nRulesBoundedControlled'] = str(sum(r['controlled_by_verifiers'] == 'yes' for r in bounded))
    n['nRulesBoundedControlledWords'] = WORDS[sum(r['controlled_by_verifiers'] == 'yes' for r in bounded)]
    n['nRulesVerifierSide'] = str(sum(r['stage'] == 'verifiers' for r in rules))
    n['nRulesVerifierSideWords'] = WORDS[sum(r['stage'] == 'verifiers' for r in rules)]
    n_auto = sum(r['auto_release'].startswith(('yes', 'delayed', 'hold')) for r in rules)
    n_net = sum(r['accounting'].startswith(('net', 'optional net')) for r in rules)
    n['nRulesAutoRelease'], n['nRulesAutoReleaseWords'] = str(n_auto), WORDS[n_auto]
    n['nRulesNet'], n['nRulesNetWords'] = str(n_net), WORDS[n_net]
    same = sum('deposits of the same token' in r['accounting'] for r in rules)
    n['nRulesNetSameToken'] = str(same)
    n['nRulesNetSameTokenWords'] = WORDS[same]

    # --- prototype gas (one escrow release; snapshot written by the harness) ---
    gas = {k: int(v) for k, v in read(PROBES / 'prototype' / 'snapshots' / 'GasBench.json').items()}
    lim2 = gas['limiter_queue'] + gas['limiter_execute_escrow']
    n['gasPlain'] = f"{gas['plain_release']:,}"
    n['gasWindow'] = f"{gas['window_release']:,}"
    n['gasWindowExtra'] = f"{gas['window_release'] - gas['plain_release']:,}"
    n['gasQueue'] = f"{gas['limiter_queue']:,}"
    n['gasExecute'] = f"{gas['limiter_execute_escrow']:,}"
    n['gasExecuteMint'] = f"{gas['limiter_execute_mint']:,}"
    n['gasLimiter'] = f'{lim2:,}'
    n['gasLimiterExtra'] = f"{lim2 - gas['plain_release']:,}"
    n['gasCancel'] = f"{gas['limiter_cancel']:,}"
    n['gasPause'] = f"{gas['limiter_pause']:,}"
    n['gasHashSaving'] = f'{2 * 22100:,}'      # two fewer fresh storage slots per request (EIP-2929 schedule)
    # prototype tests (summary of the last full `forge test` run) and invariant settings
    import re
    summary = (PROBES / 'prototype' / 'snapshots' / 'test_summary.txt').read_text(encoding='utf-8')
    passed = re.search(r'(\d+) tests passed, (\d+) failed', summary)
    assert passed and passed.group(2) == '0'
    n['nTests'] = passed.group(1)
    toml = (PROBES / 'prototype' / 'foundry.toml').read_text(encoding='utf-8')
    inv = toml[toml.index('[invariant]'):]
    n['invRuns'] = re.search(r'runs = (\d+)', inv).group(1)
    n['invDepth'] = re.search(r'depth = (\d+)', inv).group(1)

    # --- rules by placement and control (rules.csv) ---
    outside = [r for r in rules if r['stage'] not in ('verifiers', 'send') and r['controlled_by_verifiers'] == 'no']
    partly = [r for r in rules if r['stage'] not in ('verifiers', 'send') and r['controlled_by_verifiers'] == 'partly']
    n['nRulesReleaseOutside'] = str(len(outside))
    n['nRulesReleaseOutsideWords'] = WORDS[len(outside)]
    n['nRulesReleasePartlyWords'] = WORDS[len(partly)]
    n['nRulesSendOnlyWords'] = WORDS[sum(r['stage'] == 'send' for r in rules)]
    assert (len(outside), len(partly)) == (13, 3)
    # the rest sit at the release point or the token under the verifier's control (Circle CCTP)
    controlled = [r for r in rules if r['stage'] not in ('verifiers', 'send') and r['controlled_by_verifiers'] == 'yes']
    assert [r['rule'] for r in controlled] == ['Circle CCTP']
    assert (sum(r['stage'] == 'verifiers' for r in rules) + sum(r['stage'] == 'send' for r in rules)
            + len(outside) + len(partly) + len(controlled)) == len(rules)
    no_pause = sum(r['pause_by'].startswith(('none', 'sends only')) for r in rules)
    n['nRulesNoPauseWords'] = WORDS[no_pause].capitalize()
    # keeping the median CCIP lane's bucket empty for a day: its capacity plus a day of refill
    n['ccipGriefDayM'] = f"{(act['capacity_usd']['p50'] + 24 * act['rate_usd_per_h']['p50']) / 1e6:.1f}"

    # --- CCIP inbound buckets against each lane's traffic (ccip/inbound_mismatch.py) ---
    im = [r for r in read(PROBES / 'data' / 'ccip' / 'derived' / 'inbound_mismatch.json') if r['in']]
    n['ccipMisLanes'] = str(len(im))
    for D, tag in (('1 h', 'One'), ('6 h', 'Six')):
        ratios = [r['in'][D] for r in im]
        n[f'ccipInLoose{tag}'] = str(sum(x > 1 for x in ratios))
        n[f'ccipInTight{tag}'] = str(sum(x < 1 for x in ratios))
        n[f'ccipInRatioMin{tag}'] = f'{min(ratios):.2f}'
        n[f'ccipInRatioMax{tag}'] = f'{max(ratios):.2f}'
    n['ccipInEnabled'] = f"{lim['inbound_status_enabled_out']['enabled']:,}"
    n['ccipInOutSharePct'] = pct(lim['inbound_over_outbound_capacity']['share_1.0_to_1.2'], 0)
    n['ccipNoRefill'] = str(lim['class_counts']['no refill'])

    # --- coding agreement and the verifier-side ceiling under borderline readings ---
    codm = {r['id']: r for r in cod}
    timed_ids = set(resp)
    tvt = sum(amount[i] for i in timed_ids)
    cats = 'SVDO'
    first = {r['id']: (r['failure_class'] or 'O')[:1] for r in ev}
    second = {i: (codm[i]['class_recoded'] or 'O')[:1] for i in first}
    po = sum(first[i] == second[i] for i in first) / len(first)
    pe = sum((sum(first[i] == c for i in first) / len(first)) * (sum(second[i] == c for i in first) / len(first)) for c in cats)
    n['classKappa'] = f'{(po - pe) / (1 - pe):.2f}'
    n['nSecondDisagreeWords'] = WORDS[sum(first[i] != second[i] for i in first)]
    n['classSExactPct'] = pct(sum(amount[i] for i in first if first[i] == 'S') / total)
    n['classSRecodedPct'] = pct(sum(amount[i] for i in first if second[i] == 'S') / total)
    s_ids = {i for i in timed_ids if first[i] == 'S'}
    s_possible = {i for i in timed_ids if first[i] != 'S' and 'S reading' in codm[i]['borderline_note']}
    s_doubt = {i for i in s_ids if any(k in codm[i]['borderline_note'] for k in ('D reading', 'V reading'))}
    # what passes the verifiers is the class S value and the redeemed leg of an unbacked mint
    # redeemed through the bridge (replay_incidents.verifier_share)
    sys.path.insert(0, str(PROBES))
    import replay_incidents as ri

    def vis(i, cls):
        return ri.verifier_share({'id': i, 'cls': cls})
    n['ceilHighPct'] = pct(sum(amount[i] * max(vis(i, first[i]), 1.0 if i in s_possible else 0.0) for i in timed_ids) / tvt)
    n['ceilLowPct'] = pct(sum(amount[i] * (vis(i, 'D') if i in s_doubt else vis(i, first[i])) for i in timed_ids) / tvt)
    n['verifierVisiblePct'] = pct(sum(amount[i] * vis(i, first[i]) for i in first) / total, 0)
    n['nRedeemedLegs'] = WORDS[len(ri.REDEEMED_VIA_VERIFIERS)]
    n['nVerifierChecksWords'] = WORDS[len(ri.VERIFIER_CHECKS)]
    n['nSPossible'] = str(len(s_possible))
    n['nSDoubt'] = str(len(s_doubt))

    # --- failures that met a limit in force (validation.csv) ---
    val_rows = rows(HERE / 'validation.csv')
    n['nValidation'] = str(len(val_rows))
    n['nValidationWords'] = WORDS[len(val_rows)]
    vb = read(PROBES / 'results' / 'validation_bounds.json')
    tk, rn = vb['E55_taiko'], vb['E30_ronin_2024']
    n['valTaikoQuota'] = f"{tk['quota_eth_per_day']:,.0f}"
    n['valTaikoUsed'] = f"{tk['quota_eth_per_day'] - tk['left_after_t0']:,.0f}"
    n['valRoninEthLock'] = f"{rn['WETH']['lock_threshold']:,.0f}"
    n['valRoninEthDaily'] = f"{rn['WETH']['daily_limit']:,.0f}"
    n['valRoninEthUsed'] = f"{rn['WETH']['withdrawn_that_day_before']:,.0f}"
    n['valRoninUsdcLockM'] = f"{rn['USDC']['lock_threshold'] / 1e6:g}"
    n['valRoninUsdcDailyM'] = f"{rn['USDC']['daily_limit'] / 1e6:g}"
    n['valRoninUsdcUsed'] = f"{rn['USDC']['withdrawn_that_day_before']:,.0f}"
    n['valTaikoRate'] = f"{tk['refill_eth_per_hour']:.1f}"
    n['valTaikoRead'] = f"{tk['check_available_at_read']['onchain']:.2f}"
    n['valTaikoBound'] = f"{tk['bound_at_last_release']:,.0f}"
    n['valTaikoOut'] = f"{tk['released_eth']:,.0f}"
    n['valTaikoPct'] = pct(tk['share_of_bound'], 0)
    n['valTaikoMaxPct'] = pct(tk['max_cumulative_over_bound'], 0)
    n['valRoninEthBound'] = f"{rn['WETH']['bound']:,.0f}"
    n['valRoninEthOut'] = f"{rn['WETH']['taken']:,.0f}"
    n['valRoninEthPct'] = pct(rn['WETH']['share_of_bound'], 0)
    n['valRoninUsdcBoundM'] = f"{rn['USDC']['bound'] / 1e6:.2f}"
    n['valRoninUsdcOutM'] = f"{rn['USDC']['taken'] / 1e6:.2f}"
    n['valRoninUsdcPct'] = pct(rn['USDC']['share_of_bound'], 0)
    vrow = {r['id']: r for r in val_rows}
    for key in ('valTaikoBound', 'valTaikoOut', 'valTaikoPct', 'valTaikoRate'):
        assert n[key] in vrow['E55']['prediction'] + vrow['E55']['outcome'], (key, n[key])
    for key in ('valRoninEthBound', 'valRoninEthOut', 'valRoninEthPct', 'valRoninUsdcBoundM',
                'valRoninUsdcOutM', 'valRoninUsdcPct'):
        assert n[key] in vrow['E30']['prediction'] + vrow['E30']['outcome'], (key, n[key])

    # --- how the first response was timed (response_protocol.py) ---
    rp = read(PROBES / 'results' / 'response_protocol.json')
    n['respBothN'], n['respPauseFirstN'] = str(rp['n_both_ack_and_pause']), str(rp['n_pause_before_ack'])
    n['respAckAfterPauseH'] = f"{rp['median_ack_after_pause_h']:.1f}"
    n['respPauseOnchainN'] = str(rp['pause_basis_counts']['onchain'])
    n['respWeekendMedH'] = f"{rp['weekend']['median_h']:.1f}"
    n['respWeekdayMedH'] = f"{rp['weekday']['median_h']:.1f}"
    n['respWeekendP'] = f"{rp['weekend_vs_weekday_mannwhitney_p']:.2f}"
    n['respHourP'] = f"{rp['hour_blocks_kruskal_p']:.2f}"
    assert rp['n_timed'] == int(n['nTimedEvents']) and rp['response_basis']['acknowledgment'] == int(n['nRespAck'])

    # --- response times by pause holder and by period ---
    by_holder = defaultdict(list)
    for i, d in resp.items():
        by_holder[codm[i]['pause_holder']].append(d / 3600)
    n['respIndepMedH'] = f"{statistics.median(by_holder['independent_of_failure']):.1f}"
    n['respIndepN'] = str(len(by_holder['independent_of_failure']))
    early = [d / 3600 for i, d in resp.items() if codm[i]['date'][:4] <= '2023']
    late = [d / 3600 for i, d in resp.items() if codm[i]['date'][:4] >= '2024']
    n['respEarlyMedH'], n['respEarlyN'] = f'{statistics.median(early):.1f}', str(len(early))
    n['respLateMedH'], n['respLateN'] = f'{statistics.median(late):.1f}', str(len(late))

    # --- per-bridge counterfactual on each failed bridge's own traffic (replay_perbridge.py) ---
    # Shares are kept shares (1 - loss / value).  The floor is fitted in sample to all 150 days; the
    # bucket and the review are fitted out of sample and their cost is measured on held-out months
    # (o1: the 30 days before the failure; o2: the 30 days before that).
    pb = read(PROBES / 'results' / 'replay_perbridge.json')
    A = pb['aggregate']
    agg_ids = A['ids']
    F = pb['failures']
    n['pbN'] = str(pb['n_failures'])
    n['pbNAllWords'] = WORDS[pb['n_failures']]
    n['pbNWords'] = WORDS[len(agg_ids)]
    n['pbValueSharePct'] = pct(pb['value_share_of_bridge_set'], 0)
    n['pbValueB'] = f"{sum(F[i]['A'] for i in agg_ids) / 1e9:.1f}"
    assert {'E30', 'E01'} <= set(pb['params']['excluded_from_aggregates']) <= {'E30', 'E01', 'E10', 'E59'}, \
        'the text (pbApartText) names the failures shown apart'
    n['pbFirstHistoryDays'] = f"{F['E01']['history_days']:.0f}"
    # the selection of the per-bridge histories, stated as a rule: every failure with a recorded
    # response of at least 20 million, except those named with the reason, plus smaller ones
    big_timed = sorted(i for i in resp if amount[i] >= 20e6)
    WHY_NOT = {'E23': "Mixin, whose custody sat in hot wallets on many chains that we could not enumerate"}
    PENDING = {'E10': 'Qubit', 'E59': 'AFX'}   # histories being rebuilt (data/legit/build_e10.py, build_e59.py)
    miss_big = [i for i in big_timed if i not in F]
    pend = [i for i in miss_big if i in PENDING]
    if pend:
        print('WARNING: per-bridge histories still missing for', pend, '- the selection text names them as pending')
    assert all(i in WHY_NOT or i in PENDING for i in miss_big), ('a failure of at least 20M lacks a history and a reason', miss_big)
    small = sorted(i for i in F if amount[i] < 20e6)
    n['pbSelectionText'] = ("every failure with a recorded response of at least \\$20 million except "
                            + "; ".join(WHY_NOT[i] for i in miss_big if i in WHY_NOT)
                            + (" and " + " and ".join(PENDING[i] for i in pend) + " (PENDING)" if pend else "")
                            + f", and {WORDS[len(small)]} smaller ones whose release point we could read.")
    excl_ids = list(pb['params']['excluded_from_aggregates'])
    APART = {'E30': ('limit', "the 2024 Ronin failure met a deployed limit (Section~\\ref{sec:validation})"),
             'E01': ('short', "Anyswap's routers"), 'E10': ('short', "QBridge"), 'E59': ('short', "the AFX bridge")}
    assert all(i in APART for i in excl_ids), excl_ids
    lim = [APART[i][1] for i in excl_ids if APART[i][0] == 'limit']
    shorts = [i for i in excl_ids if APART[i][0] == 'short']
    parts = list(lim)
    if shorts:
        names = [APART[i][1] for i in shorts]
        days = [f"{F[i]['history_days']:.0f}" for i in shorts]
        who = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
        when = days[0] if len(days) == 1 else ", ".join(days[:-1]) + " and " + days[-1]
        parts.append(f"{who} went into service {when} days before "
                     f"{'the failure' if len(names) == 1 else 'their failures'}, too late for the fit below")
    n['pbApartText'] = (f"{WORDS[len(excl_ids)]} more are shown apart: " + ", and ".join(parts) + ".")
    fl, bk, rv1, rvh = A['floor'], A['bucket 6h m=1.5'], A['review 1h m=1.5 q=0.999'], A['review 1h m=1.5 q=0.99']

    def kept(a, key='loss', digits=1):
        return pct(a[key]['value'], digits)
    n['pbFloorPct'], n['pbFloorEventPct'] = kept(fl), pct(fl['loss']['event'], 0)
    n['pbFloorLoPct'], n['pbFloorHiPct'] = pct(fl['loss']['boot_lo'], 0), pct(fl['loss']['boot_hi'], 0)
    n['pbFloorNetPct'] = pct(fl['loss']['net'], 0)
    big_id = max(agg_ids, key=lambda i: F[i]['limits']['floor']['loss'])
    big = F[big_id]
    n['pbLargestLossShare'] = pct(big['limits']['floor']['loss'] / sum(F[i]['limits']['floor']['loss'] for i in agg_ids), 0)
    n['pbLargestLossDays'] = f"{big['D_h'] / 24:.0f}"
    n['pbLargestLegitDayM'] = f"{big['legit_value_per_day'] / 1e6:.0f}"
    others = [i for i in agg_ids if i != big_id]
    n['pbOthersN'] = WORDS[len(others)]
    n['pbOthersFloorPct'] = pct(sum(F[i]['A'] - F[i]['limits']['floor']['loss'] for i in others) / sum(F[i]['A'] for i in others))
    n['pbBucketPct'], n['pbBucketEventPct'] = kept(bk), pct(bk['loss']['event'], 0)
    n['pbBucketGovPct'], n['pbBucketFivePct'] = kept(bk, 'loss_governed'), kept(bk, 'loss_x5')
    n['pbBucketOutflowPct'] = kept(bk, 'loss_outflow_never')
    n['pbBucketDelayedPct'], n['pbBucketDelayedTwoPct'] = pct(bk['test_o1']['delayed_share'], 0), pct(bk['test_o2']['delayed_share'], 0)
    n['pbBucketDelayedMaxPct'] = pct(max(bk['test_o1']['delayed_share_max'], bk['test_o2']['delayed_share_max']), 0)
    n['pbBucketWaitMedH'] = f"{bk['test_o1']['wait_p50_h']:.0f}"
    n['pbBucketHoursPerDollar'] = f"{bk['test_o1']['hours_per_dollar']:.1f}"
    n['pbBucketHoursPerDollarTwo'] = f"{bk['test_o2']['hours_per_dollar']:.0f}"
    n['pbReviewPct'], n['pbReviewEventPct'] = kept(rv1), pct(rv1['loss']['event'], 0)
    n['pbReviewLoPct'], n['pbReviewHiPct'] = pct(rv1['loss']['boot_lo'], 0), pct(rv1['loss']['boot_hi'], 0)
    n['pbReviewGovPct'], n['pbReviewOutflowPct'] = kept(rv1, 'loss_governed'), kept(rv1, 'loss_outflow_never')
    n['pbReviewFivePct'] = kept(rv1, 'loss_x5')
    t1, t2 = rv1['test_o1'], rv1['test_o2']
    n['pbReviewDelayedPct'], n['pbReviewDelayedTwoPct'] = pct(t1['delayed_share']), pct(t2['delayed_share'])
    n['pbReviewSharePct'], n['pbReviewShareTwoPct'] = pct(t1['review_share'], 0), pct(t2['review_share'], 0)
    n['pbReviewTotalPct'], n['pbReviewTotalTwoPct'] = pct(t1['total_delayed_share'], 0), pct(t2['total_delayed_share'], 0)
    n['pbReviewPerMonth'] = f"{t1['reviews_per_bridge_month']:.0f}"
    n['pbReviewPerMonthTwo'] = f"{t2['reviews_per_bridge_month']:.0f}"
    for L, name in ((1, 'One'), (6, 'Six'), (24, 'Day')):
        n[f'pbReviewWait{name}H'] = f"{t1[f'hours_per_dollar_review{L}h']:.1f}"
        n[f'pbReviewWait{name}HTwo'] = f"{t2[f'hours_per_dollar_review{L}h']:.1f}"
    n['pbReviewWaitOneMin'] = f"{60 * t1['hours_per_dollar_review1h']:.0f}"
    n['pbTestTransfers'] = f"{bk['test_o1']['test_n']:,}"
    n['pbTestTransfersTwo'] = f"{bk['test_o2']['test_n']:,}"
    for a, name in (('1h', 'Hour'), ('10min', 'Ten')):
        n[f'pbReviewAlarm{name}Pct'] = kept(rv1, f'loss_alarm_{a}')
        n[f'pbReviewAlarm{name}EventPct'] = pct(rv1[f'loss_alarm_{a}']['event'], 0)
        n[f'pbReviewAlarm{name}LoPct'] = pct(rv1[f'loss_alarm_{a}']['boot_lo'], 0)
        n[f'pbReviewAlarm{name}HiPct'] = pct(rv1[f'loss_alarm_{a}']['boot_hi'], 0)
        n[f'pbBucketAlarm{name}Pct'] = kept(bk, f'loss_alarm_{a}')
        n[f'pbFloorAlarm{name}Pct'] = kept(fl, f'loss_alarm_{a}')
        ao = A[f'alarm_only_{a}']
        n[f'pbAlarmOnly{name}Pct'] = pct(ao['value_lo'], 0)
        assert pct(ao['value_lo'], 0) == pct(ao['value_hi'], 0), ao
    n['pbHundredPct'], n['pbHundredEventPct'] = kept(rvh), pct(rvh['loss']['event'], 0)
    n['pbHundredSharePct'] = pct(rvh['test_o1']['review_share'], 0)
    n['pbHundredPerMonth'] = f"{rvh['test_o1']['reviews_per_bridge_month']:.0f}"
    n['pbHundredAlarmHourPct'] = kept(rvh, 'loss_alarm_1h')
    var = pb['variant_outsized']
    n['pbVarFloorPct'] = pct(var['aggregate']['floor']['loss']['value'])
    n['pbVarReviewPct'] = pct(var['aggregate']['review 1h m=1.5 q=0.999']['loss']['value'])
    n['pbVarDroppedN'] = WORDS[sum(var['dropped'].values())]
    e05 = F['E05']['counts']
    n['pbPolyUnpricedPct'] = pct(e05['n_unpriced'] / e05['n_rows'], 0)
    e21 = F['E21']['counts']
    n['pbPolyTwoUnpricedPct'] = pct(e21['n_unpriced'] / e21['n_rows'], 0)
    ws = pb['window_sensitivity']
    lo = pct(min(ws[w]['review 1h m=1.5 q=0.999']['value'] for w in ws), 0)
    hi = pct(max(ws[w]['review 1h m=1.5 q=0.999']['value'] for w in ws), 0)
    n['pbWinReviewPct'] = lo if lo == hi else f'{lo} to {hi}'
    for k, name in (('bucket 1h m=1.5', 'One'), ('bucket 24h m=1.5', 'Day'), ('bucket 50h m=1.5', 'Fifty')):
        n[f'pbBucket{name}Pct'] = kept(A[k])
        n[f'pbBucket{name}DelayedPct'] = pct(A[k]['test_o1']['delayed_share'], 0)

    # --- the check that a deposit backs each release, used as a gate (a hold on every withdrawal
    # while it runs, the bucket behind), as the review of the largest transfers, or as an alarm; what each
    # design keeps when the check works and when it fails (replay_perbridge.py, check_sees), its cost in
    # counts and tails, and the subsets and weightings ---
    prm = pb['params']
    n['pbGateMin'] = f"{prm['gate_h_s'] / 60:.0f}"
    n['pbFloorPctR'], n['pbBucketPctR'], n['pbReviewPctR'] = kept(fl, digits=0), kept(bk, digits=0), kept(rv1, digits=0)
    n['pbGateWorksPctR'] = kept(bk, 'loss_gate_works', 0)
    n['pbReviewSparePct'] = pct(1 - t1['review_n'] / t1['test_n'], 1)
    n['pbGateHoursPerDollar'] = f"{prm['gate_h_s'] / 3600:.2f}"
    n['pbGateWorksPct'] = kept(bk, 'loss_gate_works')
    n['pbGateFailsPct'] = kept(bk, 'loss_gate_fails')
    n['pbGateWorksMatchPct'] = kept(bk, 'loss_gate_works_matching')
    gate_alone_fails = [F[i]['A'] if F[i]['D_h'] * 3600 > prm['gate_h_s'] else 0.0 for i in agg_ids]
    n['pbGateAloneFailsPct'] = pct(1 - sum(gate_alone_fails) / sum(F[i]['A'] for i in agg_ids), 0)
    gate_alone_works = [0.0 if F[i]['check_sees'] else x for i, x in zip(agg_ids, gate_alone_fails)]
    n['pbGateAloneWorksPct'] = pct(1 - sum(gate_alone_works) / sum(F[i]['A'] for i in agg_ids), 0)
    # what the check flags and someone can stop, over all failures (replay_perbridge.check_sees): classes
    # S, V, D, not class V from custody held by keys; an event-matching check also misses class S
    kh = set(prm['keys_held'])

    def sees(r, matching=False, as_built=False):
        c = (r['failure_class'] or 'O')[:1]
        return c in 'SVD' and not (as_built and c == 'V' and r['id'] in kh) and not (matching and c == 'S')
    n['checkSeesPct'] = pct(sum(amount[r['id']] for r in ev if sees(r)) / total, 1)
    n['checkMatchSeesPct'] = pct(sum(amount[r['id']] for r in ev if sees(r, True)) / total, 0)
    n['checkKeysHeldVPct'] = pct(sum(amount[r['id']] for r in ev if r['failure_class'] == 'V' and r['id'] in kh) / total, 0)
    # the gate with custody as built (class V from custody held by keys is stopped by nothing)
    n['pbGateBuiltPct'] = kept(bk, 'loss_gate_works_built', 0)
    assert pct(bk['loss_gate_works']['value'], 1) == '100.0', 'the text says every failure the check flags loses nothing'
    n['pbReviewCheckFailsPct'] = kept(rv1, 'loss_check_fails', 0)
    n['pbReviewAlarmCheckFailsPct'] = n['pbReviewCheckFailsPct']
    lo3 = A['bucket 6h m=3.0']
    n['pbLoosePct'], n['pbLooseGateWorksPct'] = kept(lo3), kept(lo3, 'loss_gate_works')
    n['pbLooseDelayedPct'], n['pbLooseDelayedTwoPct'] = pct(lo3['test_o1']['delayed_share'], 0), pct(lo3['test_o2']['delayed_share'], 0)
    n['pbLooseHoursPerDollar'], n['pbLooseHoursPerDollarTwo'] = f"{lo3['test_o1']['hours_per_dollar']:.1f}", f"{lo3['test_o2']['hours_per_dollar']:.1f}"
    n['pbBucketCountPct'], n['pbBucketCountTwoPct'] = pct(bk['test_o1']['count_delayed_share']), pct(bk['test_o2']['count_delayed_share'])
    n['pbReviewCountPct'], n['pbReviewCountTwoPct'] = pct(t1['count_delayed_share']), pct(t2['count_delayed_share'])
    n['pbLooseCountPct'], n['pbLooseCountTwoPct'] = pct(lo3['test_o1']['count_delayed_share']), pct(lo3['test_o2']['count_delayed_share'])
    n['pbBucketWaitNinetyNineTwoH'] = f"{bk['test_o2']['wait_all_p99_h']:.0f}"
    n['pbReviewPerMonthMed'] = f"{t1['reviews_per_month_median']:.0f}"
    n['pbReviewPerMonthMax'] = f"{max(t1['reviews_per_month_max'], t2['reviews_per_month_max']):.0f}"
    n['pbBucketKeysHeldPct'], n['pbReviewKeysHeldPct'] = kept(bk, 'loss_keysheld'), kept(rv1, 'loss_keysheld')
    pfs = fl['loss_pause_first_subset']
    n['pbPauseFirstN'] = WORDS[pfs['n']]
    n['pbPauseFirstFloorPct'] = pct(pfs['value'], 0)
    n['pbPauseFirstBucketPct'] = pct(bk['loss_pause_first_subset']['value'], 0)
    n['pbPauseFirstReviewPct'] = pct(rv1['loss_pause_first_subset']['value'], 0)
    n['pbBucketNetPct'], n['pbReviewNetPct'] = pct(bk['loss']['net'], 0), pct(rv1['loss']['net'], 0)
    n['pbGateWorksNetPct'] = pct(bk['loss_gate_works']['net'], 0)
    n['pbFloorLooLoPct'], n['pbFloorLooHiPct'] = pct(fl['loss']['loo_lo'], 0), pct(fl['loss']['loo_hi'], 0)
    n['pbReviewLooLoPct'], n['pbReviewLooHiPct'] = pct(rv1['loss']['loo_lo'], 0), pct(rv1['loss']['loo_hi'], 0)
    n['pbBucketLoPct'], n['pbBucketHiPct'] = pct(bk['loss']['boot_lo'], 0), pct(bk['loss']['boot_hi'], 0)
    n['pbGateWorksLoPct'] = pct(bk['loss_gate_works']['boot_lo'], 0)
    lf = pb['largest_floor_loss']
    assert lf['id'] == big_id
    n['pbRoninEnvM'] = musd(lf['E_D'], 0)
    n['pbRoninOutsizedM'] = musd(lf['outsized_usd'], 0)
    n['pbRoninEnvTrimM'] = musd(lf['E_D_without_outsized'], 0)
    n['pbRoninFloorTrimPct'] = pct(1 - min(lf['A'], lf['E_D_without_outsized']) / lf['A'], 0)
    n['pbRoninTakenM'] = musd(lf['A'], 0)
    # least delay of any limit with the bucket's six-hour release (delay_budget.py)
    db = read(PROBES / 'results' / 'delay_budget.json')['totals']
    n['dbLowerPct'], n['dbLowerTwoPct'] = pct(db['o1']['lower_share'], 0), pct(db['o2']['lower_share'], 0)
    assert pct(db['o1']['bucket_share'], 0) == n['pbBucketDelayedPct'] and pct(db['o2']['bucket_share'], 0) == n['pbBucketDelayedTwoPct']
    # coverage against three published incident lists (coverage/counts.py -> results/coverage.json)
    cov = read(PROBES / 'results' / 'coverage.json')
    assert cov['other_reasons'].get('unclear', 0) == 1 and set(cov['other_reasons']) <= {'below 1M', 'not a bridge release', 'unclear'}
    n['coverEntries'], n['coverMatched'], n['coverLeftOut'] = str(cov['entries']), str(cov['matched_entries']), str(cov['left_out_entries'])
    n['coverSmall'], n['coverNotBridge'] = str(cov['other_reasons']['below 1M']), WORDS[cov['other_reasons']['not a bridge release']]
    n['coverAfter'] = str(cov['our_failures_after_lists'])
    # false pauses: Liu et al. saw 103 alerts in eight months on Wormhole before any re-check; if each
    # paused the bridge for an hour, the legitimate value arriving during pauses waits half an hour on
    # average (a month taken as 730 hours)
    # Liu et al. date the run October 2024 to June 2025 and also call it 10 months; 8 months gives the higher
    # alert rate, so the wait is not understated
    fp_per_month, fp_hours = 103 / 8, 1.0
    n['fpPausedTimePct'] = pct(fp_per_month * fp_hours / 730.0)
    n['fpWaitPerDollar'] = f"{fp_per_month * fp_hours / 730.0 * fp_hours / 2:.3f}"

    # --- the prototype's overhead in dollars (prototype/snapshots/gas_price.json) ---
    gp = read(PROBES / 'prototype' / 'snapshots' / 'gas_price.json')
    gwei = gp['base_fee_gwei_median'] + gp['priority_fee_gwei_median']
    gwei90 = gp['base_fee_gwei_p90'] + gp['priority_fee_gwei_median']
    extra = lim2 - gas['plain_release']
    n['gasPriceGwei'] = f'{gwei:.2f}'
    n['gasPriceNinetyGwei'] = f'{gwei90:.2f}'
    n['ethUsd'] = f"{gp['eth_usd']:,.0f}"
    n['gasExtraUsd'] = f"{extra * gwei * 1e-9 * gp['eth_usd']:.2f}"
    n['gasExtraNinetyUsd'] = f"{extra * gwei90 * 1e-9 * gp['eth_usd']:.2f}"
    # at a base fee of 30 gwei, common in 2021 and 2022, and the same ether price
    n['gasExtraThirtyUsd'] = f"{extra * 30 * 1e-9 * gp['eth_usd']:.0f}"
    # the second contract (TunedLimiter): buckets in series, per-asset bucket, timelocked loosening
    tg = {k: int(v) for k, v in read(PROBES / 'prototype' / 'snapshots' / 'TunedGasBench.json').items()}
    n['gasTunedOne'] = f"{tg['tuned_execute_k1']:,}"
    n['gasTunedFour'] = f"{tg['tuned_execute_k4']:,}"
    n['gasTunedPerBucket'] = f"{(tg['tuned_execute_k4'] - tg['tuned_execute_k1']) // 3:,}"
    tuned_total = tg['tuned_queue'] + tg['tuned_execute_k4_asset']
    n['gasTunedTotal'] = f'{tuned_total:,}'
    n['gasTunedExtra'] = f"{tuned_total - gas['plain_release']:,}"
    n['gasTunedExtraUsd'] = f"{(tuned_total - gas['plain_release']) * gwei * 1e-9 * gp['eth_usd']:.2f}"
    suites = (PROBES / 'prototype' / 'snapshots' / 'test_suites.txt').read_text(encoding='utf-8')
    n['nTestsTuned'] = re.search(r'Ran (\d+) tests for test/TunedLimiter\.t\.sol', suites).group(1)
    fuzz_runs = int(re.search(r'runs = (\d+)', toml[toml.index('[fuzz]'):]).group(1))
    n['nFuzzRuns'] = f'{fuzz_runs:,}'

    # --- blind recoding by an independent coder (coding/agreement.py -> results/blind_agreement.json) ---
    ba_path = PROBES / 'results' / 'blind_agreement.json'
    if ba_path.exists():
        ba = read(ba_path)
        n['blindN'] = str(ba['n'])
        n['blindAgree'] = str(ba['agree'])
        n['blindKappa'] = f"{ba['kappa']:.2f}"
        n['blindDisValuePct'] = pct(ba['disagreement_value_share'], 1)
        n['blindVerifierPct'] = pct(ba['verifier_share_blind_timed'], 0)
        n['blindPauseAgree'] = str(ba['pause_holder_agree'])
        n['blindPauseN'] = str(ba['pause_holder_n'])
        if 'keys_held_value_share' in ba:
            n['keysHeldPct'] = pct(ba['keys_held_value_share'], 0)
            n['keysHeldN'] = str(ba['keys_held_n'])

    # --- forged deposits (prototype/testbed/run_forged.py, summarize_forged.py -> results/testbed_forged.json):
    # a monitor matching requests to recorded deposits against one that also requires the value to have moved ---
    tf_path = PROBES / 'results' / 'testbed_forged.json'
    if tf_path.exists():
        tf = read(tf_path)
        rmon, vmon = tf['monitors']['record_match'], tf['monitors']['value_check']
        assert rmon['alarms'] == 0 and vmon['episodes_with_alarm'] == vmon['episodes'] == rmon['episodes']
        n['tbForgedN'] = str(vmon['episodes'])
        n['tbForgedDetectMaxS'] = f"{max(v['detect_s']['max'] for v in vmon['limiters'].values()):.0f}"
        n['tbForgedPauseMaxS'] = f"{max(v['pause_s']['max'] for v in vmon['limiters'].values()):.0f}"
        assert vmon['limiters']['L10']['released_before_pause_usd']['max'] == 0
        n['tbForgedRecordReleasedM'] = musd(rmon['limiters']['L0']['released_total_usd']['median'])
        n['tbForgedPoints'] = WORDS[tf['n_points']]

    # --- end-to-end testbed (prototype/testbed/summarize.py -> results/testbed.json) ---
    tb = read(PROBES / 'results' / 'testbed.json')
    A_runs = {k: v for k, v in tb['phase_a'].items() if v['k'] == 64 and v['episodes']}
    one = {}
    for v in A_runs.values():          # one run per bridge (the legitimate stream is the same at both block times)
        one.setdefault(v['fid'], v)
    assert set(one) == {'E25', 'E15'}
    n['tbReleasesOrbit'] = f"{one['E25']['n_releases']:,}"
    n['tbReleasesNomad'] = f"{one['E15']['n_releases']:,}"
    n['tbLegitRequests'] = f"{sum(v['monitors']['km64_g0']['n_matched'] for v in one.values()):,}"
    n['tbNomadDelayedPct'] = pct(one['E15']['legit']['L0']['share_value_delayed'], 0)

    def burst_m(fid):
        xs = [g['L0']['released_before_pause_usd']['median'] for v in A_runs.values() if v['fid'] == fid
              for k, g in v['episodes'].items() if k.startswith('burst')]
        assert max(xs) - min(xs) < 1.0      # the bucket's whole capacity in every burst
        return f'{xs[0] / 1e6:.1f}'
    n['tbBurstOrbitM'], n['tbBurstNomadM'] = burst_m('E25'), burst_m('E15')
    n['tbFalseAlarms'] = str(sum(m['n_alarms'] for v in A_runs.values() for m in v['monitors'].values()))
    eps = [g for v in A_runs.values() for g in v['episodes'].values()]
    n['tbEpisodes'] = f"{sum(g['n'] for g in eps):,}"
    n['tbRuns'] = WORDS[len(A_runs)]
    for v in A_runs.values():
        for key, g in v['episodes'].items():
            P = float(key.split('P=')[1])
            assert g['L0']['detect_s']['max'] <= P + 1e-6, (v['run'], key)   # detected within one poll
    n['tbPauseMaxS'] = f"{max(g['L0']['pause_s']['max'] for g in eps):.0f}"
    n['tbHoldReleased'] = f"{max(g['L10']['released_before_pause_usd']['max'] for g in eps):,.0f}"
    # a monitor that waits for finality flags what a faster relayer took, until its grace covers the gap
    gaps = {}
    for v in tb['phase_a'].values():
        if v['k'] < 64 and not v.get('reorg_events'):
            ok = [m for m in v['monitors'].values() if m['cfg']['k_m'] == 64 and m['n_alarms'] == 0]
            bad = [m for m in v['monitors'].values() if m['cfg']['k_m'] == 64 and m['n_alarms'] > 0]
            assert ok and all(m['n_alarms'] == v['monitors']['km64_g0']['n_alarms'] for m in bad)
            gaps[v['k']] = (64 - v['k']) * v['Bs']
    n['tbFinalityGapMinM'] = f"{min(gaps.values()) / 60:.0f}"
    n['tbFinalityGapMaxM'] = f"{max(gaps.values()) / 60:.0f}"
    # reorganizations after a relayer acted on two confirmations, deposits not sent again (variant b)
    rb = next(v for v in tb['phase_a'].values() if v.get('reorg_events', {}).get('variant') == 'b')
    ra = next(v for v in tb['phase_a'].values() if v.get('reorg_events', {}).get('variant') == 'a')
    mons_b = rb['monitors']
    n['tbReorgTargets'] = str(rb['reorg_events']['n_relied_upon'])
    n['tbReorgOnceMax'] = str(max(m['reorg_targets_alarmed'] for k, m in mons_b.items() if 'kf' not in m['cfg'] and m['cfg']['k_m'] < 64))
    rc = next(m for m in mons_b.values() if m['cfg'].get('kf') == 64)
    assert rc['reorg_targets_alarmed'] == rc['reorg_targets']
    n['tbReorgRecheckMaxS'] = f"{rc['alarm_delay_after_reorg_s']['max']:.0f}"
    rc_a = next(m for m in ra['monitors'].values() if m['cfg'].get('kf') == 64)
    assert rc_a['n_alarms'] == 0      # no false alarm when the dropped deposits came back
    B_runs = [v for v in tb['phase_b'].values() if v['n_ok']]
    rt = [g['L0']['pause_s'] for v in B_runs for g in v['groups'].values()]
    n['tbRtPauseMinS'] = f"{min(x['min'] for x in rt):.0f}"
    n['tbRtPauseMaxS'] = f"{max(x['max'] for x in rt):.0f}"
    n['tbRtEpisodes'] = str(sum(g['n'] for v in B_runs for g in v['groups'].values()))

    # --- the check in shadow beside two live bridges between Ethereum and BSC ---
    # (shadow/simulate.py over the 42-day release tables of shadow/wormhole_collect.py and
    # shadow/ccip_collect.py; shadow/fee_token_check.py; shadow/live_monitor.py summary for the live run)
    sh = read(PROBES / 'results' / 'shadow_run.json')
    tot, brs = sh['total'], sh['bridges']
    assert set(brs) == {'ccip bsc->ethereum', 'ccip ethereum->bsc', 'wormhole bsc->ethereum', 'wormhole ethereum->bsc'}
    n['shRel'], n['shUsdM'] = f"{tot['releases']:,}", f"{tot['usd'] / 1e6:.1f}"
    # with any included deposit, every matched release is confirmed at the first poll after it
    anyd = [b['configs']['any included deposit, grace 0 s'] for b in brs.values()]
    assert all(c['false_alarms_raw'] == 0 and c['delay_to_confirmation_s']['1.0'] <= sh['poll_s'] for c in anyd)
    # the releases the check could not match: tokens that take a fee on every transfer, paid in three parts that
    # sum to the signed amount, with the recipient among them (shadow/fee_token_check.py)
    fee = read(PROBES / 'results' / 'shadow_fee_tokens.json')
    assert fee['releases'] == tot['unmatched'] and fee['all_match_by_outflow_sum']
    assert all(r['outflows'] == 3 for r in fee['rows'])
    n['shUnmatched'], n['shFeeTokens'] = WORDS.get(tot['unmatched'], str(tot['unmatched'])), WORDS[len(fee['tokens'])]
    # deposits not yet final when their release was included: CCIP transfers from Ethereum released a few
    # minutes after the deposit (Ethereum finality by slot, simulate.final_time)
    nf = {k: b for k, b in brs.items() if b['not_final_when_released']}
    assert set(nf) == {'ccip ethereum->bsc'}
    b = nf['ccip ethereum->bsc']
    n['shNotFinal'] = WORDS[tot['not_final_when_released']]
    assert b['deposit_age_s']['0.0'] < 600 < b['deposit_age_s']['0.01']     # the early ones are the youngest deposits
    n['shNotFinalAgeMin'] = WORDS[round(b['deposit_age_s']['0.0'] / 60)]
    n['shNotFinalWaitMin'] = f"{b['finality_after_release_s_max'] / 60:.0f}"
    assert round(b['configs']['final deposit, grace 0 s']['false_alarms_confirmed'], 6) == tot['not_final_when_released']
    # the live run (from 2026-10-17); text macros follow what the run found
    lv = read(PROBES / 'results' / 'shadow_live.json')
    a, tw = lv['streams']['all'], lv['twins']['all']
    t0 = utc(lv['window_utc'][0])
    n['shLiveStart'] = f"{t0.day} {t0.strftime('%B')}"
    n['shLiveDays'] = f"{lv['days']:.1f}"
    assert set(a['by_mode']) <= {'live', 'backfill'} and a['decode_failed'] == 0
    n['shLiveAll'] = f"{a['releases'] + lv['open_releases']:,}"
    n['shLiveUpPct'] = f"{100 * lv['monitor']['up_share']:.0f}"
    # delays once the monitor has caught up: after an outage a live release waits behind the blocks read in backfill
    cu = lv['live_caught_up']
    assert cu['as_they_happened'] + cu['read_late'] == a['live']['releases'] + lv['open_releases']
    assert cu['interrupted_by_stop'] == 0   # the text says the others arrived during a catch-up
    lat = cu['verdict_after_release_s']
    n['shLiveN'] = f"{cu['as_they_happened']:,}"
    n['shLiveCaughtN'] = f"{cu['releases']:,}"
    n['shLiveWaitedN'] = f"{cu['behind_catch_up']:,}"
    n['shLiveWaitedOver'] = f"{WORDS.get(cu['behind_catch_up_over_600s'], cu['behind_catch_up_over_600s'])}"
    n['shLiveMedS'] = f"{lat['0.5']:,.0f}"
    n['shLiveNinetyNineS'] = f"{lat['0.99']:,.0f}"
    n['shLiveMaxS'] = f"{lat['1.0']:,.0f}"
    al = lv['alarms']
    a_read, a_parts, a_other = al['read_errors'], al['paid_in_parts'], al['other']
    raw = a_read + a_parts + a_other
    if raw == 0:
        n['shLiveAlarmText'] = 'raised no alarm'
    elif a_other == 0 and a_parts == 0:
        n['shLiveAlarmText'] = (f"raised {WORDS.get(raw, raw)} alarm{'s' if raw > 1 else ''}, all read errors from a "
                                f"public node, and a re-check cleared them")
    elif a_other == 0 and a_read > 0:
        n['shLiveAlarmText'] = (f"raised {WORDS.get(raw, raw)} alarms: a re-check cleared the {WORDS.get(a_read, a_read)} read "
                                f"errors from a public node, and the other{'s were' if a_parts > 1 else ' was'} "
                                f"{WORDS.get(a_parts, a_parts) if a_parts > 1 else 'one more'} release{'s' if a_parts > 1 else ''} paid in parts")
    else:
        n['shLiveAlarmText'] = f"raised {WORDS.get(raw, raw)} alarms, of which {WORDS.get(a_other, a_other)} stood after the re-checks"
    n['shTwinN'] = f"{tw['copies_tested']:,}"
    n['shTwinText'] = (f"flagged all {tw['copies_tested']:,} test copies we made of live releases"
                       if tw['copies_flagged'] == tw['copies_tested']
                       else f"flagged {tw['copies_flagged']:,} of the {tw['copies_tested']:,} test copies we made of live releases")

    # --- the running example of the introduction ---
    W, b, r_h = 100.0, 2.0, 2.0          # USD millions held; burst and refill per hour
    D = med_resp / 3600
    n['exHeldM'], n['exRateM'] = f'{W:.0f}', f'{r_h:.0f}'
    n['exLossM'] = f'{b + r_h * D:.1f}'

    tex = ['% Generated by make_numbers.py; do not edit by hand.']
    for key, value in n.items():
        tex.append(f'\\newcommand{{\\{key}}}{{{value}}}')
    (HERE / 'numbers.tex').write_text('\n'.join(tex) + '\n', encoding='utf-8')
    (HERE / 'numbers.json').write_text(json.dumps(n, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    for key, value in n.items():
        print(f'{key:28s} {value}')


if __name__ == '__main__':
    main()
