-- SPEC-003 (2026-11-11): exact money, ISO 4217 currency, workspace-defined scope (transactions).
-- Amounts move from double precision to numeric; currency codes must be three upper-case letters;
-- owner_scope (the owner's own life areas) becomes scope, a free label each workspace defines.
-- Append-only: do not edit once applied.

-- transaction
ALTER TABLE transactions.transactions NO FORCE ROW LEVEL SECURITY;
UPDATE transactions.transactions SET currency = upper(btrim(currency));
ALTER TABLE transactions.transactions FORCE ROW LEVEL SECURITY;
DO $$ DECLARE c text; BEGIN FOR c IN SELECT conname FROM pg_constraint WHERE conrelid = 'transactions.transactions'::regclass AND contype = 'c' AND conkey = ARRAY[(SELECT attnum FROM pg_attribute WHERE attrelid = 'transactions.transactions'::regclass AND attname = 'amount')] LOOP EXECUTE format('ALTER TABLE transactions.transactions DROP CONSTRAINT %I', c); END LOOP; END $$;
ALTER TABLE transactions.transactions ALTER COLUMN amount TYPE numeric(19,4) USING amount::numeric(19,4);
ALTER TABLE transactions.transactions ADD CONSTRAINT transactions_amount_check CHECK (amount >= 0);
DO $$ DECLARE c text; BEGIN FOR c IN SELECT conname FROM pg_constraint WHERE conrelid = 'transactions.transactions'::regclass AND contype = 'c' AND conkey = ARRAY[(SELECT attnum FROM pg_attribute WHERE attrelid = 'transactions.transactions'::regclass AND attname = 'currency')] LOOP EXECUTE format('ALTER TABLE transactions.transactions DROP CONSTRAINT %I', c); END LOOP; END $$;
ALTER TABLE transactions.transactions ADD CONSTRAINT transactions_currency_check CHECK (currency ~ '^[A-Z]{3}$');
ALTER TABLE transactions.transactions RENAME COLUMN owner_scope TO scope;
DO $$ DECLARE c text; BEGIN FOR c IN SELECT conname FROM pg_constraint WHERE conrelid = 'transactions.transactions'::regclass AND contype = 'c' AND conkey = ARRAY[(SELECT attnum FROM pg_attribute WHERE attrelid = 'transactions.transactions'::regclass AND attname = 'scope')] LOOP EXECUTE format('ALTER TABLE transactions.transactions DROP CONSTRAINT %I', c); END LOOP; END $$;
ALTER TABLE transactions.transactions ALTER COLUMN scope SET DEFAULT '';
ALTER TABLE transactions.transactions ADD CONSTRAINT transactions_scope_check CHECK (length(scope) <= 64);
DO $$ DECLARE i text; BEGIN SELECT indexname INTO i FROM pg_indexes WHERE schemaname = 'transactions' AND tablename = 'transactions' AND indexdef LIKE '%(workspace_id, scope)'; IF i IS NOT NULL THEN EXECUTE format('ALTER INDEX transactions.%I RENAME TO transactions_scope', i); END IF; END $$;
