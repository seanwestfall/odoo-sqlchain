#!/usr/bin/env python3
"""Exercise the real extension, role boundaries and pg_dump/restore in fresh databases."""
import concurrent.futures
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import uuid

ROOT = Path(__file__).resolve().parents[2]
LOCAL = ROOT / '.local/milestone0'
PG = Path(os.environ.get('PG_BIN', '/opt/homebrew/opt/postgresql@16/bin'))
CREDENTIALS = json.loads((LOCAL / 'credentials.json').read_text())
CHECKS = []

def sql(query, db='postgres', role='m0_admin', fails=None):
    env = os.environ.copy()
    host = str(LOCAL / 'socket')
    if role != 'm0_admin':
        host = '127.0.0.1'
        env['PGPASSWORD'] = CREDENTIALS[{'chainsql_odoo': 'odoo', 'chainsql_worker': 'worker'}[role]]
    r = subprocess.run([str(PG / 'psql'), '-XqAt', '-v', 'ON_ERROR_STOP=1', '-h', host,
                        '-p', '55432', '-U', role, '-d', db], input=query, text=True,
                       capture_output=True, env=env, timeout=60)
    if fails:
        assert r.returncode and fails in r.stderr, (r.stdout, r.stderr)
        return
    if r.returncode:
        raise RuntimeError(r.stderr)
    return r.stdout.strip()

def check(name, condition=True):
    assert condition, name
    CHECKS.append(name)
    print('PASS:', name)

def create_database(name):
    sql(f'CREATE DATABASE {name} OWNER chainsql_odoo TEMPLATE template0;')
    sql(f'REVOKE ALL ON DATABASE {name} FROM PUBLIC; '
        f'GRANT CONNECT ON DATABASE {name} TO chainsql_odoo, chainsql_worker;', name)
    sql('REVOKE CREATE ON SCHEMA public FROM PUBLIC;', name)
    sql((ROOT / 'milestone0/scripts/install_extension.sql').read_text(), name)

def rows(db):
    return sql("SELECT coalesce(jsonb_agg(to_jsonb(o) ORDER BY id), '[]'::jsonb) FROM chainsql.operations o;", db)

def role_checks(db):
    sql('SELECT * FROM chainsql.operations;', db, 'chainsql_odoo', 'permission denied')
    sql('SELECT * FROM chainsql.claim_probe();', db, 'chainsql_odoo', 'permission denied')
    sql("SELECT chainsql.enqueue_probe('{}','unauthorized');", db, 'chainsql_worker', 'permission denied')
    sql('SET ROLE chainsql_owner;', db, 'chainsql_odoo', 'permission denied')
    sql('SET ROLE chainsql_owner;', db, 'chainsql_worker', 'permission denied')
    sql('CREATE TABLE chainsql.forbidden(id int);', db, 'chainsql_odoo', 'permission denied')
    sql('CREATE TABLE public.forbidden(id int);', db, 'chainsql_worker', 'permission denied')

suffix = uuid.uuid4().hex[:12]
database = f'chainsql_verify_{suffix}'
restored = f'chainsql_restore_{suffix}'
create_database(database)
check('dedicated extension owner', sql("SELECT pg_get_userbyid(extowner) FROM pg_extension WHERE extname='chainsql';", database) == 'chainsql_owner')
check('application and worker roles are non-superuser and cannot create databases or roles',
      sql("SELECT bool_and(NOT rolsuper AND NOT rolcreatedb AND NOT rolcreaterole) FROM pg_roles WHERE rolname IN ('chainsql_owner','chainsql_odoo','chainsql_worker');") == 't')
role_checks(database)
check('application and worker cannot bypass their separate SQL APIs')
sql("BEGIN; SELECT chainsql.enqueue_probe('{}','rolled-back'); ROLLBACK;", database, 'chainsql_odoo')
check('rollback leaves no operation', sql('SELECT count(*) FROM chainsql.operations;', database) == '0')
key = 'concurrent-idempotency'
with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
    ids = list(pool.map(lambda _: sql(f"SELECT chainsql.enqueue_probe('{{\"probe\":1}}','{key}');", database, 'chainsql_odoo'), range(6)))
