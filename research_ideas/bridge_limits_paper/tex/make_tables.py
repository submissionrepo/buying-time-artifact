"""Write the paper's tables (tab_*.tex) from the research outputs.

tab_rules.tex   deployed limits: stage, shape, accounting, automatic release, control
                (rules.csv, from results/limiter_code_facts.md section 3)
tab_timing.tex  timing of the failures (timing.json, written by make_numbers.py from
                results/incidents.csv)
tab_ccip.tex    CCIP rolling recalibration against the deployed buckets (rolling.json,
                written by make_numbers.py from data/ccip/derived/rolling_policy.json)
Run make_numbers.py first.
"""
import csv
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORDS = {1: 'one', 2: 'two', 3: 'three', 4: 'four', 5: 'five', 6: 'six', 7: 'seven', 8: 'eight', 9: 'nine',
         10: 'ten', 11: 'eleven', 12: 'twelve', 13: 'thirteen', 14: 'fourteen', 15: 'fifteen', 16: 'sixteen',
         17: 'seventeen', 18: 'eighteen', 19: 'nineteen', 20: 'twenty'}


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def tex_escape(s):
    return s.replace('%', '\\%').replace('&', '\\&').replace('_', '\\_')


def rules_table():
    with open(HERE / 'rules.csv', encoding='utf-8') as f:
        rules = list(csv.DictReader(f))
    lines = [
        '\\begin{table*}[t]',
        '\\centering',
        '\\caption{Limits, read in source code at fixed commits. Stage: verifiers, in the verifiers\' software; send, on the sending chain; release, in the contract that releases on the receiving chain; token, in the token contract; send + release, a limit on each side. Shapes as in Table~\\ref{tab:shapes}: a ramp lets value out in proportion to time, a cliff all at once when a timer runs out, a geometric limit a fixed share of the balance per period, a bounded limit a fixed total. Accounting: gross counts releases only; net subtracts counted inflows (Section~\\ref{sec:shape}). Automatic release: queued withdrawals leave when a timer expires; uncounted means outside the limit. Parameters: who can change the limit; no limit\'s code delays a loosening. Pause: who can stop releases. Issuer: the token\'s issuer; operator, owner and governors: a party other than the verifiers. Flow cancelling: inbound transfers offset the cap. Curse: CCIP\'s stop on releases. RWA: real-world asset.}',
        '\\label{tab:rules}',
        '\\scriptsize',
        '\\setlength{\\tabcolsep}{3pt}',
        '\\renewcommand{\\arraystretch}{1.05}',
        '\\begin{tabular}{@{}>{\\raggedright\\arraybackslash}p{2.95cm} >{\\raggedright\\arraybackslash}p{1.2cm} '
        '>{\\raggedright\\arraybackslash}p{3.55cm} >{\\raggedright\\arraybackslash}p{2.95cm} '
        '>{\\raggedright\\arraybackslash}p{1.95cm} >{\\raggedright\\arraybackslash}p{1.9cm} >{\\raggedright\\arraybackslash}p{2.0cm}@{}}',
        '\\toprule',
        'Limit & Stage & Shape & Accounting & Automatic release & Parameters & Pause \\\\',
        '\\midrule',
    ]
    for r in rules:
        cells = [r['rule'], r['stage'], r['shape'], r['accounting'], r['auto_release'], r['params_by'], r['pause_by']]
        lines.append(' & '.join(tex_escape(c) for c in cells) + ' \\\\')
    lines += ['\\bottomrule', '\\end{tabular}', '\\end{table*}']
    (HERE / 'tab_rules.tex').write_text('\n'.join(lines) + '\n', encoding='utf-8')


