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

    -- Schema: pgstac — created by the pgSTAC Docker image AFTER this script runs.
    -- Grants are applied here only if the schema already exists (re-runs / manual invocation).
    -- On first init the schema won't exist yet; stac-api connects as the postgres
    -- superuser so it can access pgstac without needing explicit grants here.
    DO \$\$
    BEGIN
      IF EXISTS (
        SELECT FROM information_schema.schemata WHERE schema_name = 'pgstac') THEN

        EXECUTE format('GRANT USAGE ON SCHEMA pgstac TO %I', '${DB_USER}');
        EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA pgstac TO %I', '${DB_USER}');
        EXECUTE format('GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA pgstac TO %I', '${DB_USER}');
        EXECUTE format('GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA pgstac TO %I', '${DB_USER}');
        EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA pgstac GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO %I', '${DB_USER}');
        EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA pgstac GRANT USAGE, SELECT ON SEQUENCES TO %I', '${DB_USER}');

      END IF;
    END
    \$\$;
EOSQL
