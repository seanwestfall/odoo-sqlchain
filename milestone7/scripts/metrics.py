"""Operator-only aggregate exporter. Never expose its admin DSN as an agent tool."""
import argparse,json,os,subprocess
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--database',default='chainsql_release');p.add_argument('--dataset',choices=['synthetic','testnet-pilot'],required=True);p.add_argument('--output',required=True);p.add_argument('--event-ledger');a=p.parse_args()
ROOT=Path(__file__).resolve().parents[2];PG=Path(os.environ.get('PG_BIN','/opt/homebrew/opt/postgresql@16/bin'))
q="""BEGIN READ ONLY;
SELECT json_build_object(
 'postgres_version',current_setting('server_version'),
 'extension_version',(SELECT extversion FROM pg_extension WHERE extname='chainsql'),
 'paused',(SELECT paused FROM chainsql.execution_gate),
 'arc_enabled',(SELECT enabled FROM chainsql.arc_gate),
 'operations_by_state',(SELECT coalesce(json_agg(r),'[]') FROM (SELECT snapshot->>'network' AS network,state,count(*) AS count FROM chainsql.transfers GROUP BY 1,2) r),
 'uncertain_operation_count',(SELECT count(*) FROM chainsql.transfers WHERE state IN ('dispatched','reconciliation')),
 'oldest_queued_seconds',(SELECT extract(epoch FROM now()-min(created_at)) FROM chainsql.transfers WHERE state='requested'),
 'mean_queue_to_first_claim_seconds',(SELECT avg(extract(epoch FROM claimed-created_at)) FROM (SELECT t.created_at,min(a.at) AS claimed FROM chainsql.transfers t JOIN chainsql.transfer_audit a ON a.transfer_id=t.id AND a.event='budget reserved and fenced owner claimed' GROUP BY t.id) q),
 'reservations',(SELECT coalesce(json_agg(r),'[]') FROM (SELECT u.network,u.interface,sum(b.value_reserved)::text AS amount_atomic,sum(b.fee_reserved)::text AS fee_atomic FROM chainsql.transfer_budgets b LEFT JOIN chainsql.tenant_units u USING(tenant) WHERE b.scope='*' GROUP BY 1,2) r),
 'mean_dispatch_to_observation_seconds',(SELECT avg(extract(epoch FROM a.at-t.dispatched_at)) FROM chainsql.transfers t JOIN chainsql.transfer_audit a ON a.transfer_id=t.id WHERE a.event='reserved value and actual fee converted to observed spend'),
 'resource_delivery_failures',(SELECT count(*) FROM chainsql.resource_results WHERE delivery_state='failed'),
 'resource_delivery_pending',(SELECT count(*) FROM chainsql.resource_results WHERE delivery_state='pending'),
 'resources_delivered',(SELECT count(*) FROM chainsql.resource_results WHERE delivery_state='delivered'),
 'mock_results',(SELECT count(*) FROM chainsql.operations WHERE state='observed'));
COMMIT;
"""
cmd=[str(PG/'psql'),'-XqAt','-v','ON_ERROR_STOP=1','-h',str(ROOT/'.local/release/socket'),'-p','55437','-U','m0_admin','-d',a.database]
report=json.loads(subprocess.check_output(cmd,input=q,text=True))
report.update(dataset=a.dataset,real_revenue=None,duplicate_suppression_count=None,human_interventions=None,real_users_verified=0,notes=['Atomic values grouped by network/interface; company totals only to avoid double-counting wallet reservations.','Duplicate attempts and human interventions are not yet persistently counted; null does not mean zero.','Observed synthetic results are not settlement. Test USDC is not revenue.','No genuine business pilot has been supplied.'])
report['useful_work_completed']=None
if a.event_ledger:
 from events import counts
 event_counts=counts(a.event_ledger,a.dataset,a.database)
 report.update(duplicate_suppression_count=event_counts.get('duplicate_suppressed',0),human_interventions=event_counts.get('human_intervention',0),useful_work_completed=event_counts.get('useful_work_completed',0),event_measurement_source='operator-attested ledger; not automatic instrumentation')
 report['notes'][1]='Event counters cover only explicit operator-attested entries in the selected dataset/database; absence does not prove no unrecorded events.'
Path(a.output).write_text(json.dumps(report,indent=2)+'\n');print('Aggregate metrics written; no customer identifiers or authorization material exported.')