def timing_table():
    rows = read(HERE / 'timing.json')
    lines = [
        '\\begin{table}[t]',
        '\\centering',
        '\\caption{Timing of the failures, measured from the first unauthorized release: median and quartiles over the $n$ failures where each time is known. Last release, 90\\% out: a quartile of 0\\,s means that at least a quarter of these failures released everything within one block. Alert: the first public alert by a third party. Acknowledgment: the operator\'s first public statement. First response: the earlier of the acknowledgment and the pause, or for one failure a third party\'s report that the pause had happened.}',
        '\\label{tab:timing}',
        '\\footnotesize',
        '\\setlength{\\tabcolsep}{4pt}',
        '\\begin{tabular}{@{}l r r r@{}}',
        '\\toprule',
        'Quantity & $n$ & Median & Quartiles \\\\',
        '\\midrule',
    ]
    for r in rows:
        lines.append(f"{r['label']} & {r['n']} & {r['median']} & {r['q1']} to {r['q3']} \\\\")
    lines += ['\\bottomrule', '\\end{tabular}', '\\end{table}']
    (HERE / 'tab_timing.tex').write_text('\n'.join(lines) + '\n', encoding='utf-8')


def ccip_table():
    rows = read(HERE / 'rolling.json')
    cur = rows[0]['current']
    lines = [
        '\\begin{table}[t]',
        '\\centering',
        f"\\caption{{Buckets refitted every 30 days to the previous 90 days, for a response time $D$ and a margin $m$, against the deployed buckets on the same 30-day segments ({rows[0]['lanes']} CCIP token lanes). Delayed: share of legitimate value that waited. Cap: median over lanes of the policy's release within $D$ divided by the deployed bucket's.}}",
        '\\label{tab:ccip}',
        '\\footnotesize',
        '\\begin{tabular}{@{}l r r@{}}',
        '\\toprule',
        'Rule & Delayed & Cap \\\\',
        '\\midrule',
        f'Deployed buckets & {100 * cur:.1f}\\% & 1 \\\\',
    ]
    for r in rows:
        D, m = r['key'].split(' m=')
        hours = D.replace(' h', '')
        label = '$D = ' + hours + '$\\,h, $m = ' + f'{float(m):g}' + '$'
        lines.append(label + f" & {100 * r['delayed']:.1f}\\% & {r['ratio']:.2f} \\\\")
    lines += ['\\bottomrule', '\\end{tabular}', '\\end{table}']
    (HERE / 'tab_ccip.tex').write_text('\n'.join(lines) + '\n', encoding='utf-8')


def robust_table():
    rob = read(HERE / 'robust.json')
    rows = [('uniform ramp 1e+06', 'Bucket, \\$1M per hour'),
            ('uniform cliff 24', 'Hold, 24 hours'),
            ('uniform freeze 1e+07', 'Cumulative cap, \\$10M'),
            ('matched full|12 months', 'Matched, 12 months'),
            ('matched full|24 months', 'Matched, 24 months'),
            ('matched small|12 months', 'Matched with review, 12 months'),
            ('matched small|24 months', 'Matched with review, 24 months'),
            ('verifier ramp 1e+06', 'Bucket in the verifiers\' software')]
    n_p = rob['uniform ramp 1e+06']['n_pauses']
    lines = [
        '\\begin{table*}[t]',
        '\\centering',
        f"\\caption{{Share of the value of the failures that each limit would have kept, under other readings of the response time and other weightings. Base: as in Section~\\ref{{sec:shape}}. 90\\% interval: 5th to 95th percentile of the base share over 2,000 resamples of the failures. $2D$, $D + 1$\\,h, $D + 6$\\,h: the first response doubled or delayed. Pauses: only the {n_p} failures whose first response was a pause. By event: each failure weighted equally. Without largest: the largest failure, {100 * rob['uniform ramp 1e+06']['largest_share_of_value']:.0f}\\% of the value, left out; without 3 largest: the three largest, {100 * rob['uniform ramp 1e+06']['top3_share_of_value']:.0f}\\%. Matched: one limit at the release point that delays no transfer of the combined traffic of Wormhole's nine chains over the last 12 or 24 months, applied to every failure; with review, transfers above the Governor's size threshold wait for a review and the limit is matched to the rest. All limits but the last sit at the release point.}}",
        '\\label{tab:robust}',
        '\\footnotesize',
        '\\setlength{\\tabcolsep}{4pt}',
        '\\begin{tabular}{@{}l r r r r r r r r r@{}}',
        '\\toprule',
        'Limit & Base & 90\\% interval & $2D$ & $D + 1$\\,h & $D + 6$\\,h & Pauses & By event & Without largest & Without 3 largest \\\\',
        '\\midrule',
    ]
    for key, label in rows:
        v = rob[key]
        cells = [v['D_times_2'], v['D_plus_1h'], v['D_plus_6h'], v['pauses_only'], v['event_weighted'], v['without_largest'], v['without_top3']]
        lines.append(label + f" & {100 * v['base']:.1f}\\% & {100 * v['boot_lo']:.0f} to {100 * v['boot_hi']:.0f}\\% & "
                     + ' & '.join(f'{100 * x:.1f}\\%' for x in cells) + ' \\\\')
    lines += ['\\bottomrule', '\\end{tabular}', '\\end{table*}']
    (HERE / 'tab_robust.tex').write_text('\n'.join(lines) + '\n', encoding='utf-8')


