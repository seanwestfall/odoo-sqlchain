from pathlib import Path
import subprocess,json,os
ROOT=Path(__file__).resolve().parents[2]
# Existing runtime is kept in place during the repository migration.
RUNTIME=Path(os.environ.get('CHAINSQL_RUNTIME_ROOT','/Users/sean/Projects/odoo'))
command=['docker','compose','-f',str(RUNTIME/'milestone0/compose.yaml'),'run','--rm','-T','-v',str(ROOT/'chainsql/odoo_addons')+':/mnt/chainsql-addons:ro','odoo','odoo','shell','-d','chainsql_m5_dev','--no-http','--log-level=error']
r=subprocess.run(command,input=(ROOT/'milestone5/scripts/verify_odoo.py').read_text(),text=True,capture_output=True)
print(r.stdout)
if r.returncode:print(r.stderr[-6000:]);raise SystemExit(r.returncode)
v=json.loads(next(l[9:] for l in r.stdout.splitlines() if l.startswith('EVIDENCE:')))
(ROOT/'milestone5/evidence/integration.json').write_text(json.dumps(v,indent=2)+'\n')
