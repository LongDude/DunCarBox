from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import psycopg
import pytest

from app.config import DEFAULT_DATABASE_URL, Settings
from app.domain.errors import BoxConflictError
from app.domain.models import BoxType
from app.storage.boxes import PostgresBoxRepository


def test_parallel_initialization_seeds_once(database_url: str) -> None:
    box = BoxType("seed", "Коробка", 300, 200, 150, 5000, 5)
    with ThreadPoolExecutor(max_workers=8) as workers:
        list(
            workers.map(
                lambda _: PostgresBoxRepository(database_url).initialize((box,)),
                range(8),
            )
        )
    repository = PostgresBoxRepository(database_url)
    assert repository.list() == (box,)
    repository.delete(box.id)
    repository.initialize((box,))
    assert repository.list() == ()


def test_failed_seed_rolls_back_schema_and_marker(database_url: str) -> None:
    repository = PostgresBoxRepository(database_url)
    valid = BoxType("valid", "Коробка", 300, 200, 150, 5000, 5)
    invalid = replace(valid, id="invalid", available_count=-1)
    with pytest.raises(psycopg.errors.CheckViolation):
        repository.initialize((valid, invalid))
    repository.initialize((valid,))
    assert repository.list() == (valid,)


def test_conflict_rolls_back_and_next_operation_succeeds(database_url: str) -> None:
    repository = PostgresBoxRepository(database_url)
    repository.initialize()
    box = BoxType("box", "Чай 'кавычки'", 300, 200, 150, 5000, 5)
    repository.create(box)
    with pytest.raises(BoxConflictError):
        repository.create(box)
    changed = replace(box, name="Название после конфликта", available_count=0)
    assert repository.update(changed) == changed
    assert PostgresBoxRepository(database_url).list() == (changed,)


def test_catalog_order_does_not_depend_on_database_locale(database_url: str) -> None:
    repository = PostgresBoxRepository(database_url)
    ids = ["a", "Z", "a_1", "a-1", "A", "a0", "0"]
    repository.initialize(tuple(BoxType(id, id, 1, 1, 1, 1, 0) for id in ids))
    assert [box.id for box in repository.list()] == sorted(ids)


@pytest.mark.parametrize("url", ["", "file:///tmp/catalog", "mysql://localhost/catalog"])
def test_configuration_rejects_non_postgres_urls(url: str) -> None:
    with pytest.raises(ValueError, match="PostgreSQL connection URI"):
        Settings(database_url=url, demo_dir=Path("demo"))


def test_database_url_is_read_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    url = "postgresql://example:5432/catalog?sslmode=require"
    monkeypatch.setenv("DUNCARBOX_DATABASE_URL", url)
    assert Settings.from_env().database_url == url
    assert "example" not in repr(Settings.from_env())
    monkeypatch.delenv("DUNCARBOX_DATABASE_URL")
    assert Settings.from_env().database_url == DEFAULT_DATABASE_URL


def test_database_unavailable_fails_without_fallback() -> None:
    repository = PostgresBoxRepository(
        "postgresql://test@127.0.0.1:1/no_database?connect_timeout=1"
    )
    with pytest.raises(psycopg.OperationalError):
        repository.initialize()
