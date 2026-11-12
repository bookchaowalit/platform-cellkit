-- Roles for the transactions database. Locally a superuser runs this; on Neon
-- `transactions-db provision` creates the same roles through the migrator.
--
-- transactions_migrator  owns the schema and runs migrations only.
-- transactions_api       the API at runtime: no superuser, no BYPASSRLS, owns nothing.
-- transactions_publisher sweeps and marks the outbox across workspaces; nothing else.

DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'transactions_migrator') THEN
        CREATE ROLE transactions_migrator LOGIN NOSUPERUSER NOCREATEROLE NOBYPASSRLS;
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'transactions_api') THEN
        CREATE ROLE transactions_api LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS NOINHERIT;
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'transactions_publisher') THEN
        CREATE ROLE transactions_publisher LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS NOINHERIT;
    END IF;
END
$$;
