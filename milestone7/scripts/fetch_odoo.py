"""Fetch only the pinned upstream Odoo revision for a source archive or checkout."""
import subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];p=ROOT/'vendor/odoo';pin='7bbce824a1897a912441a7f0511ffec505cbe1d5'
if (p/'.git').exists():
 actual=subprocess.check_output(['git','-C',str(p),'rev-parse','HEAD'],text=True).strip()
 if actual!=pin:raise SystemExit('Existing Odoo checkout differs; refusing to reset it.')
 print('Pinned Odoo checkout already present.')
else:
 if p.exists() and any(p.iterdir()):raise SystemExit('Nonempty vendor directory; refusing to overwrite.')
 p.mkdir(parents=True,exist_ok=True)
 subprocess.run(['git','init',str(p)],check=True)
 subprocess.run(['git','-C',str(p),'remote','add','origin','https://github.com/odoo/odoo.git'],check=True)
 subprocess.run(['git','-C',str(p),'fetch','--depth','1','origin',pin],check=True)
 subprocess.run(['git','-C',str(p),'checkout','--detach',pin],check=True)
