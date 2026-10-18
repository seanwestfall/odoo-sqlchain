#!/usr/bin/env python3
"""Build private native boundary configuration; does not enable execution."""
import json,shutil
from pathlib import Path
root=Path(__file__).resolve().parents[2];local=root/'.local/milestone3';local.mkdir(mode=0o700,exist_ok=True)
roles={r:json.loads((root/f'.local/milestone2/{r}.json').read_text()) for r in ['signer','observer']}
for c in roles.values():c['database']['host']='127.0.0.1'
roles['signer'].pop('signing_seed',None)
conf=dict(**roles,node=shutil.which('node'),script=str(root/'chainsql/arc/cli.mjs'),env_file=str(root/'.local/circle_wallet/.env'),
 journal_directory=str(local/'dispatch-journal'),tenant='odoo:chainsql_m0:1:arc')
p=local/'boundary.json'
if not p.exists():p.write_text(json.dumps(conf));p.chmod(0o600)
w=json.loads((root/'.local/milestone0/worker.json').read_text());w['host']='127.0.0.1'
p=local/'worker.json';p.write_text(json.dumps(w));p.chmod(0o600)
print('Private Arc configuration ready. Execution gate unchanged; tenant is company 1 Arc pilot only.')
