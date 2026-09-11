import os
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import quote, unquote, urlencode, urlsplit, urlunsplit
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql

from app.config import DEFAULT_DATABASE_URL, Settings
from app.main import create_app


@pytest.fixture(scope="session")
def postgres_url() -> str:
    url = os.getenv("DUNCARBOX_TEST_DATABASE_URL", DEFAULT_DATABASE_URL)
    if urlsplit(url).scheme not in {"postgresql", "postgres"}:
        pytest.fail("DUNCARBOX_TEST_DATABASE_URL must be a PostgreSQL URI")
    try:
        with psycopg.connect(url, connect_timeout=5) as connection:
            connection.execute("SELECT 1")
    except psycopg.OperationalError:
        pytest.fail(
            "PostgreSQL is required: start `docker compose up -d db` or set "
            "DUNCARBOX_TEST_DATABASE_URL to a running test database.",
            pytrace=False,
        )
    return url


@pytest.fixture
def database_url(postgres_url: str) -> Iterator[str]:
    # Each test owns a newly created schema; existing application tables are never touched.
    schema_name = f"duncarbox_test_{uuid4().hex}"
    with psycopg.connect(postgres_url) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema_name)))
    parsed = urlsplit(postgres_url)
    # libpq uses URI escaping, not form encoding: a literal '+' stays a plus.
    query = {}
    for parameter in parsed.query.split("&"):
        if parameter:
            name, _, value = parameter.partition("=")
            query[unquote(name)] = unquote(value)
    query["options"] = f"{query.get('options', '')} -csearch_path={schema_name},pg_catalog".strip()
    try:
        yield urlunsplit(parsed._replace(query=urlencode(query, quote_via=quote)))
    finally:
        with psycopg.connect(postgres_url) as connection:
            connection.execute(
                sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema_name))
            )


@pytest.fixture
def settings(database_url: str) -> Settings:
    return Settings(
        database_url=database_url,
        demo_dir=Path(__file__).resolve().parents[2] / "demo",
    )


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings)) as test_client:
        yield test_client


@pytest.fixture
def order(client: TestClient) -> dict:
    return client.get("/api/v1/demo/scenarios/simple-order").json()
