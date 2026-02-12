import sqlite3
import asyncio

from .pool import PoolConnection, AsyncPoolConnection
from datetime import datetime, date, UTC

__all__ = (
    "PostgresLite",
)


class CustomCursor(sqlite3.Cursor):
    def __init__(self, *args, **kwargs):  # noqa: ANN002
        super().__init__(*args, **kwargs)


def dict_factory(cursor: sqlite3.Cursor, row: list) -> dict:
    """ Convert SQLite3 data to dict. """
    d = {}
    for index, col in enumerate(cursor.description):
        d[col[0]] = row[index]
    return d


class PostgresLite:
    def __init__(
        self,
        filename: str = "storage.db",
        loop: asyncio.AbstractEventLoop | None = None
    ):
        self._prepare_settings()
        self._filename = filename

        if filename != ":memory:" and not filename.endswith(".db"):
            raise ValueError("Database filename must end with '.db'")

        self.loop = loop or asyncio.get_event_loop()

    def connect(self) -> PoolConnection:
        """ Makes a connection to the database and returns the pool (sync). """
        conn = sqlite3.connect(
            self._filename,
            isolation_level=None,
            detect_types=sqlite3.PARSE_DECLTYPES
        )

        conn.row_factory = dict_factory
        db = conn.cursor()
        return PoolConnection(db)

    def connect_async(self) -> AsyncPoolConnection:
        """ Makes a connection to the database and returns the pool (async). """
        conn = sqlite3.connect(
            self._filename,
            isolation_level=None,
            check_same_thread=False,
            detect_types=sqlite3.PARSE_DECLTYPES
        )

        conn.row_factory = dict_factory
        db = conn.cursor()
        return AsyncPoolConnection(db, self.loop)

    def _prepare_settings(self) -> None:
        """ Prepare SQLite settings for better experience. """

        def adapt_date_iso(val: date) -> str:
            """Adapt datetime.date to ISO 8601 date."""
            return val.isoformat()

        def adapt_datetime_iso(val: datetime) -> str:
            """Adapt datetime.datetime to timezone-naive ISO 8601 date."""
            return val.isoformat()

        sqlite3.register_adapter(date, adapt_date_iso)
        sqlite3.register_adapter(datetime, adapt_datetime_iso)

        def convert_date(val: bytes) -> date:
            """Convert ISO 8601 date to datetime.date object."""
            return date.fromisoformat(val.decode())

        def convert_datetime(val: bytes) -> datetime:
            """Convert ISO 8601 datetime to datetime.datetime object."""
            return datetime.fromisoformat(val.decode())

        def convert_timestamp(val: bytes) -> datetime:
            """Convert Unix epoch timestamp to datetime.datetime object."""
            return datetime.fromisoformat(val.decode()).replace(tzinfo=UTC)

        sqlite3.register_converter("date", convert_date)
        sqlite3.register_converter("datetime", convert_datetime)
        sqlite3.register_converter("timestamp", convert_timestamp)
