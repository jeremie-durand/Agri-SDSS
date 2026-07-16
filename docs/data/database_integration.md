# Integrating with an Existing PostgreSQL Database

Agri-SDSS runs its own dedicated PostGIS instance and receives data *from* the organizational database — it does not share or replace it. This guide explains why, and how to set up the connection. For adding file-based or API data sources, see [Adding new data](adding_new_data.md).

## Why Agri-SDSS keeps a dedicated database

This mirrors the standard pattern in comparable platforms (eoAPI/pgSTAC deployments, enterprise GIS): a dedicated serving database fed from the source systems, never a shared one.

- **Load isolation** — pipeline runs generate heavy insert bursts and sustained tile traffic can push the database to its CPU ceiling (measured during load tests). On a shared instance, that load would slow the business application.
- **Independent lifecycles** — pgSTAC owns its schema and migrations; Agri-SDSS upgrades PostgreSQL/PostGIS/pgSTAC at its own pace without locking the organizational database to the same versions.
- **Exposure** — Agri-SDSS is Internet-facing through its APIs. Its database can be overloaded or compromised without touching the organizational database, which stays internal.
- **Consumers don't need DB access** — systems that want Agri-SDSS data consume its HTTP APIs (OGC API Features at `/vector-api/`, tiles at `/raster-api/`, STAC at `/stac-api/`), which survive schema changes that would break database-level coupling.

## Agri-SDSS database facts

Everything below assumes these characteristics of the Agri-SDSS `database` service (pgSTAC image):

| Property | Value |
| --- | --- |
| Extensions | `postgis`, `btree_gist`, `unaccent`, `plpgsql` + `pgstac` schema (via pypgstac migrations) |
| `wal_level` | `replica` — fine to *subscribe* to an external publication |
| Network exposure | Port bound to `127.0.0.1` on the host by design ([security checklist](../DEPLOYMENT.md#6-security-checklist)) |

## Feeding Agri-SDSS from the organizational database

Replaces the manual [production dump restore](../DEPLOYMENT.md#8-restoring-a-production-database-dump) with a continuous or scheduled flow. Three techniques, from most to least "seamless":

### Logical replication

Native PostgreSQL publication/subscription. Rows flow automatically after an initial copy; local indexes and PostGIS geometries work normally, so vector-api serves replicated tables at full speed.

On the **source** database (requires PostgreSQL ≥ 10, same or older major version than Agri-SDSS's 15):

```sql
-- postgresql.conf: wal_level = logical  (restart required)
CREATE ROLE agri_sdss_repl WITH REPLICATION LOGIN PASSWORD '...';
GRANT SELECT ON my_table TO agri_sdss_repl;
CREATE PUBLICATION agri_sdss_pub FOR TABLE my_table;
```

On the **Agri-SDSS** database (as superuser):

```sql
-- Schema first — DDL is not replicated:
--   pg_dump -h source -t my_table --schema-only | psql ...
CREATE SUBSCRIPTION agri_sdss_sub
  CONNECTION 'host=<source-host> dbname=<db> user=agri_sdss_repl password=...'
  PUBLICATION agri_sdss_pub;
GRANT SELECT ON my_table TO agri_sdss;
CREATE INDEX ON my_table USING GIST (geometry);
```

Caveats: every replicated table needs a primary key (replica identity); DDL changes on the source must be applied manually on both sides; the initial copy of large tables generates sustained insert load (see the database memory notes in [DEPLOYMENT.md](../DEPLOYMENT.md#server-sizing)).

### Foreign data wrapper (live remote reads, no copy)

`postgres_fdw` exposes remote tables as local ones. Good for occasional joins and ad-hoc analysis; poor for map serving, because every tile or feature request round-trips to the remote server.

```sql
CREATE EXTENSION postgres_fdw;
CREATE SERVER org_db FOREIGN DATA WRAPPER postgres_fdw
  OPTIONS (host '<source-host>', dbname '<db>');
CREATE USER MAPPING FOR agri_sdss SERVER org_db
  OPTIONS (user '...', password '...');
IMPORT FOREIGN SCHEMA public LIMIT TO (my_table) FROM SERVER org_db INTO public;
```

To serve FDW data through vector-api, materialize it locally and refresh on a schedule:

```sql
CREATE MATERIALIZED VIEW my_table_local AS SELECT * FROM my_table;
CREATE INDEX ON my_table_local USING GIST (geometry);
-- cron: REFRESH MATERIALIZED VIEW CONCURRENTLY my_table_local;
```

### Scheduled dump/restore (batch)

The existing [section 8 procedure](../DEPLOYMENT.md#8-restoring-a-production-database-dump), narrowed to selected tables (`pg_dump -t my_table`) and run from cron. Simplest to operate; freshness is the cron interval.

## Connection direction

Everything above is one-way, in both data and network terms:

- **Data** flows organizational DB → Agri-SDSS only. Replicated (or foreign) tables must be treated as read-only inside Agri-SDSS: local writes to them are never sent back, and on a replicated table they would conflict with incoming changes.
- **Network**: the connection is opened *by* Agri-SDSS — the subscriber (or FDW client) dials out to the source. The organizational database never needs to reach the Agri-SDSS database, whose port stays bound to `127.0.0.1`.

The reverse direction (the organizational database subscribing to Agri-SDSS tables) uses the same steps with the roles swapped, plus two changes on the Agri-SDSS side: add `-c wal_level=logical` to the `database` command in `docker-compose.yml`, and make the database port reachable on the private network. Before going there, consider the HTTP APIs instead (see [Why Agri-SDSS keeps a dedicated database](#why-agri-sdss-keeps-a-dedicated-database)). In all cases, avoid replicating the same table in both directions — each table should have a single writing side.

## Security notes

- Never expose PostgreSQL (5432/5439) on the public internet. Use a private network, VPN, or SSH tunnel between the two servers; the compose file binds the DB to `127.0.0.1` on purpose.
- Use a dedicated least-privilege role for replication or FDW (like `agri_sdss_repl` above) — never the superuser, and never the `agri_sdss` app role of the other side.
- Credentials for cross-database connections belong in `.env` (git-ignored), like every other secret in this repo.
