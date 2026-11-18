#!/bin/bash
# Runs once when the PostgreSQL data directory is first initialised.
# Creates the application role (DB_USER) with least-privilege grants so
# services never connect as the postgres superuser.
#
# Required env vars in the database container:
#   POSTGRES_USER  — Docker-created superuser (used here to run psql)
#   POSTGRES_DB    — database name
#   DB_USER        — application role name (default: agri_sdss)
#   DB_PASS        — application role password (no default — must be set)
set -euo pipefail

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    -- Create (or update password of) the application role.
    DO \$\$
    BEGIN
      IF NOT EXISTS (
        SELECT FROM pg_catalog.pg_roles WHERE rolname = '${DB_USER}') THEN
        CREATE ROLE "${DB_USER}" WITH LOGIN PASSWORD '${DB_PASS}';
      ELSE
        ALTER ROLE "${DB_USER}" WITH PASSWORD '${DB_PASS}';
      END IF;
    END
    \$\$;

    -- Database-level access
    GRANT CONNECT ON DATABASE "${POSTGRES_DB}" TO "${DB_USER}";

    -- Schema: public
    -- CREATE is needed by gis-pipeline to create/replace tables during ingestion.
    GRANT USAGE, CREATE ON SCHEMA public TO "${DB_USER}";
    GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO "${DB_USER}";
    GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO "${DB_USER}";
    ALTER DEFAULT PRIVILEGES IN SCHEMA public
        GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO "${DB_USER}";
    ALTER DEFAULT PRIVILEGES IN SCHEMA public
        GRANT USAGE, SELECT ON SEQUENCES TO "${DB_USER}";

    -- Schema: pgstac — pgSTAC's own init files (990_pgstac.sh, 999_pgstac.sql)
    -- sort before this script, so the schema exists at first init. The app role
    -- reaches pgstac only through pgstac_ingest, without CREATE, as stac-api's
    -- apply_pgstac_grants.sql re-applies at every start.
    DO \$\$
    BEGIN
      IF EXISTS (
        SELECT FROM information_schema.schemata WHERE schema_name = 'pgstac') THEN
        EXECUTE format('GRANT pgstac_ingest TO %I', '${DB_USER}');
        REVOKE CREATE ON SCHEMA pgstac FROM pgstac_ingest;
      END IF;
    END
    \$\$;
EOSQL
