"""Print the reconciliation and coverage fields of raw/<ID>/summary.json for the new histories."""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def walk(d, prefix='', depth=0, out=None):
    out = [] if out is None else out
    if isinstance(d, dict):
        for k, v in d.items():
            walk(v, f'{prefix}.{k}' if prefix else k, depth + 1, out)
    elif isinstance(d, list):
        if len(d) <= 6 and all(not isinstance(x, (dict, list)) for x in d):
            out.append((prefix, d))
        else:
            out.append((prefix, f'[list of {len(d)}]'))
    else:
        out.append((prefix, d))
    return out


KEYS = ('check', 'reconc', 'balance', 'residual', 'gap', 'missing', 'unpriced', 'priced', 'excluded', 'warning',
        'note', 'coverage', 'complete', 'n_rows', 'rows', 'legs', 'window', 'value', 'usd', 'error', 'fail')

for i in sys.argv[1:]:
    s = json.load(open(os.path.join(HERE, 'raw', i, 'summary.json'), encoding='utf-8'))
    print(f'================ {i}')
    for k, v in walk(s):
        if any(x in k.lower() for x in KEYS):
            t = json.dumps(v, ensure_ascii=False) if not isinstance(v, str) else v
            print(f'  {k}: {t[:260]}')