def validation_table():
    with open(HERE / 'validation.csv', encoding='utf-8') as f:
        rows = list(csv.DictReader(f))
    lines = [
        '\\begin{table}[t]',
        '\\centering',
        '\\caption{Failures that met a limit in force. Prediction: what the model says the limit could keep, from its placement, control and shape (Section~\\ref{sec:where}); for the first three limits, at the release point under separate control, the bound from the parameters in force and the time the outflow ran. Outcome: what the failure released (Appendix~\\ref{app:events}).}',
        '\\label{tab:validation}',
        '\\scriptsize',
        '\\setlength{\\tabcolsep}{2.5pt}',
        '\\begin{tabular}{@{}>{\\raggedright\\arraybackslash}p{1.42cm} >{\\raggedright\\arraybackslash}p{2.0cm} '
        '>{\\raggedright\\arraybackslash}p{2.3cm} >{\\raggedright\\arraybackslash}p{2.3cm}@{}}',
        '\\toprule',
        'Failure & Limit in force & Prediction & Outcome \\\\',
        '\\midrule',
    ]
    for r in rows:
        cells = [r['failure'], r['rule_in_force'], r['prediction'], r['outcome']]
        lines.append(' & '.join(tex_escape(c) for c in cells) + ' \\\\')
    lines += ['\\bottomrule', '\\end{tabular}', '\\end{table}']
    (HERE / 'tab_validation.tex').write_text('\n'.join(lines) + '\n', encoding='utf-8')


def response_table():
    r2 = read(HERE.parents[1] / 'probes' / 'bridge_limits' / 'results' / 'replay_variants.json')
    cols = [('base', 'As observed'), ('x2', '$2D$'), ('x5', '$5D$'), ('x10', '$10D$'),
            ('outflow_detected_never', 'No response if found by outflow'), ('no_independent_pause_never', 'No response without independent pause'),
            ('alert_time', 'Response at first alert'), ('alarm_1h', 'Alarm, 1 h'), ('alarm_10min', 'Alarm, 10 min'),
            ('all57_untimed_never', 'All 57')]
    rules = [('bucket 1M/h', 'Bucket, \\$1M per hour'), ('hold 24 h', 'Hold, 24 hours'), ('matched benchmark', 'Matched to traffic')]
    lines = [
        '\\begin{table*}[t]',
        '\\centering',
        '\\caption{Share of the value of the failures kept at the release point when the response time changes. $kD$: every response time multiplied by $k$. No response if found by outflow: the failures detected through their own outflow (third-party alert, user report, shortfall) get no response. No response without independent pause: the same for failures where no independent party could pause. Response at first alert: the first public alert by a third party, where earlier. Alarm: an independent pause one hour or ten minutes after the first release that no deposit backs. All 57: the untimed failures included, with no response.}',
        '\\label{tab:response}',
        '\\footnotesize',
        '\\setlength{\\tabcolsep}{2.5pt}',
        '\\begin{tabular}{@{}l ' + 'r ' * len(cols) + '@{}}',
        '\\toprule',
        'Limit & ' + ' & '.join('\\multicolumn{1}{p{1.3cm}}{\\raggedleft ' + c + '}' for _, c in cols) + ' \\\\',
        '\\midrule',
    ]
    for key, label in rules:
        v = r2['response'][key]
        lines.append(label + ' & ' + ' & '.join(f'{100 * v[k]:.1f}\\%' for k, _ in cols) + ' \\\\')
    lines += ['\\bottomrule', '\\end{tabular}', '\\end{table*}']
    (HERE / 'tab_response.tex').write_text('\n'.join(lines) + '\n', encoding='utf-8')


