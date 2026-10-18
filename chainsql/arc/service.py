#!/usr/bin/env python3
"""Loopback trusted Arc boundary. Delegated workers supply IDs and fenced claims only."""
import argparse
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
from pathlib import Path
import uuid
from controller import ArcController,NodeProvider

p=argparse.ArgumentParser();p.add_argument('--config',required=True);p.add_argument('--recover',action='store_true');args=p.parse_args()
conf=json.loads(Path(args.config).read_text())
controller=ArcController(conf['signer'],conf['observer'],NodeProvider(conf['node'],conf['script'],conf['env_file']),conf['journal_directory'],conf['tenant'])
if args.recover:
    print(json.dumps(controller.recover()));raise SystemExit(0)
class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_POST(self):
        try:
            n=int(self.headers.get('Content-Length','0'))
            if not 0<n<=1024:raise ValueError()
            r=json.loads(self.rfile.read(n));tid=str(uuid.UUID(r['operation_id']))
            if self.path=='/execute' and set(r)=={'operation_id','claim_token','fence'}:
                token=str(uuid.UUID(r['claim_token']));fence=r['fence']
                if type(fence)!=int or fence<=0:raise ValueError()
                controller.prepare(tid,token,fence)
                submission=controller.submit(tid,token,fence)
                result={'submission':submission,'observation':controller.observe(tid)}
            elif self.path=='/reconcile' and set(r)=={'operation_id'}:result=controller.reconcile(tid)
            else:raise ValueError()
            status=200
        except Exception:
            status=409;result={'error':'Arc boundary could not complete the command. Reconcile the original operation; no replacement payment is authorized.'}
        body=json.dumps(result).encode();self.send_response(status);self.send_header('Content-Type','application/json')
        self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
ThreadingHTTPServer(('127.0.0.1',8092),Handler).serve_forever()
