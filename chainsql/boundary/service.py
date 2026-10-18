#!/usr/bin/env python3
"""Private container-network API. Never accepts raw signing material or policy edits."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import uuid
from signer import RestrictedSigner, reconcile

signer = RestrictedSigner(json.loads(Path('/run/boundary/signer.json').read_text()))
observer = json.loads(Path('/run/boundary/observer.json').read_text())

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # Do not log request bodies, SQL parameters, authorizations, or credentials.

    def do_POST(self):
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 1024:
                raise ValueError('invalid request size')
            request = json.loads(self.rfile.read(length))
            operation_id = str(uuid.UUID(request['operation_id']))
            if self.path == '/execute' and set(request) == {'operation_id', 'claim_token', 'fence'}:
                token = str(uuid.UUID(request['claim_token']))
                fence = request['fence']
                if type(fence) is not int or fence <= 0:
                    raise ValueError('invalid fence')
                receipt = signer.execute(operation_id, token, fence)
                state = reconcile(observer, operation_id)
                result = {'state': state, 'receipt': receipt}
            elif self.path == '/reconcile' and set(request) == {'operation_id'}:
                result = {'state': reconcile(observer, operation_id)}
            else:
                raise ValueError('unsupported command')
            status = 200
        except Exception:
            # Details remain available as sanitized SQL status/audit, never secret-bearing tracebacks.
            status, result = 409, {'error': 'Boundary refused this command; inspect status and controls.'}
        body = json.dumps(result).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

ThreadingHTTPServer(('0.0.0.0', 8091), Handler).serve_forever()
