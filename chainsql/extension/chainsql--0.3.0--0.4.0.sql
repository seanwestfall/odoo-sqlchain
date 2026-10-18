-- x402 v2 exact/Base Sepolia resource purchases; separate from invoice payment.
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
    IF NOT ((s->>'network' = 'mock:local' AND s->>'interface' = 'mock-usdc-6') OR (s->>'network' = 'eip155:84532' AND s->>'interface' = 'x402-eip3009-6') OR (s->>'network' = 'eip155:5042002' AND s->>'interface' = 'arc-erc20-6-fee18')) OR s->>'asset' <> 'USDC'
      OR s->>'policy_version' <> 'boundary-v1' OR s->>'source_wallet'='*'
      OR s->>'amount_atomic' !~ '^[1-9][0-9]{0,37}$' OR s->>'fee_ceiling_atomic' !~ '^(0|[1-9][0-9]{0,37})$'
      OR s->>'request_revision' !~ '^[1-9][0-9]{0,8}$' THEN RAISE EXCEPTION 'unsupported transfer snapshot or atomic units'; END IF;
    IF s->>'valid_from' !~ 'Z$' OR s->>'valid_until' !~ 'Z$' THEN RAISE EXCEPTION 'validity timestamps require explicit UTC Z'; END IF;
    IF (s->>'valid_until')::timestamptz <= (s->>'valid_from')::timestamptz
       OR (s->>'valid_until')::timestamptz - (s->>'valid_from')::timestamptz > interval '24 hours'
       OR (s->>'valid_until')::timestamptz <= clock_timestamp() THEN RAISE EXCEPTION 'invalid validity window'; END IF;
END $$;
CREATE OR REPLACE FUNCTION chainsql.reconcile_transfer_v1(p_id uuid) RETURNS text
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE t chainsql.transfers%ROWTYPE; r chainsql.mock_settlements%ROWTYPE;
BEGIN
    PERFORM chainsql._gate_v1(); SELECT * INTO STRICT t FROM chainsql.transfers WHERE id=p_id;
    IF t.state IN ('observed','cancelled') THEN RETURN t.state; END IF;
    IF t.snapshot->>'network'<>'mock:local' THEN
        -- Expiry alone cannot prove that a previously submitted payment did not settle.
        UPDATE chainsql.transfers SET state='reconciliation',reason='Await authoritative network observation; prior settlement remains possible.' WHERE id=p_id;
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

