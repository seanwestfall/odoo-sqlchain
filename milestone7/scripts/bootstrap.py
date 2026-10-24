"""Fresh local testnet-only installation. No signer process or wallet credentials."""
import base64,json,os,secrets,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];LOCAL=ROOT/'.local/release';PG=Path(os.environ.get('PG_BIN','/opt/homebrew/opt/postgresql@16/bin'))
LOCAL.mkdir(parents=True,exist_ok=True,mode=0o700);LOCAL.chmod(0o700)
port=55437;db='chainsql_release';socket=LOCAL/'socket';socket.mkdir(exist_ok=True,mode=0o700)
assert subprocess.check_output([str(PG/'postgres'),'--version'],text=True).split()[2].startswith('16.'),'Pilot supports PostgreSQL 16 only'
secret=LOCAL/'credentials.json'
if not secret.exists():
 secret.write_text(json.dumps({r:secrets.token_hex(32) for r in ['odoo','worker','signer','observer','manager','admin_password']}));secret.chmod(0o600)
creds=json.loads(secret.read_text());data=LOCAL/'pgdata'
if not (data/'PG_VERSION').exists():
 subprocess.run([str(PG/'initdb'),'-D',str(data),'-U','m0_admin','--auth-local=trust','--auth-host=scram-sha-256','--encoding=UTF8','--locale=C'],check=True,stdout=subprocess.DEVNULL)
 with (data/'postgresql.conf').open('a') as f:f.write(f"\nlisten_addresses='127.0.0.1'\nport={port}\nunix_socket_directories='{socket}'\n")
if subprocess.run([str(PG/'pg_ctl'),'-D',str(data),'status'],capture_output=True).returncode:
 subprocess.run([str(PG/'pg_ctl'),'-D',str(data),'-l',str(LOCAL/'postgres.log'),'-w','start'],check=True)
pg=[str(PG/'psql'),'-XqAt','-v','ON_ERROR_STOP=1','-h',str(socket),'-p',str(port),'-U','m0_admin']
def sql(q,database='postgres'):
 p=subprocess.run(pg+['-d',database],input=q,text=True,capture_output=True)
 if p.returncode:raise RuntimeError('Database setup failed; inspect local PostgreSQL log (credentials suppressed).')
 return p.stdout.strip()
for role in ['owner','policy','odoo','worker','signer','observer']:
 if not sql(f"SELECT 1 FROM pg_roles WHERE rolname='chainsql_{role}'"):
  options='NOLOGIN' if role in ['owner','policy'] else f"LOGIN PASSWORD '{creds[role]}'"
  sql(f'CREATE ROLE chainsql_{role} {options} NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT')
sql("ALTER ROLE chainsql_signer SET log_min_error_statement='panic'; ALTER ROLE chainsql_signer SET log_statement='none'; ALTER ROLE chainsql_signer SET log_min_duration_statement=-1; ALTER ROLE chainsql_signer SET log_parameter_max_length=0; ALTER ROLE chainsql_signer SET log_parameter_max_length_on_error=0")
if not sql(f"SELECT 1 FROM pg_database WHERE datname='{db}'"):sql(f'CREATE DATABASE {db} OWNER chainsql_odoo TEMPLATE template0')
sql(f'REVOKE ALL ON DATABASE {db} FROM PUBLIC; GRANT CONNECT ON DATABASE {db} TO chainsql_odoo,chainsql_worker,chainsql_signer,chainsql_observer',db)
sql('REVOKE CREATE ON SCHEMA public FROM PUBLIC; CREATE EXTENSION IF NOT EXISTS pg_trgm; CREATE EXTENSION IF NOT EXISTS unaccent; ALTER FUNCTION public.unaccent(text) IMMUTABLE',db)
subprocess.run(['make','-C',str(ROOT/'chainsql/extension'),f'PG_CONFIG={PG}/pg_config','install'],check=True)
subprocess.run([sys.executable,str(ROOT/'milestone7/scripts/upgrade_sql.py'),'--socket',str(socket),'--port',str(port),'--database',db],check=True)
for name in ['document.key','seller.key']:
 p=LOCAL/name
 if not p.exists():p.write_bytes(os.urandom(32))
 p.chmod(0o644 if name=='document.key' else 0o600)
(LOCAL/'odoo.conf').write_text('[options]\naddons_path=/mnt/extra-addons,/mnt/chainsql-addons\ndata_dir=/var/lib/odoo\ndb_host=host.docker.internal\ndb_port=55437\ndb_user=chainsql_odoo\ndb_password='+creds['odoo']+'\nadmin_passwd='+creds['manager']+'\ndb_name=chainsql_release\ndbfilter=^chainsql_release$\nlist_db=False\n')
(LOCAL/'odoo.conf').chmod(0o644)
c=['docker','compose','-f',str(ROOT/'milestone7/compose.yaml')]
initialized=sql("SELECT to_regclass('public.ir_module_module') IS NOT NULL",db)=='t'
subprocess.run(c+['stop','odoo'],check=True)
try:
 subprocess.run(c+['run','--rm','-T','odoo','odoo','-d',db,'-u' if initialized else '-i','chainsql_purchase_account,chainsql_document_account,chainsql_resource_account,chainsql_arc_account','--no-http','--stop-after-init','--log-level=error'],check=True)
 if not initialized:
  code="env.ref('base.user_admin').write({'login':'admin','password':"+repr(creds['admin_password'])+"});env.cr.commit()"
  subprocess.run(c+['run','--rm','-T','odoo','odoo','shell','-d',db,'--no-http','--log-level=error'],input=code,text=True,check=True,capture_output=True)
finally:subprocess.run(c+['up','-d','odoo'],check=True)
print('Fresh local app: http://localhost:8073. Admin password is in private .local/release/credentials.json. Execution remains paused.')
