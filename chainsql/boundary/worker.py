#!/usr/bin/env python3
"""One ordinary worker command. This process has no policy, signing or encryption keys."""
import argparse
from contextlib import closing
import json
from pathlib import Path
import urllib.request
import psycopg2
import uuid

parser=argparse.ArgumentParser()
parser.add_argument('operation_id', type=uuid.UUID)
parser.add_argument('--config',default='/run/boundary/worker.json')
parser.add_argument('--boundary-url',default='http://transfer-boundary:8091')
parser.add_argument('--reconcile',action='store_true')
args=parser.parse_args()
request={'operation_id':str(args.operation_id)}
if not args.reconcile:
    with closing(psycopg2.connect(**json.loads(Path(args.config).read_text()))) as conn:
        with conn:
            with conn.cursor() as cur:
                cur.execute('SELECT * FROM chainsql.claim_transfer_v1(%s)',(str(args.operation_id),))
                _,token,fence,_=cur.fetchone()
                request.update(claim_token=str(token),fence=fence)
route='/reconcile' if args.reconcile else '/execute'
try:
    req=urllib.request.Request(args.boundary_url+route, data=json.dumps(request).encode(),headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=20) as response:
        print(response.read().decode())
except Exception:
    raise SystemExit('Boundary command did not complete. Preserve the reservation and reconcile; do not create a new attempt.')
