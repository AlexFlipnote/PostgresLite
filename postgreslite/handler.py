import sqlite3

from .sqlite import PoolConnection
from datetime import datetime, date

__all__ = (
    "PostgresLite",
)


def dict_factory(cursor: sqlite3.Cursor, row: list) -> dict:
    d = {}
    for index, col in enumerate(cursor.description):
        d[col[0]] = row[index]
    return d


class PostgresLite:
    def __init__(self, filename: str = "storage.db"):
        self._prepare_settings()

        if filename != ":memory:":
            if not filename.endswith(".db"):
                raise ValueError("Database filename must end with '.db'")

        self._filename = filename

    def connect(self) -> PoolConnection:
        """ Makes a connection to the database and returns the pool (sync) """
        conn = sqlite3.connect(
            self._filename,
            isolation_level=None,
            detect_types=sqlite3.PARSE_DECLTYPES
        )

        conn.row_factory = dict_factory
        db = conn.cursor()
        return PoolConnection(db)

    async def connect_async(self) -> sqlite3.Connection:
        """ Coming soon:tm: """
        pass

    def _prepare_settings(self) -> None:
        """ Prepare SQLite settings for better experience """

        def adapt_date_iso(val) -> str:
            """Adapt datetime.date to ISO 8601 date."""
            return val.isoformat()

        def adapt_datetime_iso(val) -> str:
            """Adapt datetime.datetime to timezone-naive ISO 8601 date."""
            return val.isoformat()

        sqlite3.register_adapter(date, adapt_date_iso)
        sqlite3.register_adapter(datetime, adapt_datetime_iso)

        def convert_date(val) -> date:
            """Convert ISO 8601 date to datetime.date object."""
            return date.fromisoformat(val.decode())

        def convert_datetime(val) -> datetime:
            """Convert ISO 8601 datetime to datetime.datetime object."""
            return datetime.fromisoformat(val.decode())

        def convert_timestamp(val) -> datetime:
            """Convert Unix epoch timestamp to datetime.datetime object."""
            return datetime.fromtimestamp(int(val))

        sqlite3.register_converter("date", convert_date)
        sqlite3.register_converter("datetime", convert_datetime)
        sqlite3.register_converter("timestamp", convert_timestamp)
