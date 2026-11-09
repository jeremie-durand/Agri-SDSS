"""Integration tests for PostGISManager against a live PostGIS database.

The unit tests mock the engine, so they cannot see a break between SQLAlchemy,
GeoAlchemy2, pandas and geopandas: SQLAlchemy 2.1 with GeoAlchemy2 0.18 passed
them all while every ``to_postgis`` call failed. These tests run the real write
paths on throwaway tables. They skip when PostgreSQL is unreachable; in CI the
database service is started before the suite.
"""

from collections.abc import Iterator
from uuid import uuid4

import geopandas as gpd
import pandas as pd
import psycopg
import pytest
import sqlalchemy
from gis_pipeline.core.config import Config
from gis_pipeline.modules.db.pg_utils import PostGISManager
from shapely.geometry import Point

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def postgis() -> Iterator[PostGISManager]:
    try:
        psycopg.connect(
            host=Config.POSTGRES_HOST,
            port=Config.POSTGRES_PORT,
            dbname=Config.POSTGRES_DB,
            user=Config.POSTGRES_USER,
            password=Config.POSTGRES_PASSWORD,
            connect_timeout=3,
        ).close()
    except psycopg.OperationalError as exc:
        pytest.skip(f"PostgreSQL unavailable, skipping PostGIS integration: {exc}")
    with PostGISManager() as manager:
        yield manager


@pytest.fixture
def table_name(postgis: PostGISManager) -> Iterator[str]:
    name = f"zz_it_{uuid4().hex[:8]}"
    yield name
    with postgis.engine.begin() as conn:
        conn.execute(sqlalchemy.text(f'DROP TABLE IF EXISTS public."{name}"'))


def _points(count: int) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {"name": [f"feature_{i}" for i in range(count)]},
        geometry=[Point(-72 + i * 0.1, 46) for i in range(count)],
        crs="EPSG:4326",
    )


def _scalar(postgis: PostGISManager, sql: str) -> object:
    with postgis.engine.connect() as conn:
        return conn.execute(sqlalchemy.text(sql)).scalar_one()


def test_geodataframe_replace_then_append_keeps_gids_srid_and_pk(
    postgis: PostGISManager, table_name: str
) -> None:
    postgis.insert_table_data(_points(2), table_name, override_method="replace")
    postgis.insert_table_data(
        _points(3), table_name, override_method="append", gid_offset=2
    )

    back = gpd.read_postgis(
        f'SELECT * FROM public."{table_name}" ORDER BY gid',
        postgis.engine,
        geom_col="geometry",
    )
    assert back["gid"].tolist() == [1, 2, 3, 4, 5]
    assert back.crs.to_epsg() == 4326
    assert (
        _scalar(postgis, f"SELECT Find_SRID('public', '{table_name}', 'geometry')")
        == 4326
    )
    assert (
        _scalar(
            postgis,
            "SELECT count(*) FROM pg_constraint "
            f"WHERE conrelid = 'public.\"{table_name}\"'::regclass "
            "AND contype = 'p'",
        )
        == 1
    )


def test_empty_geodataframe_creates_empty_table(
    postgis: PostGISManager, table_name: str
) -> None:
    postgis.insert_table_data(_points(0), table_name)

    assert postgis.has_table(table_name)
    assert _scalar(postgis, f'SELECT count(*) FROM public."{table_name}"') == 0


def test_dataframe_is_written_without_geometry(
    postgis: PostGISManager, table_name: str
) -> None:
    df = pd.DataFrame({"code": ["a", "b"], "value": [1.5, 2.5]})

    postgis.insert_table_data(df, table_name)

    back = pd.read_sql(
        f'SELECT * FROM public."{table_name}" ORDER BY code', postgis.engine
    )
    assert back.to_dict("records") == df.to_dict("records")


def test_cog_metadata_creates_typed_table_and_upserts(
    postgis: PostGISManager, table_name: str
) -> None:
    metadata = {
        "id": "cog_1",
        "bbox": [-73.0, 45.0, -72.0, 46.0],
        "file_url": "https://example.test/cog_1.tif",
        "metadata": {"bands": 1},
    }

    postgis.insert_cog_metadata(metadata, table_name)
    postgis.insert_cog_metadata({**metadata, "metadata": {"bands": 3}}, table_name)

    with postgis.engine.connect() as conn:
        rows = conn.execute(
            sqlalchemy.text(
                "SELECT gid, bbox, metadata, ST_SRID(geometry), "
                "GeometryType(geometry) "
                f'FROM public."{table_name}"'
            )
        ).all()
    assert rows == [("cog_1", metadata["bbox"], {"bands": 3}, 4326, "POLYGON")]


def test_insert_into_existing_table_with_fail_raises(
    postgis: PostGISManager, table_name: str
) -> None:
    postgis.insert_table_data(_points(1), table_name)

    with pytest.raises(RuntimeError, match="Error inserting"):
        postgis.insert_table_data(_points(1), table_name, override_method="fail")