def ccip_review_table():
    rv = read(HERE / 'review.json')
    base = rv['1 h m=1.0 q=None']
    rows = [('6 h m=1.5 q=None', '6', '1.5', 'no'),
            ('1 h m=1.5 q=None', '1', '1.5', 'no'),
            ('1 h m=1.0 q=0.99', '1', '1', 'yes'),
            ('1 h m=1.5 q=0.99', '1', '1.5', 'yes'),
            ('1 h m=2.0 q=0.99', '1', '2', 'yes'),
            ('6 h m=1.5 q=0.99', '6', '1.5', 'yes'),
            ('6 h m=2.0 q=0.99', '6', '2', 'yes')]
    lines = [
        '\\begin{table}[t]',
        '\\centering',
        f"\\caption{{Inbound buckets at the release point of {base['n_lanes']} CCIP token lanes, replayed on execution times in 30-day segments against today's buckets. Each 30 days, a bucket is refitted to the previous 90 days for a response time $D$ (in hours) and scaled by a margin $\\mu$. Review: transfers above the 99th percentile of sizes in the fit window, about {rv['1 h m=1.5 q=0.99']['reviews_per_lane_month']:.1f} per lane and month, wait for a review, and the bucket is fitted to the rest. Delayed: share of value that the bucket delayed. Delay: hours of waiting in the bucket per dollar of tested value. Reviewed: share of value sent to review. Even: the review latency, in hours, at which the delay per dollar, counting a reviewed transfer as waiting that latency, equals today's. 1\\,h, 6\\,h: release within that time, median over lanes, relative to today's bucket.}}",
        '\\label{tab:ccip}',
        '\\footnotesize',
        '\\setlength{\\tabcolsep}{2.6pt}',
        '\\begin{tabular}{@{}l l l r r r r r r@{}}',
        '\\toprule',
        '$D$ & $\\mu$ & Review & Delayed & Delay & Reviewed & Even & 1\\,h & 6\\,h \\\\',
        '\\midrule',
        f"\\multicolumn{{3}}{{@{{}}l}}{{Today's buckets}} & {100 * base['current_delayed_share']:.1f}\\% & {base['current_mean_delay_h_per_dollar']:.2f} & -- & -- & 1 & 1 \\\\",
    ]
    today_h = base['current_mean_delay_h_per_dollar']
    for key, D, mu, review in rows:
        p = rv[key]
        rs = p.get('review_share') or 0
        even = (today_h - p['mean_delay_h_per_dollar']) / rs if rs else None
        even_s = '--' if even is None else (f'{even:.1f}' if even > 0 else 'never')
        rev_s = f'{100 * rs:.0f}\\%' if rs else '--'
        lines.append(f"{D} & {mu} & {review} & {100 * p['delayed_share']:.1f}\\% & {p['mean_delay_h_per_dollar']:.2f} & {rev_s} & {even_s} & "
                     f"{p['median_cap_ratio']['1 h']:.2f} & {p['median_cap_ratio']['6 h']:.2f} \\\\")
    lines += ['\\bottomrule', '\\end{tabular}', '\\end{table}']
    (HERE / 'tab_ccip.tex').write_text('\n'.join(lines) + '\n', encoding='utf-8')


