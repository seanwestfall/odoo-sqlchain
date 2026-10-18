#!/usr/bin/env python3
"""Read this task's cumulative counters; never export conversation text."""
import argparse
import json
from pathlib import Path
parser=argparse.ArgumentParser()
parser.add_argument('session_log',type=Path)
args=parser.parse_args()
last=None;baseline=None;start=None;cutoff=None
for line in args.session_log.open():
    try:record=json.loads(line)
    except ValueError:continue
    payload=record.get('payload',{})
    if payload.get('type')=='token_count':
        last=(payload.get('info') or {}).get('total_token_usage',last)
        cutoff=record.get('timestamp')
    if baseline is None and payload.get('role')=='user' and 'milestone 2' in json.dumps(payload).lower():
        baseline=dict(last) if last else None
        start=record.get('timestamp')
if baseline is None or last is None:
    raise SystemExit('No matching milestone baseline/counters found.')
delta={key:last[key]-baseline.get(key,0) for key in last}
result={'scope':'Milestone 2 from its first user prompt, including resumed turns',
        'start':start,'measured_through':cutoff,'counter_delta':delta,
        'uncached_input_tokens':delta['input_tokens']-delta.get('cached_input_tokens',0),
        'notes':['Input totals include repeated context across model calls.',
                 'Cached input is a subset of input, not additional tokens.',
                 'Reasoning output is reported as a subset of output; do not add it again.',
                 'Measurement excludes tool calls and final response after this cutoff.',
                 'These counters are not a credit or monetary-cost calculation.']}
root=Path(__file__).resolve().parents[2]
(root/'milestone2/evidence/token-usage.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
