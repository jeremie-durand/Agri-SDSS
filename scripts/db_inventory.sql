-- Inventory of the database, in a stable order, so that a `diff` of a run
-- before and a run after a backup restore or an upgrade shows what changed.
-- Run as the superuser, which can count every table:
--   docker compose exec -T database psql -X -f - < scripts/db_inventory.sql > "$BACKUP_DIR/inventory.txt"
-- After an upgrade, only the pgstac_version and server_version lines may differ.

\set QUIET on
\set ON_ERROR_STOP on
\pset format unaligned
\pset tuples_only on
\pset fieldsep ' | '

SELECT 'pgstac_version', pgstac.get_version();

SELECT 'server_version', current_setting('server_version_num')::int / 10000;

SELECT 'collections', count(*) FROM pgstac.collections;

SELECT 'items', collection, count(*)
FROM pgstac.items
GROUP BY collection
ORDER BY collection;

SELECT 'item_partitions', count(*)
FROM pg_partition_tree('pgstac.items')
WHERE isleaf AND level > 0;

-- The same bbox and datetime searches must return the same item ids. A count
-- equal to search_limit means the catalog outgrew it: raise the limit.
\set search_limit 1000000
SELECT 'search_limit', :search_limit;

SELECT 'search_bbox', count(*), md5(string_agg(f ->> 'id', ',' ORDER BY f ->> 'id'))
FROM jsonb_array_elements(pgstac.search(jsonb_build_object(
    'bbox', '[-80, 44, -56, 63]'::jsonb,
    'limit', :search_limit,
    'fields', '{"include": ["id"]}'::jsonb
)) -> 'features') AS f;

SELECT 'search_datetime', count(*), md5(string_agg(f ->> 'id', ',' ORDER BY f ->> 'id'))
FROM jsonb_array_elements(pgstac.search(jsonb_build_object(
    'datetime', '2015-01-01T00:00:00Z/2100-01-01T00:00:00Z',
    'limit', :search_limit,
    'fields', '{"include": ["id"]}'::jsonb
)) -> 'features') AS f;

SELECT
    'public_table',
    t.tablename,
    t.tableowner,
    'rows ' || (xpath(
        '/row/c/text()',
        query_to_xml(format('SELECT count(*) AS c FROM public.%I', t.tablename), false, true, '')
    ))[1]::text,
    'indexes ' || (SELECT count(*) FROM pg_indexes AS i
                   WHERE i.schemaname = 'public' AND i.tablename = t.tablename)
FROM pg_tables AS t
WHERE t.schemaname = 'public'
  AND NOT EXISTS (
      SELECT 1 FROM pg_depend AS d
      WHERE d.classid = 'pg_class'::regclass
        AND d.objid = format('public.%I', t.tablename)::regclass
        AND d.deptype = 'e'
  )
ORDER BY t.tablename;
