"""Restricted pilot signer. No caller-selected bytes, amount, destination, or endpoint.

This key is ONLY a local simulator key, never an Arc/EVM private key. The simulator
and SQL authorization boundary enforce the same immutable preparation identity.
"""
import base64
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path

import psycopg2
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()


class RestrictedSigner:
    def __init__(self, config):
        self.database = config['database']
        self.key = Ed25519PrivateKey.from_private_bytes(base64.b64decode(config['signing_seed'], validate=True))
        self.cipher = AESGCM(base64.b64decode(config['encryption_key'], validate=True))

    def _call(self, sql, args):
        with closing(psycopg2.connect(**self.database)) as conn:
            with conn:
                with conn.cursor() as cur:
                    cur.execute(sql, args)
                    return cur.fetchone()

    def _open(self, ciphertext, digest, operation_id):
        encrypted = bytes(ciphertext)
        plaintext = self.cipher.decrypt(encrypted[:12], encrypted[12:], str(operation_id).encode())
        if hashlib.sha256(plaintext).hexdigest() != digest:
            raise ValueError('authorization integrity failure')
        auth = json.loads(plaintext)
        body = auth['body']
        self.key.public_key().verify(base64.b64decode(auth['signature'], validate=True), canonical(body))
        if body['preparation_id'] != 'transfer-v1:' + str(operation_id) or body['version'] != 'boundary-v1':
            raise ValueError('authorization identity failure')
        s = body['snapshot']
        if s['network'] != 'mock:local' or s['interface'] != 'mock-usdc-6' or s['asset'] != 'USDC':
            raise ValueError('live networks are disabled')
        return body

    def prepare(self, operation_id, token, fence):
        row = self._call('SELECT * FROM chainsql.signing_material_v1(%s,%s,%s)', (operation_id, token, fence))
        snapshot, preparation_id, ciphertext, digest, state = row
        if ciphertext is not None:
            body = self._open(ciphertext, digest, operation_id)
            if body['snapshot'] != snapshot:
                raise ValueError('authorization snapshot mismatch')
            return digest
        if state != 'reserved':
            raise ValueError('missing authorization for existing attempt')
        body = {'version': 'boundary-v1', 'preparation_id': preparation_id, 'snapshot': snapshot}
        signature = self.key.sign(canonical(body))
        plaintext = canonical({'body': body, 'signature': base64.b64encode(signature).decode()})
        digest = hashlib.sha256(plaintext).hexdigest()
        nonce = os.urandom(12)
        ciphertext = nonce + self.cipher.encrypt(nonce, plaintext, str(operation_id).encode())
        # A persistence failure escapes here. No dispatch path is called on failure.
        self._call('SELECT chainsql.save_authorization_v1(%s,%s,%s,%s,%s)',
                   (operation_id, token, fence, psycopg2.Binary(ciphertext), digest))
        return digest

    def dispatch(self, operation_id, token, fence):
        # The durable authorization must already exist in a DIFFERENT committed transaction.
        ciphertext, digest = self._call('SELECT * FROM chainsql.dispatch_transfer_v1(%s,%s,%s)',
                                        (operation_id, token, fence))
        self._open(ciphertext, digest, operation_id)
        # This is the simulator's authoritative acceptance boundary, not a public RPC.
        # There is no code path here for broadcasting to a live chain.
        return self._call('SELECT chainsql.accept_mock_transfer_v1(%s,%s,%s,%s)',
                          (operation_id, token, fence, digest))[0]

    def execute(self, operation_id, token, fence):
        self.prepare(operation_id, token, fence)
        return self.dispatch(operation_id, token, fence)


def reconcile(config, operation_id):
    with closing(psycopg2.connect(**config['database'])) as conn:
        with conn:
            with conn.cursor() as cur:
                cur.execute('SELECT chainsql.reconcile_transfer_v1(%s)', (operation_id,))
                return cur.fetchone()[0]
