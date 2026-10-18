#!/usr/bin/env python3
from pathlib import Path
import json
ROOT = Path(__file__).resolve().parents[2]
local = ROOT / '.local/milestone0'
config = local / 'odoo.conf'
text = config.read_text()
if '/mnt/chainsql-addons' not in text:
    text = text.replace('addons_path = /mnt/extra-addons', 'addons_path = /mnt/extra-addons,/mnt/chainsql-addons')
    config.write_text(text)
creds = json.loads((local / 'credentials.json').read_text())
worker = local / 'worker.json'
worker.write_text(json.dumps(dict(host='host.docker.internal', port=55432, dbname='chainsql_m0',
                                 user='chainsql_worker', password=creds['worker'])))
worker.chmod(0o644)  # parent directory is 0700; container odoo UID needs read access
print('Configured custom addons and separate worker role; no credentials printed.')
