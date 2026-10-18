-- Arc testnet support is independently disabled until the policy operator enables it.
CREATE TABLE chainsql.arc_gate(singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton),enabled boolean NOT NULL DEFAULT false);
CREATE TABLE chainsql.tenant_units(tenant text PRIMARY KEY,network text NOT NULL,asset text NOT NULL,interface text NOT NULL);
INSERT INTO chainsql.tenant_units SELECT DISTINCT tenant,snapshot->>'network',snapshot->>'asset',snapshot->>'interface' FROM chainsql.transfer_approvals;
CREATE TABLE chainsql.arc_wallet_nonces(sender text PRIMARY KEY,next_nonce bigint NOT NULL CHECK(next_nonce>=0));
CREATE TABLE chainsql.arc_plans(
 transfer_id uuid PRIMARY KEY REFERENCES chainsql.transfers(id), sender text NOT NULL,
 nonce bigint NOT NULL CHECK(nonce>=0),gas numeric(78,0) NOT NULL,max_fee numeric(78,0) NOT NULL,priority_fee numeric(78,0) NOT NULL,
 provider_request_id uuid NOT NULL DEFAULT gen_random_uuid(),tx_hash text,
 UNIQUE(sender,nonce));
CREATE TABLE chainsql.arc_observations(transfer_id uuid PRIMARY KEY REFERENCES chainsql.transfers(id),evidence jsonb NOT NULL);
CREATE FUNCTION chainsql.enable_arc_v1(p_enabled boolean) RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
 PERFORM chainsql._gate_v1();
 INSERT INTO chainsql.arc_gate(singleton,enabled) VALUES(true,p_enabled) ON CONFLICT(singleton) DO UPDATE SET enabled=p_enabled;
 PERFORM chainsql._audit_v1(NULL,'Arc execution permission changed');
END $$;
CREATE FUNCTION chainsql._bind_units_v1() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
 INSERT INTO chainsql.tenant_units VALUES(NEW.tenant,NEW.snapshot->>'network',NEW.snapshot->>'asset',NEW.snapshot->>'interface') ON CONFLICT DO NOTHING;
 IF NOT EXISTS(SELECT FROM chainsql.tenant_units WHERE tenant=NEW.tenant AND network=NEW.snapshot->>'network'
   AND asset=NEW.snapshot->>'asset' AND interface=NEW.snapshot->>'interface') THEN RAISE EXCEPTION 'tenant budget unit mismatch'; END IF;
 RETURN NEW;
END $$;
ALTER TABLE chainsql.transfer_approvals ADD CONSTRAINT approval_tenant_units_fk FOREIGN KEY (tenant) REFERENCES chainsql.tenant_units(tenant);
CREATE TRIGGER tenant_units BEFORE INSERT ON chainsql.transfer_approvals FOR EACH ROW EXECUTE FUNCTION chainsql._bind_units_v1();


