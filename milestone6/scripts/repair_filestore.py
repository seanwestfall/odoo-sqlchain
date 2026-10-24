"""Copy missing filestore objects from M5; regenerate only missing generated web assets."""
import subprocess,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
c=['docker','compose','-f',str(ROOT/'milestone6/compose.yaml')]
with tempfile.TemporaryDirectory(prefix='chainsql-m6-filestore-') as tmp:
    subprocess.run(['docker','cp','chainsql-m5-odoo-1:/var/lib/odoo/filestore/chainsql_m5_dev/.',tmp],check=True,capture_output=True)
    subprocess.run(c+['exec','-T','--user','root','odoo','mkdir','-p','/tmp/m6-filestore-seed'],check=True)
    subprocess.run(['docker','cp',tmp+'/.','chainsql-m6-odoo-1:/tmp/m6-filestore-seed/'],check=True,capture_output=True)
    code='''from pathlib import Path
import shutil,os,hashlib
src=Path('/tmp/m6-filestore-seed');dst=Path('/var/lib/odoo/filestore/chainsql_m6_dev');count=0
for p in src.glob('*/*'):
 if not p.is_file() or p.is_symlink() or len(p.name)!=40:continue
 if hashlib.sha1(p.read_bytes()).hexdigest()!=p.name:continue
 target=dst/p.relative_to(src)
 if target.exists():continue
 target.parent.mkdir(parents=True,exist_ok=True)
 shutil.copyfile(p,target);os.chown(target,101,101);os.chown(target.parent,101,101);count+=1
print('Copied missing content-addressed objects:',count)
shutil.rmtree(src)
'''
    subprocess.run(c+['exec','-T','--user','root','odoo','python3','-c',code],check=True)
code='''from pathlib import Path
items=env['ir.attachment'].sudo().search([('url','=like','/web/assets/%'),('store_fname','!=',False)])
missing=items.filtered(lambda a:not Path(a._full_path(a.store_fname)).is_file())
print('Invalidating missing generated assets:',len(missing))
missing.unlink()
env.cr.commit()
'''
subprocess.run(c+['exec','-T','odoo','odoo','shell','-d','chainsql_m6_dev','--no-http','--log-level=error'],input=code,text=True,check=True)
subprocess.run(c+['restart','odoo'],check=True)
