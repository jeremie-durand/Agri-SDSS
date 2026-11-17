-- pgSTAC access of the app role, applied by entrypoint.sh as the admin at every
-- start, in one transaction:
--   psql -v ON_ERROR_STOP=1 --single-transaction -v app_role=<role> -f <this file>
--
-- The app role reaches pgstac only through pgstac_ingest, which pgSTAC's own
-- migrations keep granted and keep away from its configuration tables.
-- CREATE is revoked from pgstac_ingest on every run because a migration grants
-- it back: pgSTAC calls PostGIS unqualified under search_path pgstac, public, so
-- a role that can create in pgstac can shadow those functions.
-- The revokes remove direct grants left by older releases or a restored dump.

GRANT pgstac_ingest TO :"app_role";
REVOKE CREATE ON SCHEMA pgstac FROM pgstac_ingest;

REVOKE ALL ON SCHEMA pgstac FROM :"app_role";
REVOKE ALL ON ALL TABLES IN SCHEMA pgstac FROM :"app_role";
REVOKE ALL ON ALL SEQUENCES IN SCHEMA pgstac FROM :"app_role";
REVOKE ALL ON ALL ROUTINES IN SCHEMA pgstac FROM :"app_role";

SELECT DISTINCT format(
    'ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA pgstac REVOKE ALL ON %s FROM %I',
    pg_get_userbyid(d.defaclrole),
    CASE d.defaclobjtype
        WHEN 'r' THEN 'TABLES'
        WHEN 'S' THEN 'SEQUENCES'
        WHEN 'f' THEN 'ROUTINES'
        WHEN 'T' THEN 'TYPES'
    END,
    :'app_role'
)
FROM pg_default_acl AS d, aclexplode(d.defaclacl) AS a
WHERE d.defaclnamespace = 'pgstac'::regnamespace
  AND a.grantee = :'app_role'::regrole
\gexec