CREATE OR REPLACE FUNCTION chainsql._validate_snapshot_v1(s jsonb) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE k text;
BEGIN
    IF s IS NULL OR jsonb_typeof(s) <> 'object' OR octet_length(s::text)>16384 THEN RAISE EXCEPTION 'invalid snapshot'; END IF;
    IF (SELECT count(*) FROM jsonb_object_keys(s)) <> 14 THEN RAISE EXCEPTION 'snapshot requires exactly 14 versioned fields'; END IF;
    FOREACH k IN ARRAY ARRAY['tenant','business_reference','request_revision','source_wallet','destination','network','asset',
        'amount_atomic','fee_ceiling_atomic','policy_version','approval_identity','valid_from','valid_until','interface'] LOOP
        IF jsonb_typeof(s->k) IS DISTINCT FROM 'string' OR length(s->>k) NOT BETWEEN 1 AND 256 THEN RAISE EXCEPTION 'invalid snapshot field: %', k; END IF;
    END LOOP;
    IF NOT ((s->>'network' = 'mock:local' AND s->>'interface' = 'mock-usdc-6') OR (s->>'network' = 'eip155:5042002' AND s->>'interface' = 'arc-erc20-6-fee18')) OR s->>'asset' <> 'USDC'
      OR s->>'policy_version' <> 'boundary-v1' OR s->>'source_wallet'='*'
      OR s->>'amount_atomic' !~ '^[1-9][0-9]{0,37}$' OR s->>'fee_ceiling_atomic' !~ '^(0|[1-9][0-9]{0,37})$'
      OR s->>'request_revision' !~ '^[1-9][0-9]{0,8}$' THEN RAISE EXCEPTION 'unsupported transfer snapshot or atomic units'; END IF;
    IF s->>'valid_from' !~ 'Z$' OR s->>'valid_until' !~ 'Z$' THEN RAISE EXCEPTION 'validity timestamps require explicit UTC Z'; END IF;
    IF (s->>'valid_until')::timestamptz <= (s->>'valid_from')::timestamptz
       OR (s->>'valid_until')::timestamptz - (s->>'valid_from')::timestamptz > interval '24 hours'
       OR (s->>'valid_until')::timestamptz <= clock_timestamp() THEN RAISE EXCEPTION 'invalid validity window'; END IF;
END $$;

CREATE OR REPLACE FUNCTION chainsql._current_v1(t chainsql.transfers) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
    IF t.snapshot->>'network'='eip155:5042002' AND NOT coalesce((SELECT enabled FROM chainsql.arc_gate),false) THEN RAISE EXCEPTION 'Arc execution disabled'; END IF;
    IF (SELECT paused FROM chainsql.execution_gate) THEN RAISE EXCEPTION 'execution is paused'; END IF;
    IF NOT EXISTS(SELECT FROM chainsql.transfer_wallets WHERE tenant=t.snapshot->>'tenant'
      AND source_wallet=t.snapshot->>'source_wallet' AND enabled AND app_role=t.requested_by) THEN RAISE EXCEPTION 'wallet permission revoked'; END IF;
    IF NOT EXISTS(SELECT FROM chainsql.transfer_approvals a JOIN chainsql.transfer_heads h ON h.approval_id=a.id
      WHERE a.id=t.approval_id AND NOT a.revoked AND NOT h.invalidated) THEN RAISE EXCEPTION 'approval is stale or revoked'; END IF;
    IF clock_timestamp() < (t.snapshot->>'valid_from')::timestamptz OR clock_timestamp() >= (t.snapshot->>'valid_until')::timestamptz THEN
      RAISE EXCEPTION 'authorization is outside its validity window'; END IF;
END $$;

CREATE OR REPLACE FUNCTION chainsql.accept_mock_transfer_v1(p_id uuid,p_token uuid,p_fence bigint,p_digest text)
RETURNS text LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE t chainsql.transfers%ROWTYPE; r text;
BEGIN
    PERFORM chainsql._gate_v1(); t:=chainsql._fence_v1(p_id,p_token,p_fence);
    IF t.snapshot->>'network'<>'mock:local' THEN RAISE EXCEPTION 'mock gateway cannot accept Arc'; END IF;
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

CREATE OR REPLACE FUNCTION chainsql.reconcile_transfer_v1(p_id uuid) RETURNS text
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE t chainsql.transfers%ROWTYPE; r chainsql.mock_settlements%ROWTYPE;
BEGIN
    PERFORM chainsql._gate_v1(); SELECT * INTO STRICT t FROM chainsql.transfers WHERE id=p_id;
    IF t.state IN ('observed','cancelled') THEN RETURN t.state; END IF;
    IF t.snapshot->>'network'='eip155:5042002' THEN
        -- EVM signed transactions have no expiry. Never release on local time alone.
        UPDATE chainsql.transfers SET state='reconciliation',reason='Await authoritative Arc observation; authorization may still settle.' WHERE id=p_id;
        RETURN 'reconciliation';
    END IF;
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

