-- No network access, signing, or payment execution occurs in this extension.
CREATE TABLE chainsql.operations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    kind text NOT NULL DEFAULT 'probe' CHECK (kind = 'probe'),
    requested_by name NOT NULL,
    idempotency_key text NOT NULL CHECK (length(idempotency_key) BETWEEN 1 AND 128),
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    state text NOT NULL DEFAULT 'pending' CHECK (state IN ('pending', 'running', 'observed')),
    claim_token uuid,
    claimed_by name,
    result jsonb,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    completed_at timestamptz,
    UNIQUE (requested_by, idempotency_key),
    CHECK ((state = 'pending' AND claim_token IS NULL AND claimed_by IS NULL)
        OR (state IN ('running', 'observed') AND claim_token IS NOT NULL AND claimed_by IS NOT NULL)),
    CHECK ((state = 'observed' AND result IS NOT NULL AND completed_at IS NOT NULL)
        OR (state <> 'observed' AND result IS NULL AND completed_at IS NULL))
);
CREATE INDEX operations_pending ON chainsql.operations(created_at, id) WHERE state = 'pending';

-- Extension-owned runtime rows are otherwise omitted from ordinary pg_dump.
SELECT pg_catalog.pg_extension_config_dump('chainsql.operations', '');

CREATE FUNCTION chainsql.enqueue_probe(p_payload jsonb, p_key text) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE op chainsql.operations%ROWTYPE;
BEGIN
    IF p_payload IS NULL OR jsonb_typeof(p_payload) <> 'object'
       OR octet_length(p_payload::text) > 65536 THEN
        RAISE EXCEPTION 'probe payload must be an object of at most 64 KiB';
    END IF;
    INSERT INTO chainsql.operations(requested_by, idempotency_key, payload)
    VALUES (session_user, p_key, p_payload)
    ON CONFLICT (requested_by, idempotency_key) DO NOTHING
    RETURNING * INTO op;
    IF op.id IS NULL THEN
        SELECT * INTO STRICT op FROM chainsql.operations
        WHERE requested_by = session_user AND idempotency_key = p_key;
        IF op.payload IS DISTINCT FROM p_payload THEN
            RAISE EXCEPTION 'idempotency key already binds a different payload';
        END IF;
    END IF;
    RETURN op.id;
END $$;

CREATE FUNCTION chainsql.probe_status(p_id uuid)
RETURNS TABLE(id uuid, kind text, state text, payload jsonb, result jsonb)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
    SELECT id, kind, state, payload, result FROM chainsql.operations
    WHERE id = p_id AND requested_by = session_user;
$$;

CREATE FUNCTION chainsql.claim_probe()
RETURNS TABLE(id uuid, payload jsonb, claim_token uuid)
LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path = pg_catalog AS $$
    WITH candidate AS (
        SELECT id FROM chainsql.operations WHERE state = 'pending'
        ORDER BY created_at, id FOR UPDATE SKIP LOCKED LIMIT 1
    )
    UPDATE chainsql.operations op SET state = 'running',
        claim_token = gen_random_uuid(), claimed_by = session_user
    FROM candidate WHERE op.id = candidate.id
    RETURNING op.id, op.payload, op.claim_token;
$$;

CREATE FUNCTION chainsql.complete_probe(p_id uuid, p_token uuid, p_result jsonb)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
BEGIN
    IF p_result IS NULL OR jsonb_typeof(p_result) <> 'object'
       OR octet_length(p_result::text) > 65536 THEN
        RAISE EXCEPTION 'probe result must be an object of at most 64 KiB';
    END IF;
    UPDATE chainsql.operations SET state = 'observed', result = p_result,
        completed_at = clock_timestamp()
    WHERE id = p_id AND state = 'running' AND claim_token = p_token AND claimed_by = session_user;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'no matching active claim';
    END IF;
END $$;

REVOKE ALL ON SCHEMA chainsql FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA chainsql FROM PUBLIC;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA chainsql FROM PUBLIC;
