-- Database triggers cover ORM writes, stored balance recomputation, and direct SQL.
-- They revoke authority in the same transaction as the material source-data change.
-- These are Odoo-owned adapter triggers, not part of the ERP-independent extension.
CREATE OR REPLACE FUNCTION public.chainsql_resource_bill_changed() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
    IF ROW(NEW.company_id,NEW.partner_id,NEW.currency_id,NEW.state,NEW.amount_total,NEW.amount_residual,
           NEW.ref,NEW.name,NEW.invoice_date_due,NEW.chainsql_wallet_id)
       IS DISTINCT FROM
       ROW(OLD.company_id,OLD.partner_id,OLD.currency_id,OLD.state,OLD.amount_total,OLD.amount_residual,
           OLD.ref,OLD.name,OLD.invoice_date_due,OLD.chainsql_wallet_id) THEN
        PERFORM chainsql.invalidate_business_v1('odoo:'||current_database()||':'||OLD.company_id::text||':x402','account.move:'||OLD.id::text);
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER chainsql_resource_bill_changed AFTER UPDATE ON account_move
FOR EACH ROW EXECUTE FUNCTION public.chainsql_resource_bill_changed();
CREATE OR REPLACE FUNCTION public.chainsql_resource_wallet_changed() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE bill record;
BEGIN
    IF ROW(NEW.recipient,NEW.network,NEW.asset,NEW.version,NEW.state,NEW.partner_id)
       IS DISTINCT FROM ROW(OLD.recipient,OLD.network,OLD.asset,OLD.version,OLD.state,OLD.partner_id) THEN
        FOR bill IN SELECT id,company_id FROM public.account_move WHERE chainsql_wallet_id=OLD.id LOOP
            PERFORM chainsql.invalidate_business_v1('odoo:'||current_database()||':'||bill.company_id::text||':x402','account.move:'||bill.id::text);
        END LOOP;
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER chainsql_resource_wallet_changed AFTER UPDATE ON chainsql_wallet_approval
FOR EACH ROW EXECUTE FUNCTION public.chainsql_resource_wallet_changed();
REVOKE ALL ON FUNCTION public.chainsql_resource_bill_changed(),public.chainsql_resource_wallet_changed() FROM PUBLIC;