#!/usr/bin/env python3
"""Operator-only, explicitly mock-only demo provisioning. Never mount in a worker."""
from contextlib import closing
from datetime import datetime,timedelta,timezone
import json
from pathlib import Path
import psycopg2
from psycopg2.extras import Json
ROOT=Path(__file__).resolve().parents[2]
conf=dict(host=str(ROOT/'.local/milestone0/socket'),port=55432,user='m0_admin',dbname='chainsql_m0')
with closing(psycopg2.connect(**conf)) as conn:
    with conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT o.id,o.company_id,o.move_id,o.revision,o.amount_atomic,o.recipient,o.network,o.asset
                FROM chainsql_operation o JOIN account_move m ON m.id=o.move_id
                WHERE m.ref='ChainSQL Milestone 1 demo' AND o.approval_outcome='approved'
                ORDER BY o.revision DESC LIMIT 1""")
            row=cur.fetchone()
            if not row:raise SystemExit('Prepare and approve the labelled Milestone 1 demo request first.')
            oid,company,bill,revision,amount,recipient,network,asset=row
            assert network=='mock:local' and asset=='USDC'
            tenant=f'odoo:chainsql_m0:{company}'
            business=f'account.move:{bill}'
            cur.execute('SELECT a.id FROM chainsql.transfer_heads h JOIN chainsql.transfer_approvals a ON a.id=h.approval_id WHERE h.tenant=%s AND h.business_reference=%s',(tenant,business))
            existing=cur.fetchone()
            if existing:
                print('Independent demo approval already exists; retained without changing controls.')
            else:
                cur.execute('SET LOCAL ROLE chainsql_policy')
                for scope in ['*','pilot-company-wallet']:
                    cur.execute('SELECT chainsql.set_budget_v1(%s,%s,100000000,100000,50000000,10000)',(tenant,scope))
                cur.execute('SELECT chainsql.set_wallet_v1(%s,%s,%s,true)',(tenant,'pilot-company-wallet','chainsql_odoo'))
                now=datetime.now(timezone.utc)
                s=dict(tenant=tenant,business_reference=business,request_revision=str(revision),source_wallet='pilot-company-wallet',
                    destination=recipient,network=network,asset=asset,interface='mock-usdc-6',amount_atomic=amount,
                    fee_ceiling_atomic='10000',policy_version='boundary-v1',approval_identity='mock-only-acceptance-harness',
                    valid_from=(now-timedelta(seconds=1)).isoformat().replace('+00:00','Z'),
                    valid_until=(now+timedelta(hours=12)).isoformat().replace('+00:00','Z'))
                cur.execute('SELECT chainsql.approve_transfer_v1(%s)',(Json(s),))
                aid=str(cur.fetchone()[0])
                cur.execute('SELECT chainsql.set_pause_v1(false)')
                print(json.dumps({'operation_id':oid,'bill_id':bill,'approval_id':aid,'network':'mock:local'}))
