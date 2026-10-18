"""Trusted Arc controller; delegated workers must not receive this process's credentials."""
import base64
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import subprocess
import psycopg2
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

class BoundaryError(Exception):pass

def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':')).encode()

class NodeProvider:
    def __init__(self,node,script,env_file):self.command=[node,'--env-file='+str(env_file),str(script)]
    def __call__(self,operation,snapshot,plan=None,authorization=None):
        try:
            result=subprocess.run(self.command,input=json.dumps(dict(operation=operation,snapshot=snapshot,plan=plan,authorization=authorization)),
                text=True,capture_output=True,timeout=90)
            value=json.loads(result.stdout)
        except Exception:raise BoundaryError('provider_unavailable') from None
        if result.returncode or 'error' in value:raise BoundaryError(value.get('error','provider_unavailable'))
        return value

class ArcController:
    def __init__(self,signer_config,observer_config,provider,journal_directory,allowed_tenant):
        self.signer=signer_config['database'];self.observer=observer_config['database']
        self.cipher=AESGCM(base64.b64decode(signer_config['encryption_key']))
        self.provider=provider;self.directory=Path(journal_directory);self.directory.mkdir(mode=0o700,parents=True,exist_ok=True)
        self.tenant=allowed_tenant
    def call(self,query,args=(),observer=False):
        with closing(psycopg2.connect(**(self.observer if observer else self.signer))) as conn:
            with conn:
                with conn.cursor() as cur:
                    cur.execute(query,args);return cur.fetchone()
    def check(self,snapshot):
        if snapshot['tenant']!=self.tenant or snapshot['network']!='eip155:5042002' or snapshot['interface']!='arc-erc20-6-fee18':
            raise BoundaryError('unapproved_network_or_tenant')
    def journal_path(self,s):
        # Independent of request revision/UUID so a restored database cannot issue
        # another payment for the same business obligation under a fresh identifier.
        key=hashlib.sha256(canonical([s['tenant'],s['business_reference']])).hexdigest()
        return self.directory/(key+'.json')
    def open_auth(self,blob,digest,tid):
        blob=bytes(blob);plain=self.cipher.decrypt(blob[:12],blob[12:],tid.encode())
        if hashlib.sha256(plain).hexdigest()!=digest:raise BoundaryError('authorization_integrity')
        return json.loads(plain)
    def write_once(self,path,record):
        try:
            fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        except FileExistsError:
            return json.loads(path.read_text())
        with os.fdopen(fd,'w') as f:json.dump(record,f);f.flush();os.fsync(f.fileno())
        directory=os.open(self.directory,os.O_RDONLY)
        try:os.fsync(directory)
        finally:os.close(directory)
        return record
    def prepare(self,tid,token,fence):
        s,_,ciphertext,digest,state=self.call('SELECT * FROM chainsql.signing_material_v1(%s,%s,%s)',(tid,token,fence))
        self.check(s);path=self.journal_path(s)
        saved=json.loads(path.read_text()) if path.exists() else None
        if saved and (saved['transfer_id']!=tid or saved['snapshot']!=s):
            raise BoundaryError('restore_or_obligation_conflict_reconcile_existing_attempt')
        if ciphertext is not None:
            row=self.call('SELECT * FROM chainsql.arc_recovery_material_v1(%s)',(tid,))
            if not row:raise BoundaryError('missing_arc_plan')
            _,plan,blob,digest=row
            auth=self.open_auth(blob,digest,tid);self.validate(s,plan,auth)
            if not saved:raise BoundaryError('missing_independent_dispatch_journal')
            return auth['txHash']
        if saved:
            plan=saved['plan'];blob=base64.b64decode(saved['ciphertext']);digest=saved['digest']
            auth=self.open_auth(blob,digest,tid)
            # No fresh nonce after restore. Recovery with missing plan requires operator review.
            self.validate(s,plan,auth)
            # The stored plan may exist even though the authorization save failed.
            hints={**plan,'pendingNonce':plan['nonce']}
        else:
            hints=self.provider('prepare',s)
        plan=self.call('SELECT chainsql.arc_plan_v1(%s,%s,%s,%s,%s,%s,%s,%s)',
            (tid,token,fence,hints['sender'].lower(),int(hints['pendingNonce']),hints['gas'],hints['maxFeePerGas'],hints['maxPriorityFeePerGas']))[0]
        if saved:
            if any(plan[k]!=saved['plan'][k] for k in ['sender','nonce','gas','maxFeePerGas','maxPriorityFeePerGas','providerRequestId']):
                raise BoundaryError('restored_plan_mismatch_reconcile_only')
        else:
            auth=self.provider('sign',s,plan)
            self.validate(s,plan,auth)
            plain=canonical(auth);digest=hashlib.sha256(plain).hexdigest();nonce=os.urandom(12)
            blob=nonce+self.cipher.encrypt(nonce,plain,tid.encode())
            saved=self.write_once(path,dict(transfer_id=tid,snapshot=s,plan=plan,digest=digest,ciphertext=base64.b64encode(blob).decode()))
            if saved['transfer_id']!=tid or saved['snapshot']!=s:raise BoundaryError('concurrent_obligation_conflict')
            blob=base64.b64decode(saved['ciphertext']);digest=saved['digest'];auth=self.open_auth(blob,digest,tid)
        self.call('SELECT chainsql.save_arc_authorization_v1(%s,%s,%s,%s,%s,%s)',
            (tid,token,fence,psycopg2.Binary(blob),digest,auth['txHash']))
        return auth['txHash']
    def validate(self,s,plan,auth):
        verified=self.provider('validate',s,plan,auth)
        if verified['txHash']!=auth['txHash'] or (plan.get('txHash') and plan['txHash']!=auth['txHash']):
            raise BoundaryError('authorization_hash_mismatch')
    def material(self,tid):
        row=self.call('SELECT * FROM chainsql.arc_recovery_material_v1(%s)',(tid,))
        if not row:raise BoundaryError('missing_original_authorization_recovery_required')
        s,plan,blob,digest=row;self.check(s)
        saved=json.loads(self.journal_path(s).read_text())
        if saved['transfer_id']!=tid or saved['snapshot']!=s:raise BoundaryError('restore_obligation_conflict')
        if saved['digest']!=digest or base64.b64decode(saved['ciphertext'])!=bytes(blob):
            raise BoundaryError('journal_authorization_mismatch')
        auth=self.open_auth(blob,digest,tid);self.validate(s,plan,auth)
        return s,plan,auth
    def submit(self,tid,token,fence):
        s,plan,auth=self.material(tid)
        # Commit the dispatch permit before any provider transmission.
        self.call('SELECT * FROM chainsql.dispatch_transfer_v1(%s,%s,%s)',(tid,token,fence))
        return self.provider('submit',s,plan,auth)
    def observe(self,tid):
        s,plan,auth=self.material(tid);result=self.provider('observe',s,plan,auth)
        if result['state'] in ('confirmed','reverted'):
            self.call('SELECT chainsql.record_arc_observation_v1(%s,%s::jsonb)',(tid,json.dumps(result)),observer=True)
        return result
    def reconcile(self,tid):return self.observe(tid)
    def recover(self):
        # Keep Arc disabled until every independent journal is reconciled. Missing DB
        # rows/plans or missing provider evidence block recovery; never allocate a nonce.
        results=[]
        for path in sorted(self.directory.glob('*.json')):
            saved=json.loads(path.read_text());result=self.reconcile(saved['transfer_id'])
            if result['state'] not in ('confirmed','reverted'):raise BoundaryError('restore_reconciliation_incomplete')
            results.append(result)
        return results
