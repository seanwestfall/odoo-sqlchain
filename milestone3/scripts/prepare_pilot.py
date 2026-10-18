import json,subprocess
from pathlib import Path
root=Path(__file__).resolve().parents[2]
state=json.loads((root/'.local/circle_wallet/circle-setup.json').read_text())
recipient=state['wallets'][1]['address']
cmd=['docker','compose','-f',str(root/'milestone0/compose.yaml'),'-f',str(root/'milestone2/compose.yaml'),'run','--rm','-T','-e','ARC_RECIPIENT='+recipient,'odoo','odoo','shell','-d','chainsql_m0','--no-http','--log-level=critical']
r=subprocess.run(cmd,input=(root/'milestone3/scripts/prepare_pilot_odoo.py').read_text(),capture_output=True,text=True)
if r.returncode:raise RuntimeError(r.stdout+'\n'+r.stderr)
value=json.loads(next(l.removeprefix('PILOT:') for l in r.stdout.splitlines() if l.startswith('PILOT:')))
value['source_wallet']=state['wallets'][0]['id']
(root/'.local/milestone3/pilot.json').write_text(json.dumps(value,indent=2)+'\n')
print(json.dumps(value))
