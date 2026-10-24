"""Private operator measurement ledger for events not present in SQL audit history.
Never infer human intervention or successful business work from chain settlement.
"""
import argparse,json,os,sqlite3,time
from pathlib import Path
KINDS=('duplicate_suppressed','human_intervention','useful_work_completed')
def open_ledger(path):
 p=Path(path);p.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
 fd=os.open(p,os.O_CREAT|os.O_RDWR,0o600);os.close(fd)
 db=sqlite3.connect(p);db.execute('PRAGMA synchronous=FULL')
 db.execute('CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY,dataset TEXT NOT NULL,database_name TEXT NOT NULL,kind TEXT NOT NULL,at INTEGER NOT NULL)')
 return db
def record(path,identity,dataset,database,kind):
 if kind not in KINDS or dataset not in ('synthetic','testnet-pilot'):raise ValueError('Invalid category')
 if not 1<=len(identity)<=128 or not 1<=len(database)<=63:raise ValueError('Use short opaque evidence identifiers')
 with open_ledger(path) as db:
  old=db.execute('SELECT dataset,database_name,kind FROM events WHERE id=?',(identity,)).fetchone()
  if old:
   if old!=(dataset,database,kind):raise ValueError('Evidence identity already binds a different event')
   return False
  db.execute('INSERT INTO events VALUES(?,?,?,?,?)',(identity,dataset,database,kind,int(time.time())))
 return True
def counts(path,dataset,database):
 db=sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True)
 try:return dict(db.execute('SELECT kind,count(*) FROM events WHERE dataset=? AND database_name=? GROUP BY kind',(dataset,database)).fetchall())
 finally:db.close()
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--ledger',required=True);p.add_argument('--event-id',required=True);p.add_argument('--dataset',choices=['synthetic','testnet-pilot'],required=True);p.add_argument('--database',required=True);p.add_argument('--kind',choices=KINDS,required=True);a=p.parse_args()
 print(json.dumps({'new_event':record(a.ledger,a.event_id,a.dataset,a.database,a.kind)}))
