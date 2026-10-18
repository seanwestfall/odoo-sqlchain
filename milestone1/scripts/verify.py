#!/usr/bin/env python3
"""Run integration checks in a unique native PostgreSQL clone; preserve JSON evidence."""
import json
import subprocess
import uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
compose=['docker','compose','-f',str(ROOT/'milestone0/compose.yaml')]
db='chainsql_m1_verify_'+uuid.uuid4().hex[:12]
pg=['/opt/homebrew/opt/postgresql@16/bin/psql','-X','-h',str(ROOT/'.local/milestone0/socket'),
    '-p','55432','-U','m0_admin','-d','postgres','-v','ON_ERROR_STOP=1']
running=subprocess.check_output(compose+['ps','--status','running','--services'],text=True).split()
resume=['odoo'] + (['mock-worker'] if 'mock-worker' in running else [])
subprocess.run(compose+['stop','odoo','mock-worker'],check=True)
try:
    subprocess.run(pg+['-c',f'CREATE DATABASE {db} OWNER chainsql_odoo TEMPLATE chainsql_m0;'],check=True)
finally:
    subprocess.run(compose+['up','-d',*resume],check=True)
command=compose+['run','--rm','-T','-v',str(ROOT/'milestone1/scripts')+':/app:ro',
    '-v',str(ROOT/'.local/milestone0/worker.json')+':/run/chainsql/worker.json:ro',
    'odoo','odoo','shell','-d',db,'--no-http','--log-level=critical']
r=subprocess.run(command,input=(ROOT/'milestone1/scripts/verify_odoo.py').read_text(),
                 text=True,capture_output=True)
print(r.stdout)
if r.returncode:
    print(r.stderr)
    raise SystemExit(r.returncode)
line=next(x for x in r.stdout.splitlines() if x.startswith('EVIDENCE_JSON:'))
evidence=json.loads(line.removeprefix('EVIDENCE_JSON:'))
(ROOT/'milestone1/evidence/integration.json').write_text(json.dumps(evidence,indent=2)+'\n')
print('Evidence saved. Verification clone retained: '+db)
