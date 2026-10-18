\set ON_ERROR_STOP on
BEGIN;
SET LOCAL ROLE chainsql_owner;
ALTER EXTENSION chainsql UPDATE TO '0.3.0';
RESET ROLE;
GRANT EXECUTE ON FUNCTION chainsql.enable_arc_v1(boolean) TO chainsql_policy;
GRANT EXECUTE ON FUNCTION chainsql.arc_plan_v1(uuid,uuid,bigint,text,bigint,numeric,numeric,numeric),
 chainsql.save_arc_authorization_v1(uuid,uuid,bigint,bytea,text,text),
 chainsql.arc_recovery_material_v1(uuid) TO chainsql_signer;
GRANT EXECUTE ON FUNCTION chainsql.record_arc_observation_v1(uuid,jsonb) TO chainsql_observer;
COMMIT;
