"""Restricted resource executor. No endpoint, price or signing input from workers.
Secrets stay in this process. File locks and the independent encrypted journal
survive DB rollback/restore; backups must preserve this directory separately.
"""
import base64,fcntl,hashlib,json,os,subprocess
from pathlib import Path
from contextlib import closing
import psycopg2
from psycopg2.extras import Json
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

class BoundaryError(Exception):pass

def canonical(v):return json.dumps(v,sort_keys=True,separators=(',',':')).encode()
class ResourceController:
    def __init__(self,config,provider=None):
        self.config=config;self.cipher=AESGCM(base64.b64decode(config['encryption_key']))
        self.directory=Path(config['journal_directory']);self.directory.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.provider=provider or self.node
    def call(self,sql,args=(),role='signer'):
        with closing(psycopg2.connect(**self.config[role])) as conn:
            with conn:
                with conn.cursor() as cur:
                    cur.execute(sql,args);return cur.fetchone() if cur.description else None
    def node(self,op,s,r,fp,a=None):
        data=dict(operation=op,snapshot=s,request=r,fingerprint=fp,authorization=a)
        try:
            p=subprocess.run([self.config['node'],'--env-file='+self.config['env_file'],self.config['script']],input=json.dumps(data),text=True,capture_output=True,timeout=65)
            result=json.loads(p.stdout)
            if p.returncode or 'error' in result:raise BoundaryError(result.get('error','provider_unavailable'))
            return result
        except BoundaryError:raise
        except Exception:raise BoundaryError('provider_unavailable') from None
    def save(self,path,v):
        tmp=path.with_suffix('.tmp');fd=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
        with os.fdopen(fd,'w') as f:json.dump(v,f);f.flush();os.fsync(f.fileno())
        os.replace(tmp,path);fd=os.open(path.parent,os.O_RDONLY)
        try:os.fsync(fd)
        finally:os.close(fd)
    def decrypt(self,blob,digest,tid):
        blob=bytes(blob);plain=self.cipher.decrypt(blob[:12],blob[12:],tid.encode())
        if hashlib.sha256(plain).hexdigest()!=digest:raise BoundaryError('journal_integrity')
        return json.loads(plain)
    def run(self,tid,token=None,fence=None,reconcile_only=False):
        row=self.call('SELECT * FROM chainsql.resource_material_v1(%s)',(tid,))
        if not row:raise BoundaryError('not_a_resource_purchase')
        s,r,fp,blob,digest=row
        if s['tenant']!=self.config['tenant'] or s['network']!='eip155:84532':raise BoundaryError('wrong_tenant_or_network')
        key=hashlib.sha256(canonical([s['tenant'],s['business_reference']])).hexdigest()
        path=self.directory/(key+'.json')
        fd=os.open(self.directory/(key+'.lock'),os.O_CREAT|os.O_RDWR,0o600)
        with os.fdopen(fd,'w') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            record=json.loads(path.read_text()) if path.exists() else None
            if record and (record['transfer_id']!=tid or record['fingerprint']!=fp):raise BoundaryError('restore_conflict_reconcile_existing_purchase')
            if not record:
                if blob or reconcile_only:raise BoundaryError('missing_independent_journal')
                record={'transfer_id':tid,'fingerprint':fp,'snapshot':s,'request':r}
                self.save(path,record)  # intent before contacting any signer
            if not blob:
                if reconcile_only:raise BoundaryError('authorization_missing_in_database_restore_review')
                self.call('SELECT * FROM chainsql.signing_material_v1(%s,%s,%s)',(tid,token,fence))
                if not record.get('ciphertext'):
                    challenge=self.provider('challenge',s,r,fp)
                    # Repeat fencing immediately before calling the signer.
                    self.call('SELECT * FROM chainsql.signing_material_v1(%s,%s,%s)',(tid,token,fence))
                    auth=self.provider('sign',s,r,fp)
                    self.provider('validate',s,r,fp,auth)
                    plain=canonical(auth);digest=hashlib.sha256(plain).hexdigest();nonce=os.urandom(12)
                    blob=nonce+self.cipher.encrypt(nonce,plain,tid.encode())
                    record.update(ciphertext=base64.b64encode(blob).decode(),digest=digest,challenge=challenge)
                    self.save(path,record)
                blob=base64.b64decode(record['ciphertext']);digest=record['digest']
                self.call('SELECT chainsql.save_authorization_v1(%s,%s,%s,%s,%s)',(tid,token,fence,psycopg2.Binary(blob),digest))
            if record.get('digest')!=digest:raise BoundaryError('journal_database_mismatch')
            auth=self.decrypt(blob,digest,tid);self.provider('validate',s,r,fp,auth)
            if not reconcile_only and not record.get('delivery'):
                # SQL rechecks revocation/pause/wallet, fence and committed authorization.
                self.call('SELECT * FROM chainsql.dispatch_transfer_v1(%s,%s,%s)',(tid,token,fence))
                record['dispatch_intent']=True;self.save(path,record)
                try:
                    outcome=self.provider('purchase',s,r,fp,auth)
                    record['last_outcome']=outcome
                    if outcome.get('settlement',{}).get('success'):record['transaction']=outcome['settlement']['transaction']
                    if outcome.get('delivery'):record['delivery']=outcome['delivery']
                    self.save(path,record)
                except BoundaryError:
                    # Timeout/rejected challenge never authorizes a new nonce or releases funds.
                    record['last_error']='request_failed_or_outcome_uncertain';self.save(path,record)
            try:observation=self.provider('observe',s,r,fp,dict(auth,transaction=record.get('transaction')))
            except BoundaryError:observation={'pending':True,'reason':'provider_unavailable_reconcile_original_authorization'}
            confirmed=not observation.get('pending',False) and bool(observation.get('transaction'))
            if confirmed and not record.get('delivery'):
                try:
                    delivered=self.provider('redeliver',s,r,fp,dict(auth,transaction=observation['transaction']))
                    if delivered.get('delivery'):
                        record.update(delivery=delivered['delivery'],transaction=observation['transaction']);self.save(path,record)
                except BoundaryError:pass
            evidence=dict(observation,fingerprint=fp,payment_state='confirmed' if confirmed else 'pending',delivery_state='delivered' if confirmed and record.get('delivery') else 'pending',request_http_status=record.get('challenge',{}).get('httpStatus'),demonstration=True)
            self.call('SELECT chainsql.record_resource_v1(%s,%s,%s)',(tid,Json(evidence),Json(record.get('delivery')) if confirmed else None),'observer')
            return evidence
