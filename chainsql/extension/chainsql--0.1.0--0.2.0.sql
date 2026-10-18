-- Transfer boundary v1. Every monetary quantity is an integer, never a float.
-- Network support is deliberately limited to an enforced local settlement simulator.
CREATE TABLE chainsql.execution_gate (
    singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton),
    paused boolean NOT NULL DEFAULT true
);
CREATE TABLE chainsql.transfer_budgets (
    tenant text NOT NULL, scope text NOT NULL,
    value_limit numeric(78,0) NOT NULL CHECK(value_limit >= 0),
    fee_limit numeric(78,0) NOT NULL CHECK(fee_limit >= 0),
    per_value numeric(78,0) NOT NULL CHECK(per_value >= 0),
    per_fee numeric(78,0) NOT NULL CHECK(per_fee >= 0),
    value_reserved numeric(78,0) NOT NULL DEFAULT 0 CHECK(value_reserved >= 0),
    fee_reserved numeric(78,0) NOT NULL DEFAULT 0 CHECK(fee_reserved >= 0),
    value_spent numeric(78,0) NOT NULL DEFAULT 0 CHECK(value_spent >= 0),
    fee_spent numeric(78,0) NOT NULL DEFAULT 0 CHECK(fee_spent >= 0),
    PRIMARY KEY(tenant,scope),
    CHECK(value_reserved + value_spent <= value_limit),
    CHECK(fee_reserved + fee_spent <= fee_limit)
);
CREATE TABLE chainsql.transfer_wallets (
    tenant text NOT NULL, source_wallet text NOT NULL CHECK(source_wallet <> '*'),
    app_role name NOT NULL, enabled boolean NOT NULL DEFAULT true,
    PRIMARY KEY(tenant,source_wallet)
);
CREATE TABLE chainsql.transfer_approvals (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), snapshot jsonb NOT NULL,
    tenant text NOT NULL, business_reference text NOT NULL, revision bigint NOT NULL,
    issued_by name NOT NULL, issued_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    revoked boolean NOT NULL DEFAULT false,
    UNIQUE(tenant,business_reference,revision)
);
CREATE TABLE chainsql.transfer_heads (
    tenant text NOT NULL, business_reference text NOT NULL,
    approval_id uuid NOT NULL REFERENCES chainsql.transfer_approvals(id),
    invalidated boolean NOT NULL DEFAULT false,
    -- One business obligation cannot acquire parallel payable revisions.
    active_transfer uuid,
    PRIMARY KEY(tenant,business_reference)
);
CREATE TABLE chainsql.transfers (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    approval_id uuid NOT NULL REFERENCES chainsql.transfer_approvals(id),
    snapshot jsonb NOT NULL, requested_by name NOT NULL,
    request_key text NOT NULL CHECK(length(request_key) BETWEEN 1 AND 128),
    state text NOT NULL DEFAULT 'requested' CHECK(state IN
        ('requested','reserved','prepared','dispatched','reconciliation','observed','cancelled')),
    reserved boolean NOT NULL DEFAULT false,
    fence bigint NOT NULL DEFAULT 0, claim_token uuid, lease_until timestamptz,
    claimed_by name, created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    dispatched_at timestamptz, reason text,
    UNIQUE(requested_by,request_key), UNIQUE(approval_id)
);
CREATE TABLE chainsql.transfer_authorizations (
    transfer_id uuid PRIMARY KEY REFERENCES chainsql.transfers(id),
    ciphertext bytea NOT NULL CHECK(octet_length(ciphertext) BETWEEN 64 AND 65536),
    digest text NOT NULL CHECK(digest ~ '^[a-f0-9]{64}$'),
    prepared_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    saved_xid bigint NOT NULL DEFAULT txid_current()
);
CREATE TABLE chainsql.mock_settlements (
    transfer_id uuid PRIMARY KEY REFERENCES chainsql.transfers(id),
    receipt text NOT NULL UNIQUE, fee_atomic numeric(78,0) NOT NULL CHECK(fee_atomic >= 0),
    settled_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE chainsql.transfer_audit (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    transfer_id uuid, event text NOT NULL, actor name NOT NULL DEFAULT session_user,
    at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE FUNCTION chainsql._gate_v1() RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
    -- Coarse serialization is intentional for this pilot: one lock order for all controls,
    -- reservations, claims and settlement transitions. No external I/O under this lock.
    INSERT INTO chainsql.execution_gate(singleton) VALUES(true) ON CONFLICT DO NOTHING;
    PERFORM 1 FROM chainsql.execution_gate WHERE singleton FOR UPDATE;
END $$;
CREATE FUNCTION chainsql._audit_v1(p_id uuid,p_event text) RETURNS void
LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog AS $$
    INSERT INTO chainsql.transfer_audit(transfer_id,event) VALUES(p_id,p_event);
$$;
CREATE FUNCTION chainsql.set_pause_v1(p_paused boolean) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
    PERFORM chainsql._gate_v1();
    UPDATE chainsql.execution_gate SET paused=p_paused;
    PERFORM chainsql._audit_v1(NULL,'execution pause changed');
END $$;
CREATE FUNCTION chainsql.set_budget_v1(p_tenant text,p_scope text,p_value numeric,p_fee numeric,p_per_value numeric,p_per_fee numeric)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
    PERFORM chainsql._gate_v1();
    IF p_value::text !~ '^[0-9]{1,38}$' OR p_fee::text !~ '^[0-9]{1,38}$' OR p_per_value::text !~ '^[0-9]{1,38}$' OR p_per_fee::text !~ '^[0-9]{1,38}$' THEN
        RAISE EXCEPTION 'budgets must be integer atomic units';
    END IF;
    INSERT INTO chainsql.transfer_budgets(tenant,scope,value_limit,fee_limit,per_value,per_fee)
      VALUES(p_tenant,p_scope,p_value,p_fee,p_per_value,p_per_fee)
    ON CONFLICT(tenant,scope) DO UPDATE SET value_limit=p_value,fee_limit=p_fee,per_value=p_per_value,per_fee=p_per_fee;
    -- Table checks prevent reducing limits below spent + outstanding reservations.
    PERFORM chainsql._audit_v1(NULL,'budget limits changed');
END $$;
CREATE FUNCTION chainsql.set_wallet_v1(p_tenant text,p_wallet text,p_app name,p_enabled boolean)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
    PERFORM chainsql._gate_v1();
    INSERT INTO chainsql.transfer_wallets(tenant,source_wallet,app_role,enabled)
    VALUES(p_tenant,p_wallet,p_app,p_enabled)
    ON CONFLICT(tenant,source_wallet) DO UPDATE SET app_role=p_app,enabled=p_enabled;
    PERFORM chainsql._audit_v1(NULL,'wallet permission changed');
END $$;
CREATE FUNCTION chainsql._validate_snapshot_v1(s jsonb) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE k text;
BEGIN
    IF s IS NULL OR jsonb_typeof(s) <> 'object' OR octet_length(s::text)>16384 THEN RAISE EXCEPTION 'invalid snapshot'; END IF;
    IF (SELECT count(*) FROM jsonb_object_keys(s)) <> 14 THEN RAISE EXCEPTION 'snapshot requires exactly 14 versioned fields'; END IF;
    FOREACH k IN ARRAY ARRAY['tenant','business_reference','request_revision','source_wallet','destination','network','asset',
        'amount_atomic','fee_ceiling_atomic','policy_version','approval_identity','valid_from','valid_until','interface'] LOOP
        IF jsonb_typeof(s->k) IS DISTINCT FROM 'string' OR length(s->>k) NOT BETWEEN 1 AND 256 THEN RAISE EXCEPTION 'invalid snapshot field: %', k; END IF;
    END LOOP;
    IF s->>'network' <> 'mock:local' OR s->>'asset' <> 'USDC' OR s->>'interface' <> 'mock-usdc-6'
      OR s->>'policy_version' <> 'boundary-v1' OR s->>'source_wallet'='*'
      OR s->>'amount_atomic' !~ '^[1-9][0-9]{0,37}$' OR s->>'fee_ceiling_atomic' !~ '^(0|[1-9][0-9]{0,37})$'
      OR s->>'request_revision' !~ '^[1-9][0-9]{0,8}$' THEN RAISE EXCEPTION 'unsupported transfer snapshot or atomic units'; END IF;
    IF s->>'valid_from' !~ 'Z$' OR s->>'valid_until' !~ 'Z$' THEN RAISE EXCEPTION 'validity timestamps require explicit UTC Z'; END IF;
    IF (s->>'valid_until')::timestamptz <= (s->>'valid_from')::timestamptz
       OR (s->>'valid_until')::timestamptz - (s->>'valid_from')::timestamptz > interval '24 hours'
       OR (s->>'valid_until')::timestamptz <= clock_timestamp() THEN RAISE EXCEPTION 'invalid validity window'; END IF;
END $$;
CREATE FUNCTION chainsql.approve_transfer_v1(s jsonb) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE aid uuid; h chainsql.transfer_heads%ROWTYPE; oldrev bigint;
BEGIN
    PERFORM chainsql._gate_v1(); PERFORM chainsql._validate_snapshot_v1(s);
    IF NOT EXISTS(SELECT FROM chainsql.transfer_wallets WHERE tenant=s->>'tenant' AND source_wallet=s->>'source_wallet' AND enabled) THEN
        RAISE EXCEPTION 'wallet is not permitted'; END IF;
    SELECT * INTO h FROM chainsql.transfer_heads WHERE tenant=s->>'tenant' AND business_reference=s->>'business_reference';
    IF FOUND THEN
        SELECT revision INTO oldrev FROM chainsql.transfer_approvals WHERE id=h.approval_id;
        IF (s->>'request_revision')::bigint <= oldrev THEN RAISE EXCEPTION 'a newer immutable revision is required'; END IF;
        UPDATE chainsql.transfer_approvals SET revoked=true WHERE id=h.approval_id;
    END IF;
    INSERT INTO chainsql.transfer_approvals(snapshot,tenant,business_reference,revision,issued_by)
    VALUES(s,s->>'tenant',s->>'business_reference',(s->>'request_revision')::bigint,session_user) RETURNING id INTO aid;
    INSERT INTO chainsql.transfer_heads(tenant,business_reference,approval_id)
    VALUES(s->>'tenant',s->>'business_reference',aid)
    ON CONFLICT(tenant,business_reference) DO UPDATE SET approval_id=aid,invalidated=false;
    PERFORM chainsql._audit_v1(NULL,'immutable transfer approval issued');
    RETURN aid;
END $$;
CREATE FUNCTION chainsql._app_v1(s jsonb) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
    IF NOT EXISTS(SELECT FROM chainsql.transfer_wallets WHERE tenant=s->>'tenant' AND source_wallet=s->>'source_wallet' AND app_role=session_user) THEN
        RAISE EXCEPTION 'application is not permitted for this tenant wallet'; END IF;
END $$;
CREATE FUNCTION chainsql._current_v1(t chainsql.transfers) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
    IF (SELECT paused FROM chainsql.execution_gate) THEN RAISE EXCEPTION 'execution is paused'; END IF;
    IF NOT EXISTS(SELECT FROM chainsql.transfer_wallets WHERE tenant=t.snapshot->>'tenant'
      AND source_wallet=t.snapshot->>'source_wallet' AND enabled AND app_role=t.requested_by) THEN RAISE EXCEPTION 'wallet permission revoked'; END IF;
    IF NOT EXISTS(SELECT FROM chainsql.transfer_approvals a JOIN chainsql.transfer_heads h ON h.approval_id=a.id
      WHERE a.id=t.approval_id AND NOT a.revoked AND NOT h.invalidated) THEN RAISE EXCEPTION 'approval is stale or revoked'; END IF;
    IF clock_timestamp() < (t.snapshot->>'valid_from')::timestamptz OR clock_timestamp() >= (t.snapshot->>'valid_until')::timestamptz THEN
      RAISE EXCEPTION 'authorization is outside its validity window'; END IF;
END $$;
CREATE FUNCTION chainsql.approved_transfer_v1(p_tenant text,p_business text)
RETURNS TABLE(approval_id uuid,snapshot jsonb)
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE s jsonb; aid uuid;
BEGIN
    SELECT a.id,a.snapshot INTO aid,s FROM chainsql.transfer_heads h JOIN chainsql.transfer_approvals a ON a.id=h.approval_id
    WHERE h.tenant=p_tenant AND h.business_reference=p_business AND NOT h.invalidated AND NOT a.revoked;
    IF NOT FOUND THEN RETURN; END IF;
    PERFORM chainsql._app_v1(s); RETURN QUERY SELECT aid,s;
END $$;
CREATE FUNCTION chainsql.request_transfer_v1(p_approval uuid,p_snapshot jsonb,p_key text) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE a chainsql.transfer_approvals%ROWTYPE; t chainsql.transfers%ROWTYPE; active uuid;
BEGIN
    PERFORM chainsql._gate_v1();
    SELECT * INTO STRICT a FROM chainsql.transfer_approvals WHERE id=p_approval;
    PERFORM chainsql._app_v1(a.snapshot);
    IF p_snapshot IS DISTINCT FROM a.snapshot THEN RAISE EXCEPTION 'snapshot does not match independent approval'; END IF;
    SELECT * INTO t FROM chainsql.transfers WHERE requested_by=session_user AND request_key=p_key;
    IF FOUND THEN
        IF t.approval_id<>p_approval OR t.snapshot<>p_snapshot THEN RAISE EXCEPTION 'idempotency key binds another immutable request'; END IF;
        RETURN t.id;
    END IF;
    SELECT active_transfer INTO active FROM chainsql.transfer_heads WHERE tenant=a.tenant AND business_reference=a.business_reference;
    IF active IS NOT NULL THEN RAISE EXCEPTION 'business obligation already has a payable or settled attempt'; END IF;
    INSERT INTO chainsql.transfers(approval_id,snapshot,requested_by,request_key)
    VALUES(p_approval,p_snapshot,session_user,p_key) RETURNING * INTO t;
    PERFORM chainsql._current_v1(t);
    UPDATE chainsql.transfer_heads SET active_transfer=t.id WHERE tenant=a.tenant AND business_reference=a.business_reference;
    PERFORM chainsql._audit_v1(t.id,'request accepted'); RETURN t.id;
END $$;
CREATE FUNCTION chainsql.invalidate_business_v1(p_tenant text,p_business text) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE s jsonb;
BEGIN
    PERFORM chainsql._gate_v1();
    SELECT a.snapshot INTO s FROM chainsql.transfer_heads h JOIN chainsql.transfer_approvals a ON a.id=h.approval_id
    WHERE h.tenant=p_tenant AND h.business_reference=p_business;
    IF NOT FOUND THEN RETURN; END IF;
    PERFORM chainsql._app_v1(s);
    UPDATE chainsql.transfer_heads SET invalidated=true WHERE tenant=p_tenant AND business_reference=p_business;
    UPDATE chainsql.transfer_approvals SET revoked=true WHERE tenant=p_tenant AND business_reference=p_business;
    PERFORM chainsql._audit_v1(NULL,'business payment details invalidated');
END $$;
CREATE FUNCTION chainsql.revoke_approval_v1(p_id uuid) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
    PERFORM chainsql._gate_v1(); UPDATE chainsql.transfer_approvals SET revoked=true WHERE id=p_id;
    PERFORM chainsql._audit_v1(NULL,'approval revoked');
END $$;
CREATE FUNCTION chainsql.claim_transfer_v1(p_id uuid)
RETURNS TABLE(transfer_id uuid,claim_token uuid,fence bigint,preparation_id text)
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE t chainsql.transfers%ROWTYPE; b chainsql.transfer_budgets%ROWTYPE; n integer:=0;
        v numeric; f numeric;
BEGIN
    PERFORM chainsql._gate_v1(); SELECT * INTO STRICT t FROM chainsql.transfers WHERE id=p_id;
    IF t.state IN ('cancelled','observed') THEN RAISE EXCEPTION 'terminal operation'; END IF;
    IF t.lease_until > clock_timestamp() THEN RAISE EXCEPTION 'operation already has an active fenced owner'; END IF;
    IF t.state NOT IN ('dispatched','reconciliation') THEN PERFORM chainsql._current_v1(t); END IF;
    IF NOT t.reserved THEN
        v:=(t.snapshot->>'amount_atomic')::numeric; f:=(t.snapshot->>'fee_ceiling_atomic')::numeric;
        FOR b IN SELECT * FROM chainsql.transfer_budgets WHERE tenant=t.snapshot->>'tenant'
          AND scope IN ('*',t.snapshot->>'source_wallet') ORDER BY scope LOOP
            n:=n+1;
            IF v>b.per_value OR f>b.per_fee OR b.value_reserved+b.value_spent+v>b.value_limit
              OR b.fee_reserved+b.fee_spent+f>b.fee_limit THEN RAISE EXCEPTION 'budget exceeded'; END IF;
        END LOOP;
        IF n<>2 THEN RAISE EXCEPTION 'both company and wallet budgets are required'; END IF;
        UPDATE chainsql.transfer_budgets SET value_reserved=value_reserved+v,fee_reserved=fee_reserved+f
        WHERE tenant=t.snapshot->>'tenant' AND scope IN ('*',t.snapshot->>'source_wallet');
    END IF;
    UPDATE chainsql.transfers SET reserved=true,state=CASE WHEN state='requested' THEN 'reserved' ELSE state END,
      fence=transfers.fence+1,claim_token=gen_random_uuid(),lease_until=clock_timestamp()+interval '30 seconds',claimed_by=session_user
      WHERE id=p_id RETURNING * INTO t;
    PERFORM chainsql._audit_v1(t.id,'budget reserved and fenced owner claimed');
    RETURN QUERY SELECT t.id,t.claim_token,t.fence,'transfer-v1:'||t.id::text;
END $$;
CREATE FUNCTION chainsql._fence_v1(p_id uuid,p_token uuid,p_fence bigint) RETURNS chainsql.transfers
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE t chainsql.transfers%ROWTYPE;
BEGIN
    SELECT * INTO STRICT t FROM chainsql.transfers WHERE id=p_id;
    IF p_token IS NULL OR p_fence IS NULL OR t.claim_token IS DISTINCT FROM p_token OR t.fence<>p_fence
      OR t.lease_until IS NULL OR t.lease_until<=clock_timestamp() THEN RAISE EXCEPTION 'stale fenced ownership'; END IF;
    RETURN t;
END $$;
CREATE FUNCTION chainsql.signing_material_v1(p_id uuid,p_token uuid,p_fence bigint)
RETURNS TABLE(snapshot jsonb,preparation_id text,ciphertext bytea,digest text,state text)
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE t chainsql.transfers%ROWTYPE;
BEGIN
    PERFORM chainsql._gate_v1(); t:=chainsql._fence_v1(p_id,p_token,p_fence);
    PERFORM chainsql._current_v1(t);
    IF t.state NOT IN ('reserved','prepared','dispatched') THEN RAISE EXCEPTION 'operation is not signable'; END IF;
    RETURN QUERY SELECT t.snapshot,'transfer-v1:'||t.id::text,a.ciphertext,a.digest,t.state
      FROM (SELECT 1) z LEFT JOIN chainsql.transfer_authorizations a ON a.transfer_id=t.id;
END $$;
CREATE FUNCTION chainsql.save_authorization_v1(p_id uuid,p_token uuid,p_fence bigint,p_cipher bytea,p_digest text)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE t chainsql.transfers%ROWTYPE;
BEGIN
    PERFORM chainsql._gate_v1(); t:=chainsql._fence_v1(p_id,p_token,p_fence); PERFORM chainsql._current_v1(t);
    IF t.state<>'reserved' OR NOT t.reserved THEN RAISE EXCEPTION 'authorization may only be saved once against a reservation'; END IF;
    INSERT INTO chainsql.transfer_authorizations(transfer_id,ciphertext,digest) VALUES(p_id,p_cipher,p_digest);
    UPDATE chainsql.transfers SET state='prepared' WHERE id=p_id;
    PERFORM chainsql._audit_v1(p_id,'encrypted authorization durably prepared');
END $$;
CREATE FUNCTION chainsql.dispatch_transfer_v1(p_id uuid,p_token uuid,p_fence bigint)
RETURNS TABLE(ciphertext bytea,digest text)
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE t chainsql.transfers%ROWTYPE; a chainsql.transfer_authorizations%ROWTYPE;
BEGIN
    PERFORM chainsql._gate_v1(); t:=chainsql._fence_v1(p_id,p_token,p_fence); PERFORM chainsql._current_v1(t);
    IF t.state NOT IN ('prepared','dispatched') THEN RAISE EXCEPTION 'operation cannot dispatch'; END IF;
    SELECT * INTO STRICT a FROM chainsql.transfer_authorizations WHERE transfer_id=p_id;
    IF a.saved_xid=txid_current() THEN RAISE EXCEPTION 'authorization must commit before dispatch'; END IF;
    UPDATE chainsql.transfers SET state='dispatched',dispatched_at=coalesce(dispatched_at,clock_timestamp()) WHERE id=p_id;
    PERFORM chainsql._audit_v1(p_id,'dispatch intent recorded; outcome may be uncertain');
    RETURN QUERY SELECT a.ciphertext,a.digest;
END $$;
-- This gateway is the selected pilot execution boundary. Only the restricted signer
-- can call it, after signature verification. Its ledger and expiry check are atomic.
CREATE FUNCTION chainsql.accept_mock_transfer_v1(p_id uuid,p_token uuid,p_fence bigint,p_digest text)
RETURNS text LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE t chainsql.transfers%ROWTYPE; r text;
BEGIN
    PERFORM chainsql._gate_v1(); t:=chainsql._fence_v1(p_id,p_token,p_fence);
    SELECT receipt INTO r FROM chainsql.mock_settlements WHERE transfer_id=p_id;
    IF FOUND THEN RETURN r; END IF;
    PERFORM chainsql._current_v1(t);
    IF t.state<>'dispatched' OR NOT t.reserved OR t.dispatched_at IS NULL THEN RAISE EXCEPTION 'no dispatch permit'; END IF;
    IF NOT EXISTS(SELECT FROM chainsql.transfer_authorizations WHERE transfer_id=p_id AND digest=p_digest AND saved_xid<>txid_current()) THEN
        RAISE EXCEPTION 'authorization identity mismatch'; END IF;
    r:='mock-transfer:'||p_id::text;
    -- The simulator charges a fixed 1 atomic-unit fee, bounded by the approved ceiling.
    IF (t.snapshot->>'fee_ceiling_atomic')::numeric<1 THEN RAISE EXCEPTION 'fee ceiling below simulator fee'; END IF;
    INSERT INTO chainsql.mock_settlements(transfer_id,receipt,fee_atomic) VALUES(p_id,r,1);
    PERFORM chainsql._audit_v1(p_id,'simulator accepted exact prepared authorization'); RETURN r;
END $$;
CREATE FUNCTION chainsql._release_v1(t chainsql.transfers,p_value numeric,p_fee numeric) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
    IF t.reserved THEN
        UPDATE chainsql.transfer_budgets SET
          value_reserved=value_reserved-(t.snapshot->>'amount_atomic')::numeric,
          fee_reserved=fee_reserved-(t.snapshot->>'fee_ceiling_atomic')::numeric,
          value_spent=value_spent+p_value,fee_spent=fee_spent+p_fee
        WHERE tenant=t.snapshot->>'tenant' AND scope IN ('*',t.snapshot->>'source_wallet');
        UPDATE chainsql.transfers SET reserved=false WHERE id=t.id;
    END IF;
END $$;
CREATE FUNCTION chainsql.cancel_transfer_v1(p_id uuid) RETURNS text
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE t chainsql.transfers%ROWTYPE;
BEGIN
    PERFORM chainsql._gate_v1(); SELECT * INTO STRICT t FROM chainsql.transfers WHERE id=p_id;
    PERFORM chainsql._app_v1(t.snapshot);
    IF t.requested_by<>session_user THEN RAISE EXCEPTION 'wrong requesting application'; END IF;
    IF t.state IN ('observed','cancelled') THEN RETURN t.state; END IF;
    UPDATE chainsql.transfer_approvals SET revoked=true WHERE id=t.approval_id;
    IF EXISTS(SELECT FROM chainsql.transfer_authorizations WHERE transfer_id=p_id) OR t.dispatched_at IS NOT NULL THEN
        UPDATE chainsql.transfers SET state='reconciliation',reason='Cancellation cannot undo a payable authorization; reconcile or compensate.' WHERE id=p_id;
        PERFORM chainsql._audit_v1(p_id,'cancellation requires reconciliation; reservation retained');
        RETURN 'reconciliation';
    END IF;
    PERFORM chainsql._release_v1(t,0,0);
    UPDATE chainsql.transfers SET state='cancelled',reason='Cancelled before any authorization existed.' WHERE id=p_id;
    UPDATE chainsql.transfer_heads SET active_transfer=NULL WHERE active_transfer=p_id;
    PERFORM chainsql._audit_v1(p_id,'unsigned request cancelled; reservation released'); RETURN 'cancelled';
END $$;
CREATE FUNCTION chainsql.reconcile_transfer_v1(p_id uuid) RETURNS text
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE t chainsql.transfers%ROWTYPE; r chainsql.mock_settlements%ROWTYPE;
BEGIN
    PERFORM chainsql._gate_v1(); SELECT * INTO STRICT t FROM chainsql.transfers WHERE id=p_id;
    IF t.state IN ('observed','cancelled') THEN RETURN t.state; END IF;
    SELECT * INTO r FROM chainsql.mock_settlements WHERE transfer_id=p_id;
    IF FOUND THEN
        PERFORM chainsql._release_v1(t,(t.snapshot->>'amount_atomic')::numeric,r.fee_atomic);
        UPDATE chainsql.transfers SET state='observed',reason=CASE WHEN t.state='reconciliation'
          THEN 'Settlement observed after cancellation: any refund requires a separately approved compensation.' ELSE 'Simulation settlement observed.' END WHERE id=p_id;
        PERFORM chainsql._audit_v1(p_id,'reserved value and actual fee converted to observed spend'); RETURN 'observed';
    END IF;
    IF clock_timestamp() < (t.snapshot->>'valid_until')::timestamptz THEN
        -- Absence of a receipt before expiry is not evidence of non-settlement.
        RETURN t.state;
    END IF;
    -- Only mock:local is admitted. Its authoritative ledger and clock are under the
    -- same lock as acceptance, proving this expired authorization cannot settle later.
    PERFORM chainsql._release_v1(t,0,0);
    UPDATE chainsql.transfers SET state='cancelled',reason='Simulator proved expiry without settlement; reservation released.' WHERE id=p_id;
    UPDATE chainsql.transfer_heads SET active_transfer=NULL WHERE active_transfer=p_id;
    PERFORM chainsql._audit_v1(p_id,'authoritative simulator expiry proved; reservation released'); RETURN 'cancelled';
END $$;
CREATE FUNCTION chainsql.transfer_status_v1(p_id uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE t chainsql.transfers%ROWTYPE; r chainsql.mock_settlements%ROWTYPE;
BEGIN
    SELECT * INTO STRICT t FROM chainsql.transfers WHERE id=p_id;
    PERFORM chainsql._app_v1(t.snapshot);
    IF t.requested_by<>session_user THEN RAISE EXCEPTION 'wrong requesting application'; END IF;
    SELECT * INTO r FROM chainsql.mock_settlements WHERE transfer_id=p_id;
    RETURN jsonb_build_object('id',t.id,'snapshot',t.snapshot,'state',t.state,'reserved',t.reserved,
      'preparation_id','transfer-v1:'||t.id::text,'receipt',r.receipt,'observed_fee_atomic',r.fee_atomic::text,'reason',t.reason);
END $$;

-- Immutable records cannot be changed even through accidental future table grants.
CREATE FUNCTION chainsql._immutable_transfer_v1() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
    IF TG_TABLE_NAME='transfers' THEN
        IF NEW.snapshot IS DISTINCT FROM OLD.snapshot OR NEW.approval_id<>OLD.approval_id
          OR NEW.requested_by<>OLD.requested_by OR NEW.request_key<>OLD.request_key THEN RAISE EXCEPTION 'immutable transfer snapshot'; END IF;
    ELSE
        IF NEW.snapshot IS DISTINCT FROM OLD.snapshot OR NEW.tenant<>OLD.tenant
          OR NEW.business_reference<>OLD.business_reference OR NEW.revision<>OLD.revision
          OR (OLD.revoked AND NOT NEW.revoked) THEN RAISE EXCEPTION 'immutable approval'; END IF;
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER immutable_transfer BEFORE UPDATE ON chainsql.transfers FOR EACH ROW EXECUTE FUNCTION chainsql._immutable_transfer_v1();
CREATE TRIGGER immutable_approval BEFORE UPDATE ON chainsql.transfer_approvals FOR EACH ROW EXECUTE FUNCTION chainsql._immutable_transfer_v1();

SELECT pg_catalog.pg_extension_config_dump('chainsql.execution_gate','');
SELECT pg_catalog.pg_extension_config_dump('chainsql.transfer_budgets','');
SELECT pg_catalog.pg_extension_config_dump('chainsql.transfer_wallets','');
SELECT pg_catalog.pg_extension_config_dump('chainsql.transfer_approvals','');
SELECT pg_catalog.pg_extension_config_dump('chainsql.transfer_heads','');
SELECT pg_catalog.pg_extension_config_dump('chainsql.transfers','');
SELECT pg_catalog.pg_extension_config_dump('chainsql.transfer_authorizations','');
SELECT pg_catalog.pg_extension_config_dump('chainsql.mock_settlements','');
SELECT pg_catalog.pg_extension_config_dump('chainsql.transfer_audit','');
REVOKE ALL ON ALL TABLES IN SCHEMA chainsql FROM PUBLIC;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA chainsql FROM PUBLIC;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA chainsql FROM PUBLIC;
