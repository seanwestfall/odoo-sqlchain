#!/usr/bin/env python3
"""Provision the local pilot; never prints passwords or private key material."""
import base64
import json
import os
import secrets
import subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
LOCAL=ROOT/'.local/milestone2'
LOCAL.mkdir(exist_ok=True,mode=0o700)
PG=Path('/opt/homebrew/opt/postgresql@16/bin')
psql=[str(PG/'psql'),'-XqAt','-v','ON_ERROR_STOP=1','-h',str(ROOT/'.local/milestone0/socket'),'-p','55432','-U','m0_admin']
def sql(q,db='chainsql_m0'):
    p=subprocess.run(psql+['-d',db],input=q,text=True,capture_output=True,check=True)
    return p.stdout.strip()
creds_path=LOCAL/'credentials.json'
if creds_path.exists(): creds=json.loads(creds_path.read_text())
else:
    creds={k:secrets.token_hex(32) for k in ['signer','observer']}
    creds_path.write_text(json.dumps(creds));creds_path.chmod(0o600)
for role in ['chainsql_policy','chainsql_signer','chainsql_observer']:
    if not sql(f"SELECT 1 FROM pg_roles WHERE rolname='{role}'"):
        if role=='chainsql_policy': options='NOLOGIN'
        else: options="LOGIN PASSWORD '"+creds[role.removeprefix('chainsql_')]+"'"
        sql(f'CREATE ROLE {role} {options} NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT')
sql("ALTER ROLE chainsql_signer SET log_min_error_statement = 'panic'; ALTER ROLE chainsql_signer SET log_statement = 'none'; ALTER ROLE chainsql_signer SET log_min_duration_statement = -1; ALTER ROLE chainsql_signer SET log_parameter_max_length = 0; ALTER ROLE chainsql_signer SET log_parameter_max_length_on_error = 0")
sql('GRANT CONNECT ON DATABASE chainsql_m0 TO chainsql_signer,chainsql_observer')
subprocess.run(['make','-C',str(ROOT/'chainsql/extension'),f'PG_CONFIG={PG}/pg_config','install'],check=True)
# The script is repeatable: ALTER EXTENSION only when needed; ACLs are reapplied.
s= (ROOT/'milestone2/scripts/install.sql').read_text()
if sql("SELECT extversion FROM pg_extension WHERE extname='chainsql'") in ('0.2.1','0.3.0'):
    s=s.replace("ALTER EXTENSION chainsql UPDATE TO '0.2.1';",'')
sql(s)
for role in ['signer','observer']:
    p=LOCAL/(role+'.json')
    if not p.exists():
        value={'database':dict(host='host.docker.internal',port=55432,dbname='chainsql_m0',user='chainsql_'+role,password=creds[role])}
        if role=='signer':
            value.update(signing_seed=base64.b64encode(os.urandom(32)).decode(),encryption_key=base64.b64encode(os.urandom(32)).decode())
        p.write_text(json.dumps(value));p.chmod(0o600)
print('Native extension upgraded to 0.2.1; separate signer/observer roles and NOLOGIN policy role ready. Execution defaults paused.')