CREATE OR REPLACE FUNCTION chainsql.dispatch_transfer_v1(p_id uuid,p_token uuid,p_fence bigint)
RETURNS TABLE(ciphertext bytea,digest text)
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE t chainsql.transfers%ROWTYPE; a chainsql.transfer_authorizations%ROWTYPE;
BEGIN
    PERFORM chainsql._gate_v1(); t:=chainsql._fence_v1(p_id,p_token,p_fence); PERFORM chainsql._current_v1(t);
    IF t.snapshot->>'network'='eip155:5042002' AND NOT EXISTS(SELECT FROM chainsql.arc_plans WHERE transfer_id=p_id AND tx_hash IS NOT NULL) THEN RAISE EXCEPTION 'durable Arc plan and hash required'; END IF;
    IF t.state NOT IN ('prepared','dispatched') THEN RAISE EXCEPTION 'operation cannot dispatch'; END IF;
    SELECT * INTO STRICT a FROM chainsql.transfer_authorizations WHERE transfer_id=p_id;
    IF a.saved_xid=txid_current() THEN RAISE EXCEPTION 'authorization must commit before dispatch'; END IF;
    UPDATE chainsql.transfers SET state='dispatched',dispatched_at=coalesce(dispatched_at,clock_timestamp()) WHERE id=p_id;
    PERFORM chainsql._audit_v1(p_id,'dispatch intent recorded; outcome may be uncertain');
    RETURN QUERY SELECT a.ciphertext,a.digest;
END $$;

