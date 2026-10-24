"""Isolated document-proof demo; keys and database configuration stay ignored."""
import configparser,os,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];RUNTIME=Path(os.environ.get('CHAINSQL_RUNTIME_ROOT',str(ROOT)))
pg=[str(Path(os.environ.get('PG_BIN','/opt/homebrew/opt/postgresql@16/bin'))/'psql'),'-XAt','-v','ON_ERROR_STOP=1','-h',str(RUNTIME/'.local/milestone0/socket'),'-p','55432','-U','m0_admin','-d','postgres']
exists=subprocess.check_output(pg+['-c',"SELECT 1 FROM pg_database WHERE datname='chainsql_m6_dev'"],text=True).strip()
if not exists:
    running=subprocess.check_output(['docker','ps','--filter','label=com.docker.compose.project=chainsql-m5','--format','{{.ID}}'],text=True).split()
    if running:subprocess.run(['docker','stop',*running],check=True,capture_output=True)
    try:subprocess.run(pg+['-c','CREATE DATABASE chainsql_m6_dev OWNER chainsql_odoo TEMPLATE chainsql_m5_dev'],check=True)
    finally:
        if running:subprocess.run(['docker','start',*running],check=True,capture_output=True)
local=ROOT/'.local/milestone6';local.mkdir(mode=0o700,parents=True,exist_ok=True);local.chmod(0o700)
for name in ['document.key','seller.key']:
    p=local/name
    if not p.exists():p.write_bytes(os.urandom(32))
    p.chmod(0o644 if name=='document.key' else 0o600)
config=configparser.ConfigParser();config.read(RUNTIME/'.local/milestone0/odoo.conf');config['options']['db_name']='chainsql_m6_dev';config['options']['dbfilter']='^chainsql_m6_dev$'
with (local/'odoo.conf').open('w') as f:config.write(f)
(local/'odoo.conf').chmod(0o644)
c=['docker','compose','-f',str(ROOT/'milestone6/compose.yaml')]
subprocess.run(c+['stop','odoo'],check=True,capture_output=True)
try:subprocess.run(c+['run','--rm','-T','odoo','odoo','-d','chainsql_m6_dev','-i','chainsql_document_account','--no-http','--stop-after-init','--log-level=error'],check=True)
finally:subprocess.run(c+['up','-d','odoo'],check=True)
subprocess.run([sys.executable,str(ROOT/'milestone6/scripts/repair_filestore.py')],check=True)
print('Document sample ready on http://localhost:8072; no public document or chain transaction created.')
