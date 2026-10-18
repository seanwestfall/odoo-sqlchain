"""Renew only a provably unsigned, expired pilot. Never renew signed payments."""
from pathlib import Path
from datetime import datetime,timedelta,timezone
import json
import psycopg2
from psycopg2.extras import Json
ROOT=Path(__file__).resolve().parents[2];p=ROOT/'.local/milestone4/pilot.json';v=json.loads(p.read_text())
with psycopg2.connect(host=str(ROOT/'.local/milestone0/socket'),port=55432,user='m0_admin',dbname='chainsql_m0') as db:
 with db.cursor() as cur:
  cur.execute('SELECT state,dispatched_at,(snapshot->>\'valid_until\')::timestamptz,EXISTS(SELECT FROM chainsql.transfer_authorizations a WHERE a.transfer_id=t.id) FROM chainsql.transfers t WHERE id=%s FOR UPDATE',(v['purchase_id'],))
  state,sent,until,signed=cur.fetchone();assert state=='requested' and not sent and not signed and until<datetime.now(timezone.utc)
  cur.execute('SET LOCAL SESSION AUTHORIZATION chainsql_odoo')
  cur.execute('SELECT chainsql.cancel_transfer_v1(%s)',(v['purchase_id'],));assert cur.fetchone()[0]=='cancelled'
  cur.execute('RESET SESSION AUTHORIZATION');cur.execute('SET LOCAL ROLE chainsql_policy')
  s=dict(v['snapshot']);now=datetime.now(timezone.utc)
  s.update(request_revision=str(int(s['request_revision'])+1),valid_from=(now-timedelta(seconds=5)).isoformat().replace('+00:00','Z'),valid_until=(now+timedelta(minutes=55)).isoformat().replace('+00:00','Z'))
  cur.execute('SELECT chainsql.approve_resource_v1(%s,%s)',(Json(s),Json(v['request'])));aid=str(cur.fetchone()[0])
archive=p.with_name('pilot-unsigned-expired-'+v['purchase_id']+'.json');archive.write_text(p.read_text());archive.chmod(0o600)
v.update(snapshot=s,approval_id=aid)
for key in ['purchase_id','odoo_purchase_id']:v.pop(key,None)
p.write_text(json.dumps(v,indent=2));print('Expired unsigned request cancelled; new immutable approval revision',s['request_revision'])