def hms_short(s):
    if not s:
        return '--'
    s = float(s)
    d, r = divmod(int(round(s)), 86400)
    h, r = divmod(r, 3600)
    m = r // 60
    if d:
        return f'{d}\\,d {h}\\,h'
    if h:
        return f'{h}\\,h {m}\\,min'
    return f'{m}\\,min'


def top_failures_table(k=20):
    P = HERE.parents[1] / 'probes' / 'bridge_limits' / 'results'
    with open(P / 'incidents.csv', encoding='utf-8') as f:
        inc = {r['id']: r for r in csv.DictReader(f) if r['in_bridge_set'] == 'yes'}
    with open(P / 'incident_coding.csv', encoding='utf-8') as f:
        cod = {r['id']: r for r in csv.DictReader(f)}
    cls = {'S': 'event', 'V': 'keys', 'D': 'flaw', 'O': 'other'}   # data code CHECK shown as FLAW
    det = {'third_party_alert': 'alert', 'operator_monitoring': 'operator', 'unknown': '--', 'escrow_or_balance_shortfall': 'shortfall',
           'user_report_or_failed_withdrawal': 'user', 'other': 'other'}
    pause = {'independent_of_failure': 'indep.', 'no_pause_function': 'none', 'controlled_by_failing_party': 'party', 'unknown': '--'}
    top = sorted(inc.values(), key=lambda r: -float(r['amount_usd']))[:k]
    tot = sum(float(r['amount_usd']) for r in inc.values())
    share = sum(float(r['amount_usd']) for r in top) / tot
    lines = [
        '\\begin{table*}[t]',
        '\\centering',
        f"\\caption{{The {k} largest failures, {100 * share:.0f}\\% of the value. Class: stage where the withdrawals entered. Outflow: first to last unauthorized release. Response: first public response (a: acknowledgment, p: pause). Found: how the operator learned (alert: a third party's public alert; operator: own monitoring; user: a user's report or failed withdrawal; shortfall: a shortfall in the escrow). Pause: who could pause (indep.: a party independent of the failure; party: the failing party; none: no pause on the path). Recovered: returned or frozen afterwards. All {len(inc)} failures, with sources, are in the artifact.}}",
        '\\label{tab:failures}',
        '\\scriptsize',
        '\\setlength{\\tabcolsep}{3pt}',
        '\\begin{tabular}{@{}l l r l l r r l l r@{}}',
        '\\toprule',
        'Failure & Year & \\$M & Class & Side & Outflow & Response & Found & Pause & Recovered \\\\',
        '\\midrule',
    ]
    short = short_names()          # the same names as Table 5
    for r in top:
        c = cod.get(r['id'], {})
        name = short.get(r['id'], r['name'].split(' (')[0])
        basis = {'acknowledgment': 'a', 'pause': 'p', 'pause report': 'p'}.get(r['response_basis'], '')
        resp = hms_short(r['response_delay_s']) + (f' {basis}' if basis and r['response_delay_s'] else '')
        rec = float(c.get('recovered_usd') or 0) / 1e6
        lines.append(' & '.join([tex_escape(name), r['date'][:4], f"{float(r['amount_usd']) / 1e6:,.0f}", cls.get(r['failure_class'][:1], r['failure_class']),
                                 r['release_side'] or '--', hms_short(r['outflow_duration_s']), resp,
                                 det.get(c.get('detection_channel', 'unknown'), '--'), pause.get(c.get('pause_holder', 'unknown'), '--'),
                                 f'{rec:,.0f}' if rec else '0']) + ' \\\\')
    lines += ['\\bottomrule', '\\end{tabular}', '\\end{table*}']
    (HERE / 'tab_failures.tex').write_text('\n'.join(lines) + '\n', encoding='utf-8')


