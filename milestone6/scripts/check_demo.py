"""Read-only HTTP/independent byte-verification checks; does not sign or spend."""
import base64,json,subprocess,urllib.request,urllib.error
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];local=ROOT/'.local/milestone6'
sample=json.loads((local/'seller-sample.json').read_text())
checks=[]
def get(headers):
    try:return urllib.request.urlopen(urllib.request.Request(sample['url'],headers=headers),timeout=10)
    except urllib.error.HTTPError as e:return e
r=get({'PAYMENT-SIGNATURE':'payment-does-not-grant-access'})
assert r.status==404;checks.append('unauthorized HTTP request denied before payment processing')
r=get({'Authorization':'Bearer '+sample['token']})
assert r.status==402
challenge=json.loads(base64.b64decode(r.headers['PAYMENT-REQUIRED']))
assert challenge['x402Version']==2 and challenge['accepts'][0]['amount']=='10000'
checks.append('authorized HTTP request returns x402 v2 402 challenge')
command=['node',str(ROOT/'chainsql/x402/document_cli.mjs'),'verify',str(local/'document.bin'),str(local/'manifest.json')]
assert subprocess.run(command,capture_output=True).returncode==0
checks.append('independent Node verifier accepts Odoo-exported original bytes')
changed=local/'changed.bin';changed.write_bytes((local/'document.bin').read_bytes()+b'changed');changed.chmod(0o600)
command[3]=str(changed)
assert subprocess.run(command,capture_output=True).returncode!=0
checks.append('independent Node verifier rejects changed bytes')
evidence={'checks':checks,'resource_url':sample['url'],'live_payment_performed':False,'arc_publication_performed':False,'network':'eip155:84532','price_atomic':'10000'}
(ROOT/'milestone6/evidence/demo-checks.json').write_text(json.dumps(evidence,indent=2)+'\n')
print(json.dumps(evidence))
