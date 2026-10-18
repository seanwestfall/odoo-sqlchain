import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'chainsql/x402'))
from controller import ResourceController
p=argparse.ArgumentParser();p.add_argument('purchase_id');p.add_argument('--reconcile',action='store_true');a=p.parse_args()
c=json.loads((ROOT/'.local/milestone4/boundary.json').read_text());executor=ResourceController(c)
if a.reconcile:result=executor.run(a.purchase_id,reconcile_only=True)
else:
 # Trusted operator CLI claims with the existing worker's limited DB role.
 import psycopg2
 c0=json.loads((ROOT/'.local/milestone0/credentials.json').read_text())
 with psycopg2.connect(host='127.0.0.1',port=55432,dbname='chainsql_m0',user='chainsql_worker',password=c0['worker']) as db:
  with db.cursor() as cur:
   cur.execute('SELECT * FROM chainsql.claim_transfer_v1(%s)',(a.purchase_id,));_,token,fence,_=cur.fetchone()
 result=executor.run(a.purchase_id,str(token),fence)
print(json.dumps(result,indent=2))
