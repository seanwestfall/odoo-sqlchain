-- UUID audit identities survive extension-owned runtime backup/restore without a
-- separately restored identity-sequence counter.
ALTER TABLE chainsql.transfer_audit ALTER COLUMN id DROP IDENTITY;
ALTER TABLE chainsql.transfer_audit ALTER COLUMN id TYPE uuid USING gen_random_uuid();
ALTER TABLE chainsql.transfer_audit ALTER COLUMN id SET DEFAULT gen_random_uuid();
