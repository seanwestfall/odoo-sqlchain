\set ON_ERROR_STOP on
BEGIN;
SET LOCAL ROLE chainsql_owner;
ALTER EXTENSION chainsql UPDATE TO '0.4.0';
RESET ROLE;
GRANT EXECUTE ON FUNCTION chainsql.approve_resource_v1(jsonb,jsonb) TO chainsql_policy;
GRANT EXECUTE ON FUNCTION chainsql.approved_resource_v1(text,text),chainsql.request_resource_v1(uuid,jsonb,jsonb,text),chainsql.resource_status_v1(uuid) TO chainsql_odoo;
GRANT EXECUTE ON FUNCTION chainsql.resource_material_v1(uuid) TO chainsql_signer;
GRANT EXECUTE ON FUNCTION chainsql.record_resource_v1(uuid,jsonb,jsonb) TO chainsql_observer;
COMMIT;
