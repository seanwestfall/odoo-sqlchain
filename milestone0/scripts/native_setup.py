#!/usr/bin/env python3
"""Create/start only the disposable milestone-0 native PostgreSQL cluster."""
import json
import os
from pathlib import Path
import secrets
import subprocess

ROOT = Path(__file__).resolve().parents[2]
LOCAL = ROOT / '.local/milestone0'
PG = Path(os.environ.get('PG_BIN', '/opt/homebrew/opt/postgresql@16/bin'))
LOCAL.mkdir(parents=True, exist_ok=True)
LOCAL.chmod(0o700)
secret_file = LOCAL / 'credentials.json'
if not secret_file.exists():
    secret_file.write_text(json.dumps({name: secrets.token_hex(24) for name in
        ('odoo', 'worker', 'manager')}, indent=2))
    secret_file.chmod(0o600)
credentials = json.loads(secret_file.read_text())
data = LOCAL / 'pgdata'
socket = LOCAL / 'socket'
socket.mkdir(exist_ok=True)
if not (data / 'PG_VERSION').exists():
    subprocess.run([str(PG / 'initdb'), '-D', str(data), '-U', 'm0_admin',
                    '--auth-local=trust', '--auth-host=scram-sha-256', '--encoding=UTF8',
                    '--locale=C'], check=True)
    with (data / 'postgresql.conf').open('a') as f:
        f.write(f"\nlisten_addresses = '127.0.0.1'\nport = 55432\n"
                f"unix_socket_directories = '{socket}'\n")
status = subprocess.run([str(PG / 'pg_ctl'), '-D', str(data), 'status'], capture_output=True)
if status.returncode:
    subprocess.run([str(PG / 'pg_ctl'), '-D', str(data), '-l', str(LOCAL / 'postgres.log'),
                    '-w', 'start'], check=True)

def sql(query, database='postgres'):
    return subprocess.run([str(PG / 'psql'), '-X', '-v', 'ON_ERROR_STOP=1', '-At',
                           '-h', str(socket), '-p', '55432', '-U', 'm0_admin', '-d', database],
                          input=query, text=True, check=True, capture_output=True).stdout.strip()

for role, options in (
    ('chainsql_owner', 'NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT'),
    ('chainsql_odoo', f"LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT PASSWORD '{credentials['odoo']}'"),
    ('chainsql_worker', f"LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT PASSWORD '{credentials['worker']}'"),
):
    if not sql(f"SELECT 1 FROM pg_roles WHERE rolname='{role}';"):
        sql(f'CREATE ROLE {role} {options};')
if not sql("SELECT 1 FROM pg_database WHERE datname='chainsql_m0';"):
    sql('CREATE DATABASE chainsql_m0 OWNER chainsql_odoo TEMPLATE template0;')
sql('REVOKE ALL ON DATABASE chainsql_m0 FROM PUBLIC; '
    'GRANT CONNECT ON DATABASE chainsql_m0 TO chainsql_odoo, chainsql_worker;', 'chainsql_m0')
sql('REVOKE CREATE ON SCHEMA public FROM PUBLIC; '
    'CREATE EXTENSION IF NOT EXISTS pg_trgm; '
    'CREATE EXTENSION IF NOT EXISTS unaccent; '
    'ALTER FUNCTION public.unaccent(text) IMMUTABLE;', 'chainsql_m0')
config = LOCAL / 'odoo.conf'
config.write_text('[options]\naddons_path = /mnt/extra-addons,/mnt/chainsql-addons\ndata_dir = /var/lib/odoo\n'
                  'db_host = host.docker.internal\ndb_port = 55432\ndb_user = chainsql_odoo\n'
                  f"db_password = {credentials['odoo']}\nadmin_passwd = {credentials['manager']}\n"
                  'db_name = chainsql_m0\ndbfilter = ^chainsql_m0$\nlist_db = False\n')
# Docker's odoo UID must read this file; enclosing directory remains owner-only.
config.chmod(0o644)
print('Native PostgreSQL ready on localhost:55432; database chainsql_m0. Credentials are in ignored local files.')
