#!/usr/bin/env python3
"""Separate restricted SQL role. Claim+completion commit together; a crash rolls both back."""
import argparse
from contextlib import closing
import json
import time
from pathlib import Path
import psycopg2
from psycopg2.extras import Json


def process_one(conn):
    with conn:
        with conn.cursor() as cur:
            cur.execute('SELECT id::text, payload, claim_token::text FROM chainsql.claim_probe()')
            row = cur.fetchone()
            if not row:
                return False
            operation_id, payload, token = row
            valid = (payload.get('mode') == 'mock-v1' and payload.get('network') == 'mock:local'
                     and payload.get('asset') == 'USDC' and payload.get('decimals') == 6
                     and isinstance(payload.get('amount_atomic'), str)
                     and payload['amount_atomic'].isdigit() and int(payload['amount_atomic']) > 0)
            result = dict(mode='mock-v1', operation_id=operation_id,
                          fingerprint=payload.get('fingerprint'), status='simulated' if valid else 'rejected',
                          receipt_reference='mock:' + operation_id, resource_purchases=[],
                          **{k: payload.get(k) for k in ['amount_atomic', 'recipient', 'network', 'asset']})
            cur.execute('SELECT chainsql.complete_probe(%s::uuid, %s::uuid, %s::jsonb)',
                        (operation_id, token, Json(result)))
    print('Observed mock operation ' + operation_id, flush=True)
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', default='/run/chainsql/worker.json')
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text())
    with closing(psycopg2.connect(**config)) as conn:
        while True:
            worked = process_one(conn)
            if args.once:
                return
            if not worked:
                time.sleep(1)

if __name__ == '__main__':
    main()