def stake_table():
    with open(HERE / 'stake.csv', encoding='utf-8') as f:
        rows = list(csv.DictReader(f))
    lines = [
        '\\begin{table}[t]',
        '\\centering',
        '\\caption{Stake behind the verifiers against the value held at one time (Appendix~\\ref{app:methods}), in millions of US dollars. Stake is read on-chain. Held: assets in the escrow and lock contracts that the verifiers\' attestations release, read on-chain for Polygon (in part), Across and CCIP (the Ethereum lock-release pools), and otherwise the total reported by DefiLlama for Hyperlane, Lombard and LayerZero, Axelarscan for Axelar and Wormholescan for Wormhole. Confiscable: whether published rules let stake be taken for attesting to an invalid message. Nominal: the stake registered for the service, which its operators also restake for other services, at 1 ETH per share. Chainlink\'s LINK staking secures a price feed and is not counted for CCIP.}',
        '\\label{tab:stake}',
        '\\scriptsize',
        '\\setlength{\\tabcolsep}{2.5pt}',
        '\\begin{tabular}{@{}>{\\raggedright\\arraybackslash}p{2.75cm} >{\\raggedleft\\arraybackslash}p{0.95cm} >{\\raggedright\\arraybackslash}p{2.6cm} r r@{}}',
        '\\toprule',
        'System & Stake & Confiscable & Held & Ratio \\\\',
        '\\midrule',
    ]
    for r in rows:
        lines.append(' & '.join(tex_escape(c) for c in [r['system'], r['stake_musd'], r['confiscable_short'],
                                                          r['value_held_musd'], r['ratio']]) + ' \\\\')
    lines += ['\\bottomrule', '\\end{tabular}', '\\end{table}']
    (HERE / 'tab_stake.tex').write_text('\n'.join(lines) + '\n', encoding='utf-8')


def short_names():
    """Short event names from the curated records (probes/bridge_limits/incidents/curation.py)."""
    sys.path.insert(0, str(HERE.parents[1] / 'probes' / 'bridge_limits' / 'incidents'))
    import curation
    return {e['id']: e['short'] for e in curation.EVENTS}


PB_BUCKET, PB_REVIEW = 'bucket 6h m=1.5', 'review 1h m=1.5 q=0.999'


