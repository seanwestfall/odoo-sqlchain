from pathlib import Path
import json,shutil
ROOT=Path(__file__).resolve().parents[2]
p=ROOT/'.local/milestone4';p.mkdir(mode=0o700,exist_ok=True)
base=json.loads((ROOT/'.local/milestone3/boundary.json').read_text())
# Use existing dedicated signer/observer credentials; never give them to Odoo.
signer=json.loads((ROOT/'.local/milestone2/signer.json').read_text())
observer=json.loads((ROOT/'.local/milestone2/observer.json').read_text())
worker=json.loads((ROOT/'.local/milestone0/worker.json').read_text())
conf=dict(signer=signer['database'],observer=observer['database'],encryption_key=signer['encryption_key'],tenant='odoo:chainsql_m0:1:x402',journal_directory=str(p/'journal'),node=shutil.which('node'),env_file=str(ROOT/'.local/circle_wallet/.env'),script=str(ROOT/'chainsql/x402/cli.mjs'))
# Docker-address configs become native-host configs for this restricted executor.
for name in ['signer','observer']:conf[name]['host']='127.0.0.1';conf[name]['port']=55432
f=p/'boundary.json';f.write_text(json.dumps(conf));f.chmod(0o600)
print('Private milestone 4 executor config created; no spending enabled.')
