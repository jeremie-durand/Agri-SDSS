DO $$
BEGIN
  IF NOT EXISTS (
    SELECT FROM pg_catalog.pg_roles
    WHERE rolname = 'postgres') THEN

    CREATE ROLE postgres WITH LOGIN SUPERUSER PASSWORD 'changeme';
  END IF;
END
$$;
