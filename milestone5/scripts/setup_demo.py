"""Create the isolated sample demo from an existing milestone-4 development DB."""
import configparser,os,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
RUNTIME=Path(os.environ.get('CHAINSQL_RUNTIME_ROOT',str(ROOT)))
PG=Path(os.environ.get('PG_BIN','/opt/homebrew/opt/postgresql@16/bin'))
pg=[str(PG/'psql'),'-XAt','-v','ON_ERROR_STOP=1','-h',str(RUNTIME/'.local/milestone0/socket'),'-p','55432','-U','m0_admin','-d','postgres']
exists=subprocess.check_output(pg+['-c',"SELECT 1 FROM pg_database WHERE datname='chainsql_m5_dev'"],text=True).strip()
if not exists:
    running=subprocess.check_output(['docker','ps','--filter','label=com.docker.compose.project=chainsql-m0','--format','{{.ID}}'],text=True).split()
    if running:subprocess.run(['docker','stop',*running],check=True)
    try:subprocess.run(pg+['-c','CREATE DATABASE chainsql_m5_dev OWNER chainsql_odoo TEMPLATE chainsql_m0'],check=True)
    finally:
        if running:subprocess.run(['docker','start',*running],check=True)
local=ROOT/'.local/milestone5';local.mkdir(parents=True,exist_ok=True,mode=0o700)
config=configparser.ConfigParser();config.read(RUNTIME/'.local/milestone0/odoo.conf')
config['options']['db_name']='chainsql_m5_dev';config['options']['dbfilter']='^chainsql_m5_dev$'
with (local/'odoo.conf').open('w') as f:config.write(f)
(local/'odoo.conf').chmod(0o644)
compose=['docker','compose','-f',str(ROOT/'milestone5/compose.yaml')]
subprocess.run(compose+['stop','odoo'],check=True)
try:
    subprocess.run(compose+['run','--rm','-T','odoo','odoo','-d','chainsql_m5_dev','-i','chainsql_purchase_account','-u','chainsql_purchase_account','--no-http','--stop-after-init','--log-level=error'],check=True)
finally:subprocess.run(compose+['up','-d','odoo'],check=True)
print('Sample-only milestone 5 demo: http://localhost:8071')