CREATE OR REPLACE FUNCTION chainsql.transfer_status_v1(p_id uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE t chainsql.transfers%ROWTYPE; r chainsql.mock_settlements%ROWTYPE;
BEGIN
    SELECT * INTO STRICT t FROM chainsql.transfers WHERE id=p_id;
    PERFORM chainsql._app_v1(t.snapshot);
    IF t.requested_by<>session_user THEN RAISE EXCEPTION 'wrong requesting application'; END IF;
    SELECT * INTO r FROM chainsql.mock_settlements WHERE transfer_id=p_id;
    RETURN jsonb_build_object('id',t.id,'snapshot',t.snapshot,'state',t.state,'reserved',t.reserved,
      'preparation_id','transfer-v1:'||t.id::text,'receipt',r.receipt,'observed_fee_atomic',r.fee_atomic::text,'reason',t.reason,'arc_observation',(SELECT evidence FROM chainsql.arc_observations WHERE transfer_id=p_id));
END $$;


CREATE FUNCTION chainsql.arc_plan_v1(p_id uuid,p_token uuid,p_fence bigint,p_sender text,p_pending bigint,p_gas numeric,p_max_fee numeric,p_priority numeric)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE t chainsql.transfers%ROWTYPE;p chainsql.arc_plans%ROWTYPE;n bigint;
BEGIN
 PERFORM chainsql._gate_v1();t:=chainsql._fence_v1(p_id,p_token,p_fence);PERFORM chainsql._current_v1(t);
 IF t.snapshot->>'network'<>'eip155:5042002' OR NOT t.reserved THEN RAISE EXCEPTION 'not a reserved Arc request'; END IF;
 SELECT * INTO p FROM chainsql.arc_plans WHERE transfer_id=p_id;
 IF NOT FOUND THEN
  IF p_sender IS NULL OR p_pending IS NULL OR p_gas IS NULL OR p_max_fee IS NULL OR p_priority IS NULL
     OR p_gas::text='NaN' OR p_max_fee::text='NaN' OR p_priority::text='NaN' OR p_sender !~ '^0x[0-9a-f]{40}$' OR p_pending<0 OR p_pending>9007199254740991 OR p_gas<21000 OR p_max_fee<1
     OR p_priority<0 OR p_priority>p_max_fee OR p_gas<>trunc(p_gas) OR p_max_fee<>trunc(p_max_fee) OR p_priority<>trunc(p_priority)
     OR p_gas*p_max_fee>(t.snapshot->>'fee_ceiling_atomic')::numeric THEN RAISE EXCEPTION 'invalid or over-budget Arc plan'; END IF;
  INSERT INTO chainsql.arc_wallet_nonces VALUES(p_sender,p_pending) ON CONFLICT DO NOTHING;
  SELECT greatest(next_nonce,p_pending) INTO n FROM chainsql.arc_wallet_nonces WHERE sender=p_sender;
  UPDATE chainsql.arc_wallet_nonces SET next_nonce=n+1 WHERE sender=p_sender;
  INSERT INTO chainsql.arc_plans(transfer_id,sender,nonce,gas,max_fee,priority_fee) VALUES(p_id,p_sender,n,p_gas,p_max_fee,p_priority) RETURNING * INTO p;
 ELSE
  IF p.sender<>p_sender THEN RAISE EXCEPTION 'wallet identity changed'; END IF;
 END IF;
 RETURN jsonb_build_object('sender',p.sender,'nonce',p.nonce::text,'gas',p.gas::text,'maxFeePerGas',p.max_fee::text,
    'maxPriorityFeePerGas',p.priority_fee::text,'providerRequestId',p.provider_request_id,'txHash',p.tx_hash);
END $$;
CREATE FUNCTION chainsql.save_arc_authorization_v1(p_id uuid,p_token uuid,p_fence bigint,p_cipher bytea,p_digest text,p_hash text)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
 PERFORM chainsql._gate_v1();
 IF p_hash IS NULL OR p_hash !~ '^0x[0-9a-f]{64}$' OR NOT EXISTS(SELECT FROM chainsql.arc_plans WHERE transfer_id=p_id AND tx_hash IS NULL) THEN RAISE EXCEPTION 'invalid Arc authorization identity'; END IF;
 PERFORM chainsql.save_authorization_v1(p_id,p_token,p_fence,p_cipher,p_digest);
 UPDATE chainsql.arc_plans SET tx_hash=p_hash WHERE transfer_id=p_id;
END $$;
CREATE FUNCTION chainsql.arc_recovery_material_v1(p_id uuid)
RETURNS TABLE(snapshot jsonb,plan jsonb,ciphertext bytea,digest text)
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
 RETURN QUERY SELECT t.snapshot,jsonb_build_object('sender',p.sender,'nonce',p.nonce::text,'gas',p.gas::text,
   'maxFeePerGas',p.max_fee::text,'maxPriorityFeePerGas',p.priority_fee::text,'providerRequestId',p.provider_request_id,'txHash',p.tx_hash),a.ciphertext,a.digest
 FROM chainsql.transfers t JOIN chainsql.arc_plans p ON p.transfer_id=t.id JOIN chainsql.transfer_authorizations a ON a.transfer_id=t.id
 WHERE t.id=p_id AND t.snapshot->>'network'='eip155:5042002';
END $$;
CREATE FUNCTION chainsql.record_arc_observation_v1(p_id uuid,e jsonb) RETURNS text
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE t chainsql.transfers%ROWTYPE;p chainsql.arc_plans%ROWTYPE;fee numeric;old jsonb;k text;
BEGIN
 PERFORM chainsql._gate_v1();SELECT * INTO STRICT t FROM chainsql.transfers WHERE id=p_id;
 SELECT * INTO STRICT p FROM chainsql.arc_plans WHERE transfer_id=p_id;
 IF e IS NULL OR jsonb_typeof(e)<>'object' THEN RAISE EXCEPTION 'invalid Arc observation'; END IF;
 FOREACH k IN ARRAY ARRAY['state','txHash','amountAtomic','token','feeAtomic','blockNumber','blockHash',
   'finalizedBlockNumber','finalizedBlockHash','observedAt','providerRequestId','receiptStatus','network','asset'] LOOP
   IF jsonb_typeof(e->k) IS DISTINCT FROM 'string' THEN RAISE EXCEPTION 'missing Arc observation field'; END IF;
 END LOOP;
 IF e->>'chainId' IS DISTINCT FROM '5042002' OR e->>'asset' IS DISTINCT FROM 'USDC'
   OR e->>'providerRequestId' IS DISTINCT FROM p.provider_request_id::text
   OR e->>'blockNumber' !~ '^(0|[1-9][0-9]{0,18})$'
   OR e->>'finalizedBlockNumber' !~ '^(0|[1-9][0-9]{0,18})$'
   OR e->>'observedAt' !~ 'Z$'
   OR (e->>'state'='confirmed' AND (e->>'receiptStatus'<>'success' OR e->>'matchingTransferLogs' IS DISTINCT FROM '1'))
   OR (e->>'state'='reverted' AND e->>'receiptStatus'<>'reverted')
   THEN RAISE EXCEPTION 'invalid Arc evidence identity'; END IF;
 PERFORM (e->>'observedAt')::timestamptz;
 IF e IS NULL OR jsonb_typeof(e)<>'object' OR e->>'network' IS DISTINCT FROM 'eip155:5042002'
   OR e->>'state' NOT IN ('confirmed','reverted') OR e->>'txHash' IS DISTINCT FROM p.tx_hash
   OR e->>'amountAtomic' IS DISTINCT FROM t.snapshot->>'amount_atomic'
   OR e->>'token' IS DISTINCT FROM '0x3600000000000000000000000000000000000000'
   OR e->>'amountDecimals' IS DISTINCT FROM '6' OR e->>'feeDecimals' IS DISTINCT FROM '18'
   OR (e->>'blockNumber')::numeric>(e->>'finalizedBlockNumber')::numeric
   OR e->>'feeAtomic' !~ '^(0|[1-9][0-9]{0,37})$'
   OR e->>'blockHash' !~ '^0x[0-9a-f]{64}$' OR e->>'finalizedBlockHash' !~ '^0x[0-9a-f]{64}$'
   OR e->>'observedAt' IS NULL THEN RAISE EXCEPTION 'invalid Arc observation'; END IF;
 fee:=(e->>'feeAtomic')::numeric;
 IF fee>(t.snapshot->>'fee_ceiling_atomic')::numeric THEN RAISE EXCEPTION 'observed fee exceeds allowance; manual review required'; END IF;
 SELECT evidence INTO old FROM chainsql.arc_observations WHERE transfer_id=p_id;
 IF FOUND THEN
  IF old->>'txHash'<>e->>'txHash' OR old->>'state'<>e->>'state' OR old->>'feeAtomic'<>e->>'feeAtomic' THEN RAISE EXCEPTION 'conflicting terminal observation'; END IF;
  RETURN old->>'state';
 END IF;
 IF t.state NOT IN ('prepared','dispatched','reconciliation') OR NOT t.reserved THEN RAISE EXCEPTION 'unreserved or undispatched Arc operation'; END IF;
 INSERT INTO chainsql.arc_observations VALUES(p_id,e);
 PERFORM chainsql._release_v1(t,CASE WHEN e->>'state'='confirmed' THEN (t.snapshot->>'amount_atomic')::numeric ELSE 0 END,fee);
 UPDATE chainsql.transfers SET state='observed',reason=CASE WHEN e->>'state'='confirmed' THEN 'Arc transfer observed; accounting requires separate ORM review.' ELSE 'Arc transaction reverted; gas spent, bill remains unpaid.' END WHERE id=p_id;
 PERFORM chainsql._audit_v1(p_id,'finalized Arc observation recorded'); RETURN e->>'state';
END $$;
SELECT pg_catalog.pg_extension_config_dump('chainsql.arc_gate','');
SELECT pg_catalog.pg_extension_config_dump('chainsql.tenant_units','');
SELECT pg_catalog.pg_extension_config_dump('chainsql.arc_wallet_nonces','');
SELECT pg_catalog.pg_extension_config_dump('chainsql.arc_plans','');
SELECT pg_catalog.pg_extension_config_dump('chainsql.arc_observations','');
REVOKE ALL ON ALL TABLES IN SCHEMA chainsql FROM PUBLIC;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA chainsql FROM PUBLIC;
