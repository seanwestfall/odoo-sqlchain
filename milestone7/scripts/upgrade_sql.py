"""Apply native extension migrations and ACLs without permitting a downgrade or execution."""
import argparse,os,subprocess
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--socket',required=True);p.add_argument('--port',default='55437');p.add_argument('--database',required=True);p.add_argument('--empty-restore-target',action='store_true');a=p.parse_args()
ROOT=Path(__file__).resolve().parents[2];PG=Path(os.environ.get('PG_BIN','/opt/homebrew/opt/postgresql@16/bin'))
cmd=[str(PG/'psql'),'-XqAt','-v','ON_ERROR_STOP=1','-h',a.socket,'-p',a.port,'-U','m0_admin','-d',a.database]
def run(q):return subprocess.check_output(cmd,input=q,text=True).strip()
v=run("SELECT extversion FROM pg_extension WHERE extname='chainsql'")
if a.empty_restore_target and v:raise SystemExit('Restore preparation requires an empty target without an existing extension')
versions=['0.1.0','0.2.0','0.2.1','0.3.0','0.4.0']
if v and v not in versions:raise SystemExit('Unsupported extension version; no downgrade attempted')
if not v:run((ROOT/'milestone0/scripts/install_extension.sql').read_text());v='0.1.0'
if versions.index(v)>=versions.index('0.2.0'):run('SET ROLE chainsql_policy; SELECT chainsql.set_pause_v1(true); RESET ROLE;')
for milestone,target in [('milestone2','0.2.1'),('milestone3','0.3.0'),('milestone4','0.4.0')]:
 s=(ROOT/milestone/'scripts/install.sql').read_text()
 if versions.index(v)>=versions.index(target):s=s.replace(f"ALTER EXTENSION chainsql UPDATE TO '{target}';",'')
 run(s)
 if versions.index(v)<versions.index(target):v=target
if not a.empty_restore_target:run('SET ROLE chainsql_policy; SELECT chainsql.set_pause_v1(true); SELECT chainsql.enable_arc_v1(false); RESET ROLE;')
print('Native extension 0.4.0 ready; empty restore target (keep all workers stopped).' if a.empty_restore_target else 'Native extension 0.4.0 installed/upgraded, ACLs applied, execution paused and Arc disabled.')
