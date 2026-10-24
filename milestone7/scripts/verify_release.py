"""Run existing native security suites against the new isolated PG16 cluster."""
import base64,json,os,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];LOCAL=ROOT/'.local/release';runtime=LOCAL/'test-runtime'
creds=json.loads((LOCAL/'credentials.json').read_text())
for n in [0,2]:(runtime/f'.local/milestone{n}').mkdir(parents=True,exist_ok=True,mode=0o700)
link=runtime/'.local/milestone0/socket'
if not link.exists():link.symlink_to(LOCAL/'socket',target_is_directory=True)
for n in [0,2]:
 p=runtime/f'.local/milestone{n}/credentials.json';p.write_text(json.dumps(creds));p.chmod(0o600)
p=runtime/'.local/milestone2/signer.json'
if not p.exists():p.write_text(json.dumps({'encryption_key':base64.b64encode(os.urandom(32)).decode(),'signing_seed':base64.b64encode(os.urandom(32)).decode()}));p.chmod(0o600)
results=[]
for n in [3,4]:
 evidence=ROOT/f'milestone7/evidence/native-m{n}.json'
 env=dict(os.environ,CHAINSQL_RUNTIME_ROOT=str(runtime),CHAINSQL_PG_PORT='55437',CHAINSQL_EVIDENCE_FILE=str(evidence))
 with (ROOT/f'milestone7/evidence/native-m{n}.log').open('w') as log:
  subprocess.run([sys.executable,str(ROOT/f'milestone{n}/scripts/verify_native.py')],env=env,stdout=log,stderr=log,check=True)
 results.append({'suite':n,'checks':len(json.loads(evidence.read_text())['checks'])})
print(json.dumps(results))