check('concurrent duplicate enqueue returns one operation', len(set(ids)) == 1)
sql(f"SELECT chainsql.enqueue_probe('{{\"probe\":2}}','{key}');", database, 'chainsql_odoo', 'different payload')
check('idempotency key rejects changed payload')
sql("SELECT chainsql.enqueue_probe('[]','invalid');", database, 'chainsql_odoo', 'must be an object')
check('invalid payload rejected')
for i in range(5):
    sql(f"SELECT chainsql.enqueue_probe('{{\"probe\":{i}}}','worker-{i}');", database, 'chainsql_odoo')
with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
    claimed = list(pool.map(lambda _: json.loads(sql('SELECT row_to_json(c) FROM chainsql.claim_probe() c;', database, 'chainsql_worker')), range(6)))
check('concurrent workers claim each committed operation once', len({r['id'] for r in claimed}) == 6)
check('empty queue returns no work', not sql('SELECT * FROM chainsql.claim_probe();', database, 'chainsql_worker'))
first = claimed[0]
sql(f"SELECT chainsql.complete_probe('{first['id']}','{uuid.uuid4()}','{{}}');", database, 'chainsql_worker', 'no matching active claim')
check('incorrect claim token rejected')
sql(f"SELECT chainsql.complete_probe('{first['id']}','{first['claim_token']}','{{\"observed\":true}}');", database, 'chainsql_worker')
check('worker completion is visible to requesting application',
      sql(f"SELECT state FROM chainsql.probe_status('{first['id']}');", database, 'chainsql_odoo') == 'observed')
sql(f"SELECT chainsql.complete_probe('{first['id']}','{first['claim_token']}','{{}}');", database, 'chainsql_worker', 'no matching active claim')
check('completion cannot be overwritten by replay')
sql("SELECT chainsql.enqueue_probe('{\"restore\":true}','pending-after-restore');", database, 'chainsql_odoo')
before = rows(database)
backup = LOCAL / f'{database}.dump'
admin = ['-h', str(LOCAL / 'socket'), '-p', '55432', '-U', 'm0_admin']
subprocess.run([str(PG / 'pg_dump'), *admin, '-Fc', '-f', str(backup), database], check=True, capture_output=True)
# Precreate with the correct owner: pg_restore cannot ALTER EXTENSION OWNER.
create_database(restored)
toc = subprocess.check_output([str(PG / 'pg_restore'), '--list', str(backup)], text=True)
toc_file = backup.with_suffix('.restore-list')
toc_file.write_text('\n'.join(';' + line if ' SCHEMA - chainsql ' in line else line
                              for line in toc.splitlines()) + '\n')
r = subprocess.run([str(PG / 'pg_restore'), *admin, '--exit-on-error', '-L', str(toc_file), '-d', restored, str(backup)],
                   text=True, capture_output=True)
if r.returncode:
    raise RuntimeError(r.stderr)
check('native pg_dump/pg_restore preserves all extension runtime rows exactly', rows(restored) == before)
check('restore preserves dedicated extension ownership', sql("SELECT pg_get_userbyid(extowner) FROM pg_extension WHERE extname='chainsql';", restored) == 'chainsql_owner')
role_checks(restored)
check('restored role boundaries still enforce permissions')
check('restored pending work is claimable', bool(sql('SELECT * FROM chainsql.claim_probe();', restored, 'chainsql_worker')))
sql('SELECT count(*) FROM public.account_move;', 'chainsql_m0', 'chainsql_worker', 'permission denied')
check('worker cannot read Odoo accounting records')
modules = json.loads(sql("SELECT jsonb_object_agg(name,state) FROM ir_module_module WHERE name IN ('account','purchase','stock','mrp');", 'chainsql_m0', 'chainsql_odoo'))
check('account installed; Purchase, Inventory and Manufacturing deferred', modules == {'account':'installed','purchase':'uninstalled','stock':'uninstalled','mrp':'uninstalled'})
report = {
    'observed_at_utc': datetime.now(timezone.utc).isoformat(), 'checks': CHECKS,
    'postgres_version': sql('SELECT version();'), 'database': database, 'restored_database': restored,
    'runtime_rows': len(json.loads(before)), 'runtime_rows_sha256': hashlib.sha256(before.encode()).hexdigest(),
    'backup_sha256': hashlib.sha256(backup.read_bytes()).hexdigest(),
    'odoo_modules': modules, 'scope': 'Native extension runtime restore and permissions; excludes Odoo filestore and Circle secrets.',
}
(ROOT / 'milestone0/evidence/native-verification.json').write_text(json.dumps(report, indent=2) + '\n')
print(f'{len(CHECKS)} checks passed. Disposable verification databases retained for inspection.')
