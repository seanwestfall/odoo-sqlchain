\set ON_ERROR_STOP on
-- Run as this disposable cluster's administrator, after PGXS make install.
BEGIN;
SELECT format('GRANT CREATE ON DATABASE %I TO chainsql_owner', current_database()) \gexec
SET LOCAL ROLE chainsql_owner;
CREATE EXTENSION IF NOT EXISTS chainsql VERSION '0.1.0';
RESET ROLE;
SELECT format('REVOKE CREATE ON DATABASE %I FROM chainsql_owner', current_database()) \gexec
GRANT USAGE ON SCHEMA chainsql TO chainsql_odoo, chainsql_worker;
GRANT EXECUTE ON FUNCTION chainsql.enqueue_probe(jsonb, text), chainsql.probe_status(uuid)
    TO chainsql_odoo;
GRANT EXECUTE ON FUNCTION chainsql.claim_probe(), chainsql.complete_probe(uuid, uuid, jsonb)
    TO chainsql_worker;
COMMIT;
