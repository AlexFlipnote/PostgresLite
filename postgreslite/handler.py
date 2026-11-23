import json
import os
import sqlite3

from datetime import datetime, date, UTC

from .pool import PoolConnection, AsyncPoolConnection

__all__ = (
    "PostgresLite",
)

_EXTENSIONS = (".db", ".sqlite", ".sqlite3", ".db3")


def dict_factory(cursor: sqlite3.Cursor, row: tuple) -> dict:
    return {col[0]: value for col, value in zip(cursor.description, row, strict=True)}


def _convert_date(val: bytes) -> date:
    return date.fromisoformat(val.decode())


def _convert_datetime(val: bytes) -> datetime:
    return datetime.fromisoformat(val.decode())


def _convert_timestamp(val: bytes) -> datetime:
    dt = datetime.fromisoformat(val.decode())
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _convert_json(val: bytes) -> object:
    return json.loads(val.decode())


# sqlite3 converters are process-wide, so they're registered once here.
# They only apply to connections opened with detect_types=PARSE_DECLTYPES.
# Values going in are converted per query instead (see pool._adapt), so sqlite3's adapters are untouched.
sqlite3.register_converter("date", _convert_date)
sqlite3.register_converter("datetime", _convert_datetime)
sqlite3.register_converter("timestamp", _convert_timestamp)
sqlite3.register_converter("json", _convert_json)


class PostgresLite:
    def __init__(self, filename: str | os.PathLike[str] = "storage.db", *, timeout: float = 5.0):
        """
        Parameters
        ----------
        filename:
            Path to the database file (.db, .sqlite, .sqlite3 or .db3), a 'file:' URI, or ':memory:'.
        timeout:
            How many seconds to wait for another connection's lock before raising 'database is locked'.
        """  # noqa: D205
        self._filename = os.fspath(filename)
        self._timeout = timeout
        self._uri = self._filename.startswith("file:")

        if self._filename != ":memory:" and not self._uri and not self._filename.endswith(_EXTENSIONS):
            raise ValueError(f"Database filename must end with one of: {', '.join(_EXTENSIONS)}")

    def _connect(self, *, check_same_thread: bool) -> sqlite3.Connection:
        conn = sqlite3.connect(
            self._filename,
            timeout=self._timeout,
            isolation_level=None,
            check_same_thread=check_same_thread,
            detect_types=sqlite3.PARSE_DECLTYPES,
            uri=self._uri,
        )
        conn.row_factory = dict_factory
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def connect(self) -> PoolConnection:
        """ Makes a connection to the database and returns the pool (sync). """
        return PoolConnection(self._connect(check_same_thread=True))

    def connect_async(self) -> AsyncPoolConnection:
        """ Makes a connection to the database and returns the pool (async). """
        return AsyncPoolConnection(self._connect(check_same_thread=False))

    def dump_schema(self, include_indexes: bool = False, output: str | os.PathLike[str] | None = None) -> str:
        """
        Returns the current database schema as a SQL string.

        Parameters
        ----------
        include_indexes:
            Whether to include CREATE INDEX statements in the output (default False).
        output:
            If a path ending in '.sql', writes the full schema to that file.
            If a folder path, writes one '{table}.sql' file per table with indexes appended.
            If None, no file is written.

        Returns
        -------
            The full schema as a SQL string, regardless of output mode.
        """
        if self._filename == ":memory:":
            raise ValueError(
                "An in-memory database only exists on its own connection, "
                "use dump_schema() on that connection instead"
            )
        with self.connect() as conn:
            return conn.dump_schema(include_indexes, output)
