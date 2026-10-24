"""Complete sample mock jobs and synchronize through Odoo. No signing path."""
from pathlib import Path
from contextlib import closing
import importlib.util,json,os,subprocess
import psycopg2
ROOT=Path(__file__).resolve().parents[2]
RUNTIME=Path(os.environ.get('CHAINSQL_RUNTIME_ROOT',str(ROOT)))
spec=importlib.util.spec_from_file_location('mock',ROOT/'milestone1/scripts/mock_worker.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
c=json.loads((RUNTIME/'.local/milestone0/credentials.json').read_text())
with closing(psycopg2.connect(host='127.0.0.1',port=55432,dbname='chainsql_m5_dev',user='chainsql_worker',password=c['worker'])) as db:
    for _ in range(100):
        if not m.process_one(db):break
v=json.loads((ROOT/'milestone5/evidence/integration.json').read_text())
code=f"""from odoo import api
env=api.Environment(env.cr,env.ref('base.user_admin').id,{{'allowed_company_ids':[1]}})
op=env['chainsql.operation'].browse({v['operation_id']})
op.action_sync()
assert op.state=='observed' and op.move_id.payment_state=='not_paid'
env.cr.commit()
print('Observed mock result',op.id)
"""
r=subprocess.run(['docker','compose','-f',str(ROOT/'milestone5/compose.yaml'),'exec','-T','odoo','odoo','shell','-d','chainsql_m5_dev','--no-http','--log-level=error'],input=code,text=True,capture_output=True)
if r.returncode:print(r.stderr);r.check_returncode()
print(r.stdout);v['mock_observed']=True;(ROOT/'milestone5/evidence/integration.json').write_text(json.dumps(v,indent=2)+'\n')
