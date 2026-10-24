"""Authenticated, version-pinned x402 seller; no public management endpoints."""
import base64,hashlib,json,re,subprocess,time
from http.server import BaseHTTPRequestHandler,HTTPServer
from pathlib import Path
from core import Vault,Denied,Conflict,canonical
NETWORK='eip155:84532'
TOKEN='0x036CbD53842c5426634e7929541eC2318f3dCF7e'

def header(value):return base64.b64encode(canonical(value)).decode()

class Provider:
    def __init__(self,script=None):self.script=script or str(Path(__file__).resolve().parents[1]/'x402/seller_bridge.mjs')
    def call(self,operation,**values):
        try:
            p=subprocess.run(['node',self.script],input=json.dumps(dict(operation=operation,**values)),text=True,capture_output=True,timeout=65)
            value=json.loads(p.stdout)
            if p.returncode or value.get('error'):raise Denied('Provider unavailable or invalid payment')
            return value
        except (ValueError,subprocess.TimeoutExpired):raise Denied('Provider unavailable') from None

class Seller:
    def __init__(self,vault,provider,origin='http://127.0.0.1:8096'):
        self.vault,self.provider,self.origin=vault,provider,origin.rstrip('/')
    def requirements(self,v):
        return dict(scheme='exact',network=NETWORK,asset=TOKEN,amount=v['price'],payTo=v['pay_to'],maxTimeoutSeconds=3600,extra=dict(name='USDC',version='2'))
    def handle(self,identity,token,signature=None):
        # Access precedes even 402; paying never creates a data grant.
        v,b,until=self.vault.authorize(identity,token)
        url=f'{self.origin}/resources/{identity}'
        requirements=self.requirements(v)
        resource=dict(url=url,description='Approved immutable document snapshot',mimeType='application/octet-stream')
        if not signature:
            return 402,{'PAYMENT-REQUIRED':header(dict(x402Version=2,resource=resource,accepts=[requirements],extensions={'chainsql':{'version':v['version'],'accessUntil':until}}))},b'Payment required for authorized version'
        try:
            if len(signature)>16384:raise ValueError()
            payload=json.loads(base64.b64decode(signature,validate=True))
            a=payload['payload']['authorization']
            if not re.fullmatch(r'0x[0-9a-fA-F]{64}',a['nonce']):raise ValueError()
            if a['from'].lower()!=b['wallet']:raise ValueError()
            key=hashlib.sha256(canonical([NETWORK,TOKEN.lower(),a['from'].lower(),a['nonce'].lower()])).hexdigest()
        except (ValueError,KeyError,TypeError):raise Denied('Invalid payment identity') from None
        old=self.vault.order(key)
        # Full signature/domain/resource/price validation also applies to cached requests.
        self.provider.call('validate',payload=payload,requirements=requirements,resource=resource,wallet=b['wallet'],until=until,replay=bool(old))
        if not old:
            block=self.provider.call('verify',payload=payload,requirements=requirements)['block']
        else:block=old['from_block']
        order=self.vault.prepare(key,identity,b['id'],payload,block)
        if order['state']!='paid':
            try:observation=self.provider.call('observe',payload=payload,fromBlock=order['from_block'])
            except Denied:return 202,{},b'Observation unavailable; reconcile original payment'
            if observation.get('transaction') and not observation.get('pending'):
                self.vault.paid(key,observation)
            elif observation.get('pending'):
                return 202,{},b'Original payment is awaiting observation'
            else:
                self.vault.authorize(identity,token)
                if order['state']=='prepared' and int(a['validBefore'])<=int(time.time()):
                    return 202,{},b'Original authorization expired; reconcile without a new payment'
                if self.vault.claim_dispatch(key):
                    try:
                        self.provider.call('settle',payload=payload,requirements=requirements)
                        observation=self.provider.call('observe',payload=payload,fromBlock=order['from_block'])
                        if observation.get('transaction') and not observation.get('pending'):self.vault.paid(key,observation)
                    except Denied:pass  # uncertain transmission stays durable, never fresh payment
                if self.vault.order(key)['state']!='paid':return 202,{},b'Reconcile the original payment; do not pay again'
        self.vault.authorize(identity,token)  # revoke/expire can also deny a previously paid replay
        receipt=json.loads(self.vault.order(key)['receipt'])
        response=dict(success=True,transaction=receipt['transaction'],network=NETWORK,payer=b['wallet'])
        return 200,{'PAYMENT-RESPONSE':header(response),'X-ChainSQL-Version':v['version']},self.vault.bytes(identity)

def route_factory(seller):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_GET(self):
            try:
                if not re.fullmatch(r'/resources/[0-9a-f-]{36}',self.path):raise Denied('Resource unavailable')
                auth=self.headers.get('Authorization','')
                if not auth.startswith('Bearer ') or not 1<=len(auth[7:])<=200:raise Denied('Resource unavailable')
                status,headers,body=seller.handle(self.path.rsplit('/',1)[1],auth[7:],self.headers.get('PAYMENT-SIGNATURE'))
            except Denied:status,headers,body=404,{},b'Resource unavailable or payment verification pending'
            except Conflict:status,headers,body=409,{},b'Payment identity conflict; do not pay again'
            except Exception:status,headers,body=503,{},b'Unavailable; reconcile the original payment'
            self.send_response(status)
            for k,v in headers.items():self.send_header(k,v)
            self.send_header('Content-Type','application/octet-stream' if status==200 else 'text/plain')
            self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.send_header('Content-Length',str(len(body)))
            self.end_headers();self.wfile.write(body)
    return Handler

def main():
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--directory',required=True);p.add_argument('--key-file',required=True);p.add_argument('--port',type=int,default=8096);a=p.parse_args()
    vault=Vault(a.directory,Path(a.key_file).read_bytes())
    HTTPServer(('127.0.0.1',a.port),route_factory(Seller(vault,Provider(),f'http://127.0.0.1:{a.port}'))).serve_forever()
if __name__=='__main__':main()
