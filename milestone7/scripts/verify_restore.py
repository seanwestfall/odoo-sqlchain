"""Full disposable Odoo DB+filestore restore drill with a pending probe; no payment."""
import hashlib,json,os,subprocess,sys,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];LOCAL=ROOT/'.local/release';PG=Path(os.environ.get('PG_BIN','/opt/homebrew/opt/postgresql@16/bin'))
backup=LOCAL/('backup-'+uuid.uuid4().hex[:8]);backup.mkdir(mode=0o700)
source='chainsql_release';target='chainsql_release_restore_'+uuid.uuid4().hex[:8]
pg=[str(PG/'psql'),'-XqAt','-v','ON_ERROR_STOP=1','-h',str(LOCAL/'socket'),'-p','55437','-U','m0_admin']
c=['docker','compose','-f',str(ROOT/'milestone7/compose.yaml')]
def sql(q,db=source):return subprocess.check_output(pg+['-d',db],input=q,text=True).strip()
def shell(code,db=source):
 p=subprocess.run(c+['run','--rm','-T','odoo','odoo','shell','-d',db,'--no-http','--log-level=error'],input=code,text=True,capture_output=True)
 if p.returncode:raise RuntimeError(p.stderr)
 return next(line[9:] for line in p.stdout.splitlines() if line.startswith('EVIDENCE:'))
checks=[]
sql('SET ROLE chainsql_policy;SELECT chainsql.set_pause_v1(true); SELECT chainsql.enable_arc_v1(false);')
subprocess.run(c+['stop','odoo'],check=True,capture_output=True)
try:
 info=json.loads(shell("""import json
raw=b'M7 SYNTHETIC restore attachment\\x00\\r\\n'
a=env['ir.attachment'].create({'name':'M7 restore fixture','raw':raw,'type':'binary','mimetype':'application/octet-stream'})
env.cr.execute("SELECT chainsql.enqueue_probe(%s::jsonb,%s)", ('{"test":"m7 restore; no settlement"}','m7-restore-fixture'))
op=str(env.cr.fetchone()[0]);env.cr.commit()
print('EVIDENCE:'+json.dumps({'attachment':a.id,'probe':op}))
"""))
 subprocess.run([str(PG/'pg_dump'),'-Fc','-h',str(LOCAL/'socket'),'-p','55437','-U','m0_admin','-d',source,'-f',str(backup/'database.dump')],check=True)
 subprocess.run(['docker','cp',f'chainsql-release-odoo-1:/var/lib/odoo/filestore/{source}',str(backup/'filestore')],check=True,capture_output=True)
 (backup/'document.key').write_bytes((LOCAL/'document.key').read_bytes());(backup/'document.key').chmod(0o600)
 manifest={str(p.relative_to(backup)):hashlib.sha256(p.read_bytes()).hexdigest() for p in backup.rglob('*') if p.is_file()}
 (backup/'manifest.json').write_text(json.dumps(manifest,indent=2))
 sql('CREATE DATABASE '+target+' OWNER chainsql_odoo TEMPLATE template0','postgres')
 sql('CREATE EXTENSION unaccent; CREATE EXTENSION pg_trgm; ALTER FUNCTION public.unaccent(text) IMMUTABLE;',target)
 subprocess.run([sys.executable,str(ROOT/'milestone7/scripts/upgrade_sql.py'),'--socket',str(LOCAL/'socket'),'--database',target,'--empty-restore-target'],check=True,capture_output=True)
 toc=subprocess.check_output([str(PG/'pg_restore'),'--list',str(backup/'database.dump')],text=True)
 (backup/'restore.toc').write_text('\n'.join(';'+line if ' SCHEMA - chainsql ' in line else line for line in toc.splitlines())+'\n')
 subprocess.run([str(PG/'pg_restore'),'--exit-on-error','-L',str(backup/'restore.toc'),'-h',str(LOCAL/'socket'),'-p','55437','-U','m0_admin','-d',target,str(backup/'database.dump')],check=True)
 sql('SET ROLE chainsql_policy;SELECT chainsql.set_pause_v1(true);SELECT chainsql.enable_arc_v1(false);',target)
 # Stopped container is still a valid docker cp target; restore to a different DB path.
 subprocess.run(['docker','cp',str(backup/'filestore'),f'chainsql-release-odoo-1:/var/lib/odoo/filestore/{target}'],check=True,capture_output=True)
 # Root helper fixes copied ownership for the Odoo service UID.
 subprocess.run(c+['run','--rm','-T','--user','root','odoo','chown','-R','odoo:odoo',f'/var/lib/odoo/filestore/{target}'],check=True,capture_output=True)
 code=f"""import json
assert env['ir.attachment'].browse({info['attachment']}).raw==b'M7 SYNTHETIC restore attachment\\x00\\r\\n'
env.cr.execute("SELECT state FROM chainsql.probe_status(%s)",({info['probe']!r},));assert env.cr.fetchone()[0]=='pending'
print('EVIDENCE:'+json.dumps({{'restored_attachment':True,'pending_probe':True,'paused':True,'arc_disabled':True}}))
"""
 assert sql('SELECT paused AND NOT enabled FROM chainsql.execution_gate CROSS JOIN chainsql.arc_gate',target)=='t'
 restored=json.loads(shell(code,target));assert all(restored.values());checks+=list(restored)
 subprocess.run(c+['run','--rm','-T','odoo','odoo','-d',target,'-u','chainsql_base,chainsql_account,chainsql_transfer_boundary,chainsql_arc_account,chainsql_resource_account,chainsql_purchase_account,chainsql_document_account','--no-http','--stop-after-init','--log-level=error'],check=True,capture_output=True)
 assert all(json.loads(shell(code,target)).values());checks.append('addon upgrade preserves attachment, pending probe and pause')
 assert all(hashlib.sha256((backup/p).read_bytes()).hexdigest()==h for p,h in manifest.items());checks.append('backup manifest remains valid')
 evidence={'source':source,'restored':target,'checks':checks,'test_kind':'synthetic pending probe plus full Odoo filestore; native-m3 separately tests signed pending transfers','backup_directory':str(backup.relative_to(ROOT))}
 (ROOT/'milestone7/evidence/restore.json').write_text(json.dumps(evidence,indent=2)+'\n');print(json.dumps(evidence))
finally:subprocess.run(c+['up','-d','odoo'],check=True,capture_output=True)
