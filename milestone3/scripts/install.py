#!/usr/bin/env python3
"""Upgrade the native development extension; Arc stays disabled until policy enablement."""
from pathlib import Path
import subprocess
root=Path(__file__).resolve().parents[2]
pg=Path('/opt/homebrew/opt/postgresql@16/bin')
subprocess.run(['make','-C',str(root/'chainsql/extension'),f'PG_CONFIG={pg}/pg_config','install'],check=True)
psql=[str(pg/'psql'),'-XqAt','-v','ON_ERROR_STOP=1','-h',str(root/'.local/milestone0/socket'),'-p','55432','-U','m0_admin','-d','chainsql_m0']
s=(root/'milestone3/scripts/install.sql').read_text()
v=subprocess.check_output(psql+['-c',"SELECT extversion FROM pg_extension WHERE extname='chainsql'"],text=True).strip()
if v=='0.3.0':s=s.replace("ALTER EXTENSION chainsql UPDATE TO '0.3.0';",'')
subprocess.run(psql,input=s,text=True,check=True)
print('ChainSQL 0.3.0 installed. Existing Arc gate setting preserved (disabled on initial install).')
