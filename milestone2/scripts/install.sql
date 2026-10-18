\set ON_ERROR_STOP on
BEGIN;
SET LOCAL ROLE chainsql_owner;
ALTER EXTENSION chainsql UPDATE TO '0.2.1';
RESET ROLE;
GRANT USAGE ON SCHEMA chainsql TO chainsql_odoo,chainsql_worker,chainsql_signer,chainsql_observer,chainsql_policy;
GRANT EXECUTE ON FUNCTION chainsql.request_transfer_v1(uuid,jsonb,text),
 chainsql.approved_transfer_v1(text,text),chainsql.invalidate_business_v1(text,text),
 chainsql.cancel_transfer_v1(uuid),chainsql.transfer_status_v1(uuid) TO chainsql_odoo;
GRANT EXECUTE ON FUNCTION chainsql.claim_transfer_v1(uuid) TO chainsql_worker;
GRANT EXECUTE ON FUNCTION chainsql.signing_material_v1(uuid,uuid,bigint),
 chainsql.save_authorization_v1(uuid,uuid,bigint,bytea,text),
 chainsql.dispatch_transfer_v1(uuid,uuid,bigint),
 chainsql.accept_mock_transfer_v1(uuid,uuid,bigint,text) TO chainsql_signer;
GRANT EXECUTE ON FUNCTION chainsql.reconcile_transfer_v1(uuid) TO chainsql_observer;
GRANT EXECUTE ON FUNCTION chainsql.set_pause_v1(boolean),
 chainsql.set_budget_v1(text,text,numeric,numeric,numeric,numeric),
 chainsql.set_wallet_v1(text,text,name,boolean),chainsql.approve_transfer_v1(jsonb),
 chainsql.revoke_approval_v1(uuid) TO chainsql_policy;
-- Preserve the Milestone 1 API grants across the upgrade.
GRANT EXECUTE ON FUNCTION chainsql.enqueue_probe(jsonb,text),chainsql.probe_status(uuid) TO chainsql_odoo;
GRANT EXECUTE ON FUNCTION chainsql.claim_probe(),chainsql.complete_probe(uuid,uuid,jsonb) TO chainsql_worker;
COMMIT;
