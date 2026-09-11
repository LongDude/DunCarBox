from typing import Protocol

import psycopg
from psycopg.errors import UniqueViolation
from psycopg.rows import DictRow, dict_row

from app.domain.errors import BoxConflictError, BoxNotFoundError
from app.domain.models import BoxType


class BoxRepository(Protocol):
    def list(self) -> tuple[BoxType, ...]: ...
    def create(self, box: BoxType) -> BoxType: ...
    def update(self, box: BoxType) -> BoxType: ...
    def delete(self, box_id: str) -> None: ...


class PostgresBoxRepository:
    """One short-lived connection per operation; no shared connection across threads."""

    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    def _connect(self) -> psycopg.Connection[DictRow]:
        return psycopg.connect(self._database_url, row_factory=dict_row, connect_timeout=5)

    def initialize(self, seed: tuple[BoxType, ...] = ()) -> None:
        with self._connect() as connection:
            # Serialize schema setup and seed across concurrent application startups.
            # PostgreSQL releases this lock at transaction commit or rollback.
            connection.execute(
                "SELECT pg_advisory_xact_lock(hashtext('duncarbox_catalog_init_v1'))"
            )
            connection.execute("""
                CREATE TABLE IF NOT EXISTS boxes (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL,
                    length INTEGER NOT NULL CHECK (length > 0),
                    width INTEGER NOT NULL CHECK (width > 0),
                    height INTEGER NOT NULL CHECK (height > 0),
                    max_weight INTEGER NOT NULL CHECK (max_weight > 0),
                    available_count INTEGER NOT NULL CHECK (available_count >= 0)
                )
            """)
            connection.execute("CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY)")
            # Reserve the seed marker and insert rows in the same transaction.
            first_start = connection.execute(
                "INSERT INTO metadata (key) VALUES ('catalog_seed_v1') "
                "ON CONFLICT (key) DO NOTHING RETURNING key"
            ).rowcount
            if first_start:
                with connection.cursor() as cursor:
                    cursor.executemany(
                        "INSERT INTO boxes "
                        "(id, name, length, width, height, max_weight, available_count) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT (id) DO NOTHING",
                        [self._values(box) for box in seed],
                    )

    @staticmethod
    def _values(box: BoxType) -> tuple[str | int, ...]:
        return (
            box.id,
            box.name,
            box.length,
            box.width,
            box.height,
            box.max_weight,
            box.available_count,
        )

    def list(self) -> tuple[BoxType, ...]:
        with self._connect() as connection:
            return tuple(
                BoxType(**dict(row))
                for row in connection.execute(
                    "SELECT id, name, length, width, height, max_weight, available_count "
                    'FROM boxes ORDER BY id COLLATE "C"'
                )
            )

    def create(self, box: BoxType) -> BoxType:
        try:
            with self._connect() as connection:
                connection.execute(
                    "INSERT INTO boxes "
                    "(id, name, length, width, height, max_weight, available_count) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    self._values(box),
                )
        except UniqueViolation as exc:
            raise BoxConflictError(box.id) from exc
        return box

    def update(self, box: BoxType) -> BoxType:
        with self._connect() as connection:
            changed = connection.execute(
                "UPDATE boxes SET name=%s, length=%s, width=%s, height=%s, "
                "max_weight=%s, available_count=%s WHERE id=%s",
                (*self._values(box)[1:], box.id),
            ).rowcount
            if not changed:
                raise BoxNotFoundError(box.id)
        return box

    def delete(self, box_id: str) -> None:
        with self._connect() as connection:
            if not connection.execute("DELETE FROM boxes WHERE id=%s", (box_id,)).rowcount:
                raise BoxNotFoundError(box_id)
