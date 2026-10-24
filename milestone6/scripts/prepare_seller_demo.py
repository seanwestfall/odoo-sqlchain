"""Trusted local handoff of an Odoo-approved synthetic snapshot; never an HTTP admin API."""
import base64,json,sys,time
from datetime import datetime
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'chainsql/documents'))
from core import Vault,proof
local=ROOT/'.local/milestone6'
output=(local/'acceptance-output.txt').read_text()
evidence=json.loads(next(x.removeprefix('EVIDENCE:') for x in output.splitlines() if x.startswith('EVIDENCE:')))
export=json.loads(next(x.removeprefix('PRIVATE_EXPORT:') for x in output.splitlines() if x.startswith('PRIVATE_EXPORT:')))
for name,value in [('export.json',export),('manifest.json',{k:export[k] for k in ['sha256','salt','commitment']})]:
    p=local/name;p.write_text(json.dumps(value));p.chmod(0o600)
data=base64.b64decode(export['bytes_b64']);salt=bytes.fromhex(export['salt'])
assert proof.verify(data,export['sha256'],salt,export['commitment'])
(local/'document.bin').write_bytes(data);(local/'document.bin').chmod(0o600)
(local/'acceptance-output.txt').chmod(0o600)
(ROOT/'milestone6/evidence/odoo-acceptance.json').write_text(json.dumps(evidence,indent=2)+'\n')
v=Vault(local/'seller', (local/'seller.key').read_bytes())
sample=local/'seller-sample.json'
if sample.exists():
    old=json.loads(sample.read_text())
    assert v.version(old['resource_id'])['version']==export['version'],'Existing sample belongs to a different acceptance run; retain its journal and use a separate directory.'
else:
    identity=v.publish(export['company'],export['source'],export['version'],data,int(datetime.fromisoformat(export['retain_until']).timestamp()),export['approved_by'],'10000','0x176c176a4a14a89741337a438ddead22a4f6fd05',salt=salt)
    token=v.buyer('sample-authorized-buyer','0x9CEa12375B83386a7366A50bA5626F1a4094EfDE')
    until=int(time.time())+86400;v.grant(identity,'sample-authorized-buyer',until)
    sample.write_text(json.dumps({'resource_id':identity,'token':token,'access_until':until,'url':'http://127.0.0.1:8096/resources/'+identity}));sample.chmod(0o600)
v.close()
print(json.dumps({'bill_id':evidence['bill_id'],'document_id':evidence['document_id'],'checks':len(evidence['checks']),'seller_prepared':True}))
