"""Portable exact-byte proof format. JSON serialization is never the document hash."""
import hashlib, hmac, os
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
DOMAIN = b'ChainSQL/document-commitment/v1\x00'

def digest(data):
    if not isinstance(data, bytes): raise TypeError('Exact bytes required')
    return hashlib.sha256(data).hexdigest()

def commitment(data, salt):
    if len(salt)!=32: raise ValueError('A 32-byte random salt is required')
    return hashlib.sha256(DOMAIN+salt+hashlib.sha256(data).digest()).hexdigest()

def verify(data, expected_digest, salt, expected_commitment):
    return hmac.compare_digest(digest(data),expected_digest) and hmac.compare_digest(commitment(data,salt),expected_commitment)

def seal(key, data, identity):
    nonce=os.urandom(12)
    return nonce+AESGCM(key).encrypt(nonce,data,identity.encode())

def unseal(key, blob, identity):
    return AESGCM(key).decrypt(blob[:12],blob[12:],identity.encode())
