"""Private version vault and seller journal. Trusted operator writes configuration.
The HTTP process exposes only authenticated purchases, never these admin methods.
"""
import base64,hashlib,importlib.util,json,os,secrets,sqlite3,time,uuid
from pathlib import Path
spec=importlib.util.spec_from_file_location('document_proof',Path(__file__).resolve().parents[1]/'odoo_addons/chainsql_document_account/proof.py')
proof=importlib.util.module_from_spec(spec);spec.loader.exec_module(proof)
canonical=lambda value:json.dumps(value,sort_keys=True,separators=(',',':')).encode()

class Denied(Exception):pass
class Conflict(Exception):pass

class Vault:
    def __init__(self, directory, key):
        self.directory=Path(directory);self.directory.mkdir(mode=0o700,parents=True,exist_ok=True)
        self.key=key
        if len(key)!=32:raise ValueError('AES-256 key required')
        path=self.directory/'seller.sqlite3'
        self.db=sqlite3.connect(path,timeout=10,isolation_level=None)
        self.db.row_factory=sqlite3.Row
        path.chmod(0o600)
        self.db.executescript('''PRAGMA journal_mode=WAL; PRAGMA synchronous=FULL; PRAGMA foreign_keys=ON;
        CREATE TABLE IF NOT EXISTS versions(id TEXT PRIMARY KEY,company TEXT NOT NULL,source TEXT NOT NULL,version TEXT NOT NULL,sha256 TEXT NOT NULL,commitment TEXT NOT NULL,blob BLOB,retain_until INTEGER NOT NULL,approved_by TEXT,price TEXT NOT NULL,pay_to TEXT NOT NULL,UNIQUE(company,source,version));
        CREATE TABLE IF NOT EXISTS buyers(id TEXT PRIMARY KEY,token_hash TEXT UNIQUE NOT NULL,wallet TEXT NOT NULL,active INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS grants(version_id TEXT REFERENCES versions(id),buyer_id TEXT REFERENCES buyers(id),until_time INTEGER NOT NULL,PRIMARY KEY(version_id,buyer_id));
        CREATE TABLE IF NOT EXISTS orders(payment_key TEXT PRIMARY KEY,version_id TEXT REFERENCES versions(id),buyer_id TEXT REFERENCES buyers(id),payload_hash TEXT NOT NULL,payload BLOB NOT NULL,state TEXT NOT NULL CHECK(state IN ('prepared','uncertain','paid')),from_block TEXT NOT NULL,receipt TEXT,created_at INTEGER NOT NULL);
        ''')
    def close(self):self.db.close()
    def publish(self, company, source, version, data, retain_until, approved_by, price, pay_to, salt=None):
        if not approved_by or retain_until<=int(time.time()) or not str(price).isdigit() or int(price)<=0:raise Denied('An approved version and valid retention/price are required')
        if len(data)>1024*1024:raise Denied('Pilot documents are limited to 1 MiB')
        identity=str(uuid.uuid4());salt=os.urandom(32) if salt is None else salt
        if len(salt)!=32:raise ValueError('32-byte salt required')
        blob=proof.seal(self.key,salt+data,identity)
        self.db.execute('INSERT INTO versions VALUES(?,?,?,?,?,?,?,?,?,?,?)',(identity,company,source,version,proof.digest(data),proof.commitment(data,salt),blob,retain_until,approved_by,str(price),pay_to))
        return identity
    def buyer(self, identity, wallet):
        token=secrets.token_urlsafe(32)
        self.db.execute('INSERT INTO buyers VALUES(?,?,?,1)',(identity,hashlib.sha256(token.encode()).hexdigest(),wallet.lower()))
        return token
    def grant(self, version, buyer, until):
        v=self.version(version)
        if until>v['retain_until']:raise Denied('Grant exceeds retained version lifetime')
        self.db.execute('INSERT OR REPLACE INTO grants VALUES(?,?,?)',(version,buyer,until))
    def revoke(self, version, buyer):self.db.execute('DELETE FROM grants WHERE version_id=? AND buyer_id=?',(version,buyer))
    def version(self, identity):
        r=self.db.execute('SELECT * FROM versions WHERE id=?',(identity,)).fetchone()
        if not r:raise Denied('Resource unavailable')
        return dict(r)
    def authorize(self, identity, token):
        now=int(time.time());v=self.version(identity)
        b=self.db.execute('SELECT * FROM buyers WHERE token_hash=? AND active=1',(hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
        if not b or v['blob'] is None or v['retain_until']<=now:raise Denied('Resource unavailable')
        g=self.db.execute('SELECT until_time FROM grants WHERE version_id=? AND buyer_id=?',(identity,b['id'])).fetchone()
        if not g or g[0]<=now:raise Denied('Resource unavailable')
        return v,dict(b),min(v['retain_until'],g[0])
    def bytes(self, identity):
        v=self.version(identity)
        if not v['blob'] or v['retain_until']<=time.time():raise Denied('Retained content unavailable')
        plain=proof.unseal(self.key,v['blob'],identity);salt,data=plain[:32],plain[32:]
        if not proof.verify(data,v['sha256'],salt,v['commitment']):raise Denied('Document integrity failure')
        return data
    def manifest(self, identity):
        v=self.version(identity);plain=proof.unseal(self.key,v['blob'],identity)
        return dict(format='chainsql-document-v1',id=identity,version=v['version'],sha256=v['sha256'],salt=plain[:32].hex(),commitment=v['commitment'])
    def purge(self, identity, now=None):
        now=int(time.time()) if now is None else now;v=self.version(identity)
        if now<v['retain_until']:raise Denied('Retention has not elapsed')
        if self.db.execute("SELECT 1 FROM orders WHERE version_id=? AND state!='paid'",(identity,)).fetchone():raise Denied('Uncertain settlement requires review before purge')
        self.db.execute('UPDATE versions SET blob=NULL WHERE id=?',(identity,))
    def order(self,key):
        row=self.db.execute('SELECT * FROM orders WHERE payment_key=?',(key,)).fetchone()
        return dict(row) if row else None
    def prepare(self,key,version,buyer,payload,from_block):
        digest=hashlib.sha256(canonical(payload)).hexdigest()
        self.db.execute('BEGIN IMMEDIATE')
        try:
            old=self.order(key)
            if old:
                if (old['version_id'],old['buyer_id'],old['payload_hash'])!=(version,buyer,digest):raise Conflict('Payment identity is already bound to another request')
            else:self.db.execute('INSERT INTO orders VALUES(?,?,?,?,?,?,?,?,?)',(key,version,buyer,digest,proof.seal(self.key,canonical(payload),key),'prepared',str(from_block),None,int(time.time())))
            self.db.execute('COMMIT')
        except BaseException:self.db.execute('ROLLBACK');raise
        return self.order(key)
    def claim_dispatch(self,key):
        # Atomic durable transition; only its winner may transmit. A crash needs observation,
        # never a fresh authorization or an automatic second settle call.
        return self.db.execute("UPDATE orders SET state='uncertain' WHERE payment_key=? AND state='prepared'",(key,)).rowcount==1
    def paid(self,key,receipt):
        self.db.execute("UPDATE orders SET state='paid',receipt=? WHERE payment_key=?",(json.dumps(receipt),key))