CREATE TABLE chainsql.resource_approvals (
 approval_id uuid PRIMARY KEY REFERENCES chainsql.transfer_approvals(id),
 request jsonb NOT NULL, fingerprint text NOT NULL CHECK(fingerprint ~ '^[0-9a-f]{64}$')
);
CREATE TABLE chainsql.resource_results (
 transfer_id uuid PRIMARY KEY REFERENCES chainsql.transfers(id),
 payment_state text NOT NULL CHECK(payment_state IN ('pending','confirmed','failed')),
 delivery_state text NOT NULL CHECK(delivery_state IN ('pending','delivered','failed')),
 evidence jsonb NOT NULL, result jsonb, updated_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE FUNCTION chainsql._immutable_resource_v1() RETURNS trigger
LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'resource approval is immutable'; END $$;
CREATE TRIGGER immutable_resource BEFORE UPDATE OR DELETE ON chainsql.resource_approvals
FOR EACH ROW EXECUTE FUNCTION chainsql._immutable_resource_v1();
CREATE FUNCTION chainsql.approve_resource_v1(s jsonb, r jsonb) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE a uuid; k text;
BEGIN
 IF s->>'network' IS DISTINCT FROM 'eip155:84532' OR s->>'interface' IS DISTINCT FROM 'x402-eip3009-6'
 OR s->>'fee_ceiling_atomic' IS DISTINCT FROM '0' THEN RAISE EXCEPTION 'unsupported resource payment'; END IF;
 IF r IS NULL OR jsonb_typeof(r)<>'object' OR octet_length(r::text)>16384 OR (SELECT count(*) FROM jsonb_object_keys(r))<>11 THEN RAISE EXCEPTION 'invalid resource request'; END IF;
 FOREACH k IN ARRAY ARRAY['url','method','body','resource_version','resource_key','operation_fingerprint','operation_id','scheme','asset','domain_name','domain_version'] LOOP
  IF jsonb_typeof(r->k) IS DISTINCT FROM 'string' THEN RAISE EXCEPTION 'invalid resource field'; END IF;
 END LOOP;
 IF r->>'method'<>'GET' OR r->>'body'<>'' OR r->>'scheme'<>'exact'
 OR r->>'asset'<>'0x036CbD53842c5426634e7929541eC2318f3dCF7e'
 OR r->>'domain_name'<>'USDC' OR r->>'domain_version'<>'2'
 OR r->>'url' !~ '^http://127[.]0[.]0[.]1:8094/vendor-verification/[1-9][0-9]*[?]version=1$'
 OR r->>'resource_version'<>'1' OR r->>'resource_key'<>'demo-vendor-verification'
 OR r->>'operation_id' !~ '^[1-9][0-9]*$' OR r->>'operation_fingerprint' !~ '^[0-9a-f]{64}$'
 THEN RAISE EXCEPTION 'resource not in pilot egress/domain policy'; END IF;
 a:=chainsql.approve_transfer_v1(s);
 INSERT INTO chainsql.resource_approvals VALUES(a,r,encode(sha256(convert_to(jsonb_build_object('snapshot',s,'request',r)::text,'UTF8')),'hex'));
 RETURN a;
END $$;
CREATE FUNCTION chainsql.approved_resource_v1(p_tenant text,p_business text)
RETURNS TABLE(approval_id uuid,snapshot jsonb,request jsonb,fingerprint text)
LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog AS $$
 SELECT a.approval_id,a.snapshot,r.request,r.fingerprint FROM chainsql.approved_transfer_v1(p_tenant,p_business) a
 JOIN chainsql.resource_approvals r ON r.approval_id=a.approval_id
$$;
CREATE FUNCTION chainsql.request_resource_v1(p_approval uuid,p_snapshot jsonb,p_request jsonb,p_key text) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
 IF NOT EXISTS(SELECT FROM chainsql.resource_approvals WHERE approval_id=p_approval AND request=p_request) THEN RAISE EXCEPTION 'resource request changed'; END IF;
 RETURN chainsql.request_transfer_v1(p_approval,p_snapshot,p_key);
END $$;
CREATE FUNCTION chainsql.resource_material_v1(p_id uuid) RETURNS TABLE(snapshot jsonb,request jsonb,fingerprint text,ciphertext bytea,digest text)
LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog AS $$
 SELECT t.snapshot,r.request,r.fingerprint,a.ciphertext,a.digest FROM chainsql.transfers t
 JOIN chainsql.resource_approvals r ON r.approval_id=t.approval_id
 LEFT JOIN chainsql.transfer_authorizations a ON a.transfer_id=t.id WHERE t.id=p_id
$$;
CREATE FUNCTION chainsql.resource_status_v1(p_id uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE status jsonb;
BEGIN
 status:=chainsql.transfer_status_v1(p_id);
 RETURN status || jsonb_build_object('purchase',(SELECT jsonb_build_object('payment_state',payment_state,'delivery_state',delivery_state,'evidence',evidence,'result',result) FROM chainsql.resource_results WHERE transfer_id=p_id),
 'request',(SELECT r.request FROM chainsql.resource_approvals r JOIN chainsql.transfers t ON t.approval_id=r.approval_id WHERE t.id=p_id));
END $$;
CREATE FUNCTION chainsql.record_resource_v1(p_id uuid,e jsonb,r jsonb) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE t chainsql.transfers%ROWTYPE; spec chainsql.resource_approvals%ROWTYPE; old chainsql.resource_results%ROWTYPE;
BEGIN
 PERFORM chainsql._gate_v1(); SELECT * INTO STRICT t FROM chainsql.transfers WHERE id=p_id;
 SELECT * INTO STRICT spec FROM chainsql.resource_approvals WHERE approval_id=t.approval_id;
 IF e IS NULL OR jsonb_typeof(e)<>'object' OR octet_length(e::text)>16384 OR octet_length(coalesce(r::text,''))>65536
 OR e->>'fingerprint' IS DISTINCT FROM spec.fingerprint
 OR e->>'payment_state' IS NULL OR e->>'payment_state' NOT IN ('pending','confirmed','failed')
 OR e->>'delivery_state' IS NULL OR e->>'delivery_state' NOT IN ('pending','delivered','failed') THEN RAISE EXCEPTION 'invalid resource evidence'; END IF;
 IF e->>'delivery_state'='delivered' AND (r IS NULL OR e->>'payment_state'<>'confirmed') THEN RAISE EXCEPTION 'delivery requires observed payment'; END IF;
 SELECT * INTO old FROM chainsql.resource_results WHERE transfer_id=p_id;
 IF old.payment_state='confirmed' AND (e->>'payment_state'<>'confirmed' OR e->>'transaction' IS DISTINCT FROM old.evidence->>'transaction') THEN RAISE EXCEPTION 'terminal payment conflict'; END IF;
 IF old.delivery_state='delivered' AND (r IS DISTINCT FROM old.result OR e->>'delivery_state'<>'delivered') THEN RAISE EXCEPTION 'immutable delivered resource'; END IF;
 IF e->>'payment_state'='confirmed' AND old.payment_state IS DISTINCT FROM 'confirmed' THEN
  IF NOT t.reserved OR t.dispatched_at IS NULL OR e->>'transaction' IS NULL OR e->>'transaction' !~ '^0x[0-9a-fA-F]{64}$'
   OR e->>'network' IS DISTINCT FROM 'eip155:84532' OR e->>'amount' IS DISTINCT FROM t.snapshot->>'amount_atomic'
   OR e->>'recipient' IS DISTINCT FROM t.snapshot->>'destination' OR e->>'authorization_nonce' IS DISTINCT FROM '0x'||spec.fingerprint
   OR e->>'receipt_status' IS DISTINCT FROM 'success' THEN RAISE EXCEPTION 'invalid observed purchase'; END IF;
  PERFORM chainsql._release_v1(t,(t.snapshot->>'amount_atomic')::numeric,0);
  UPDATE chainsql.transfers SET state='observed',reason='Resource expense observed; vendor bill payment is separate.' WHERE id=p_id;
 END IF;
 INSERT INTO chainsql.resource_results VALUES(p_id,e->>'payment_state',e->>'delivery_state',e,r,clock_timestamp())
 ON CONFLICT(transfer_id) DO UPDATE SET payment_state=excluded.payment_state,delivery_state=excluded.delivery_state,evidence=excluded.evidence,result=excluded.result,updated_at=excluded.updated_at;
END $$;
SELECT pg_catalog.pg_extension_config_dump('chainsql.resource_approvals','');
SELECT pg_catalog.pg_extension_config_dump('chainsql.resource_results','');
REVOKE ALL ON ALL TABLES IN SCHEMA chainsql FROM PUBLIC;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA chainsql FROM PUBLIC;
