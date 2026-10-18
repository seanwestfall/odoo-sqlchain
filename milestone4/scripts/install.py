from pathlib import Path
import subprocess
ROOT=Path(__file__).resolve().parents[2];pg=Path('/opt/homebrew/opt/postgresql@16/bin')
subprocess.run(['make','-C',str(ROOT/'chainsql/extension'),f'PG_CONFIG={pg}/pg_config','install'],check=True)
cmd=[str(pg/'psql'),'-Xq','-v','ON_ERROR_STOP=1','-h',str(ROOT/'.local/milestone0/socket'),'-p','55432','-U','m0_admin','-d','chainsql_m0']
v=subprocess.check_output(cmd+['-Atc',"SELECT extversion FROM pg_extension WHERE extname='chainsql'"],text=True).strip()
s=(ROOT/'milestone4/scripts/install.sql').read_text()
if v=='0.4.0':s=s.replace("ALTER EXTENSION chainsql UPDATE TO '0.4.0';",'')
subprocess.run(cmd,input=s,text=True,check=True)