def perbridge_table():
    """Per-bridge counterfactual, kept shares (results/replay_perbridge.json from replay_perbridge.py)."""
    pb = read(HERE.parents[1] / 'probes' / 'bridge_limits' / 'results' / 'replay_perbridge.json')
    F, A = pb['failures'], pb['aggregate']
    short = short_names()
    cls = {'S': 'event', 'V': 'keys', 'D': 'flaw', 'O': 'other'}   # data code CHECK shown as FLAW
    EOL = ' ' + '\\' * 2      # LaTeX row end
    PCT = '\\%'
    lines = [
        r'\begin{table*}[t]',
        r'\centering',
        r"\caption{Limits fitted to each failed bridge's own traffic before the failure: share of the value released in the failure that each would have kept at the response time $D$. Legit: legitimate value released per day over the 150 days before the failure. Floor: the limit shaped like all 150 days, fitted in sample, which delays none of them; it is the most a limit that delays no legitimate transfer of that history could keep. Bucket: a token bucket fitted out of sample to the 90 days that end 30 days before the failure, for $D = 6$\,h, with a margin of 1.5. Review: transfers above the 99.9th percentile of sizes in those 90 days wait for a review that the party cannot pass, and a bucket for $D = 1$\,h with a margin of 1.5 takes the rest. Alarm: a pause one hour after the first release that no deposit backs, with the review design or alone, where the check flags the failure and someone other than the failing party can stop it. A range: the value released within the first hour is known only between bounds. Each release contract that a failure reaches has its own limit. Net: weighted by the value never returned or frozen. $^\dagger$Left out of the totals (Section~\ref{sec:perbridge}). Table~\ref{tab:pbcost} gives what the designs cost legitimate users and keep when the check fails.}",
        r'\label{tab:perbridge}',
        r'\footnotesize',
        r'\setlength{\tabcolsep}{4pt}',
        r'\begin{tabular}{@{}l l l r r r r r r r r@{}}',
        r'\toprule',
        r' & & & & & & \multicolumn{5}{c}{Kept at $D$} ' + EOL,
        r'\cmidrule(l){7-11}',
        r' & & & & & & In sample & \multicolumn{2}{c}{Out of sample} & \multicolumn{2}{c}{Alarm in 1\,h} ' + EOL,
        r'\cmidrule(lr){7-7} \cmidrule(lr){8-9} \cmidrule(l){10-11}',
        r'Failure & Year & Class & \$M & $D$ (h) & Legit (\$M/day) & Floor & Bucket & Review & Review & Alone' + EOL,
        r'\midrule',
    ]
    for i, f in sorted(F.items(), key=lambda kv: -kv[1]['A']):
        lim = f['limits']
        kept = [1 - lim[k]['loss'] / f['A'] for k in ('floor', PB_BUCKET, PB_REVIEW)]
        kept.append(1 - lim[PB_REVIEW]['loss_alarm_1h'] / f['A'])
        lo, hi = f['share_1h'] if f.get('check_sees', True) else (1.0, 1.0)   # unflagged or unstoppable: nothing kept
        alone = f'{100 * (1 - hi):.0f}' if round(100 * (1 - hi)) == round(100 * (1 - lo)) else f'{100 * (1 - hi):.0f}--{100 * (1 - lo):.0f}'
        name = short.get(i, i) + ('$^\\dagger$' if i in pb['params']['excluded_from_aggregates'] else '')
        per_day = f['legit_value_per_day'] / 1e6
        lines.append(' & '.join([name, f.get('date', '')[:4], cls[f['cls']],
                                 f"{f['A'] / 1e6:,.0f}", f"{f['D_h']:.1f}", f'{per_day:.2f}' if per_day >= 0.005 else '$<$0.01']
                                + [f'{100 * x:.0f}' + PCT for x in kept] + [alone + PCT]) + EOL)
    keys = [('floor', 'loss'), (PB_BUCKET, 'loss'), (PB_REVIEW, 'loss'), (PB_REVIEW, 'loss_alarm_1h')]
    ao = A['alarm_only_1h']
    lines.append(r'\midrule')
    lines.append(f"By value ({WORDS[len(A['ids'])]} failures) & & & & & & "
                 + ' & '.join(f"{100 * A[k][key]['value']:.0f}" + PCT for k, key in keys)
                 + f" & {100 * ao['value_lo']:.0f}" + PCT + EOL)
    lines.append('\\quad 90\\% bootstrap interval & & & & & & '
                 + ' & '.join(f"{100 * A[k][key]['boot_lo']:.0f}--{100 * A[k][key]['boot_hi']:.0f}" for k, key in keys) + ' & ' + EOL)
    lines.append('By failure & & & & & & ' + ' & '.join(f"{100 * A[k][key]['event']:.0f}" + PCT for k, key in keys)
                 + f" & {100 * ao['event_lo']:.0f}" + PCT + EOL)
    lines.append('Net & & & & & & ' + ' & '.join(f"{100 * A[k][key]['net']:.0f}" + PCT for k, key in keys) + ' & ' + EOL)
    lines += [r'\bottomrule', r'\end{tabular}', r'\end{table*}']
    (HERE / 'tab_perbridge.tex').write_text('\n'.join(lines) + '\n', encoding='utf-8')


