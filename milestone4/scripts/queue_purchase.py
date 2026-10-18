import json,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];p=ROOT/'.local/milestone4/pilot.json';v=json.loads(p.read_text());op=v['operation']['id']
if v.get('purchase_id'):raise SystemExit('Existing purchase: use run.py or --reconcile; no new queue.')
r=subprocess.run(['docker','compose','-f',str(ROOT/'milestone0/compose.yaml'),'exec','-T','-e',f'M4_OPERATION_ID={op}','odoo','odoo','shell','-d','chainsql_m0','--no-http','--log-level=critical'],input=(ROOT/'milestone4/scripts/odoo_queue.py').read_text(),text=True,capture_output=True)
if r.returncode:raise RuntimeError(r.stderr[-3000:])
result=json.loads(next(x[9:] for x in r.stdout.splitlines() if x.startswith('PURCHASE:')))
v.update(result);p.write_text(json.dumps(v,indent=2));(ROOT/'milestone4/evidence/odoo-queue.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
