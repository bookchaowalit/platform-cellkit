-- Roles for the finance-accounts database. Locally a superuser runs this; on Neon
-- `finance-accounts-db provision` creates the same roles through the migrator.
--
-- finance_accounts_migrator  owns the schema and runs migrations only.
-- finance_accounts_api       the API at runtime: no superuser, no BYPASSRLS, owns nothing.
-- finance_accounts_publisher sweeps and marks the outbox across workspaces; nothing else.

DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'finance_accounts_migrator') THEN
        CREATE ROLE finance_accounts_migrator LOGIN NOSUPERUSER NOCREATEROLE NOBYPASSRLS;
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'finance_accounts_api') THEN
        CREATE ROLE finance_accounts_api LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS NOINHERIT;
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'finance_accounts_publisher') THEN
        CREATE ROLE finance_accounts_publisher LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS NOINHERIT;
    END IF;
END
$$;