def pbcost_table():
    """The designs on the failed bridges' traffic, with the check that deposits back each release
    working and failing, and what they cost legitimate users on the held-out months (replay_perbridge.json).
    Gate: every withdrawal held while the check runs (gate_h_s); a failure the check flags and someone can
    stop loses nothing; one it misses meets the limit behind the hold (replay_perbridge.py, check_sees)."""
    pb = read(HERE.parents[1] / 'probes' / 'bridge_limits' / 'results' / 'replay_perbridge.json')
    A, F = pb['aggregate'], pb['failures']
    ids = A['ids']
    H = pb['params']['gate_h_s']
    EOL = ' ' + '\\' * 2
    PCT = '\\%'
    bk, rv, lo3 = A[PB_BUCKET], A[PB_REVIEW], A['bucket 6h m=3.0']
    tot = sum(F[i]['A'] for i in ids)
    gate_alone_works = 1 - sum(0.0 if F[i]['check_sees'] else (F[i]['A'] if F[i]['D_h'] * 3600 > H else 0.0) for i in ids) / tot
    gate_alone_fails = 1 - sum(F[i]['A'] if F[i]['D_h'] * 3600 > H else 0.0 for i in ids) / tot

    def pair(a, key, fmt, scale=1.0, add=0.0):
        return '/'.join(fmt.format(scale * a[o][key] + add) for o in ('test_o1', 'test_o2'))

    def k(x):
        return f'{100 * x:.0f}'
    hrs = H / 3600
    rows = [
        ('Bucket', k(bk['loss']['value']), k(bk['loss']['value']), pair(bk, 'delayed_share', '{:.0f}', 100),
         pair(bk, 'count_delayed_share', '{:.1f}', 100), pair(bk, 'hours_per_dollar', '{:.1f}')),
        ('Review 1/1000', k(rv['loss']['value']), k(rv['loss_check_fails']['value']), pair(rv, 'total_delayed_share', '{:.0f}', 100),
         pair(rv, 'count_delayed_share', '{:.1f}', 100), pair(rv, 'hours_per_dollar_review1h', '{:.1f}')),
        ('\\quad + alarm 1\\,h', k(rv['loss_alarm_1h']['value']), k(rv['loss_check_fails']['value']),
         pair(rv, 'total_delayed_share', '{:.0f}', 100), pair(rv, 'count_delayed_share', '{:.1f}', 100),
         pair(rv, 'hours_per_dollar_review1h', '{:.1f}')),
        (f'Gate {H / 60:.0f}\\,min', k(gate_alone_works), k(gate_alone_fails), '100', '100', f'{hrs:.2f}'),
        ('\\quad + bucket', k(bk['loss_gate_works']['value']), k(bk['loss_gate_fails']['value']), '100', '100',
         pair(bk, 'hours_per_dollar', '{:.1f}', 1.0, hrs)),
        ('\\quad + bucket, margin 3', k(lo3['loss_gate_works']['value']), k(lo3['loss_gate_fails']['value']), '100', '100',
         pair(lo3, 'hours_per_dollar', '{:.1f}', 1.0, hrs)),
    ]
    lines = [
        r'\begin{table}[t]',
        r'\centering',
        r"\caption{Designs on the failed bridges' traffic, fitted a month ahead: share of the failures' value kept at the response time when the check that a deposit backs each withdrawal works and when it fails, and the cost to legitimate users in the month before each failure and the month before that (first/second number): value and transfers delayed (\%), and hours of delay per dollar, a reviewed transfer waiting one hour. Review: as in Table~\ref{tab:perbridge}, the review being the check. Gate: every withdrawal held while the check runs; behind it nothing, or the bucket of Table~\ref{tab:perbridge}, or that bucket with a margin of 3. Custody in a contract throughout; with custody as built, the gate keeps " + k(bk['loss_gate_works_built']['value']) + r"\% when the check works.}",
        r'\label{tab:pbcost}',
        r'\scriptsize',
        r'\setlength{\tabcolsep}{2.5pt}',
        r'\begin{tabular}{@{}l r r r r r@{}}',
        r'\toprule',
        r' & \multicolumn{2}{c}{Kept (\%), check} & \multicolumn{3}{c}{Cost} ' + EOL,
        r'\cmidrule(lr){2-3} \cmidrule(l){4-6}',
        r'Design & works & fails & Value & Transfers & h/\$' + EOL,
        r'\midrule',
    ]
    for row in rows:
        lines.append(' & '.join(row) + EOL)
    lines += [r'\bottomrule', r'\end{tabular}', r'\end{table}']
    (HERE / 'tab_pbcost.tex').write_text('\n'.join(lines) + '\n', encoding='utf-8')


if __name__ == '__main__':
    rules_table()
    timing_table()
    ccip_review_table()
    robust_table()
    validation_table()
    response_table()
    top_failures_table()
    stake_table()
    perbridge_table()
    pbcost_table()
