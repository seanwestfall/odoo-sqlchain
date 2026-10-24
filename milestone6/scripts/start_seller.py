"""Install/reload a loopback-only seller in the current user's launchd session (macOS)."""
import os,plistlib,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];local=ROOT/'.local/milestone6'
label='com.chainsql.m6.private-seller'
plist=Path.home()/'Library/LaunchAgents'/f'{label}.plist'
plist.parent.mkdir(parents=True,exist_ok=True)
config={'Label':label,'ProgramArguments':[sys.executable,str(ROOT/'chainsql/documents/seller.py'),'--directory',str(local/'seller'),'--key-file',str(local/'seller.key')],'WorkingDirectory':str(ROOT),'EnvironmentVariables':{'PATH':'/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin'},'RunAtLoad':True,'KeepAlive':True,'StandardOutPath':str(local/'seller.stdout.log'),'StandardErrorPath':str(local/'seller.stderr.log')}
plist.write_bytes(plistlib.dumps(config));plist.chmod(0o600)
domain=f'gui/{os.getuid()}'
subprocess.run(['launchctl','bootout',domain+'/'+label],capture_output=True)
subprocess.run(['launchctl','bootstrap',domain,str(plist)],check=True)
print('Private seller started on loopback port 8096.')
