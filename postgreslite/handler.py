import sqlite3
import datetime


def dict_factory(cursor: sqlite3.Cursor, row: list) -> dict:
    d = {}
    for index, col in enumerate(cursor.description):
        d[col[0]] = row[index]
    return d


class SQLStatements:
    def __init__(self, arguments: list):
        self.arguments = arguments

    @property
    def prepared(self) -> tuple:
        """ Prepare statements for SQLite with *args provided from earlier"""
        arg_len = len(self.arguments)

        if arg_len <= 0:
            return ()
        elif arg_len == 1:
            return (self.arguments[0],)
        else:
            return tuple(self.arguments)


class PostgresLite:
    def __init__(self, filename: str = "storage.db"):
        self._prepare_settings()

        if filename != ":memory:":
            if not filename.endswith(".db"):
                raise ValueError("Database filename must end with '.db'")

        self.conn = sqlite3.connect(
            filename,
            isolation_level=None,
            detect_types=sqlite3.PARSE_DECLTYPES
        )

        self.conn.row_factory = dict_factory
        self.db = self.conn.cursor()

    def _prepare_settings(self):
        def adapt_date_iso(val):
            """Adapt datetime.date to ISO 8601 date."""
            return val.isoformat()

        def adapt_datetime_iso(val):
            """Adapt datetime.datetime to timezone-naive ISO 8601 date."""
            return val.isoformat()

        sqlite3.register_adapter(datetime.date, adapt_date_iso)
        sqlite3.register_adapter(datetime.datetime, adapt_datetime_iso)

        def convert_date(val):
            """Convert ISO 8601 date to datetime.date object."""
            return datetime.date.fromisoformat(val.decode())

        def convert_datetime(val):
            """Convert ISO 8601 datetime to datetime.datetime object."""
            return datetime.datetime.fromisoformat(val.decode())

        def convert_timestamp(val):
            """Convert Unix epoch timestamp to datetime.datetime object."""
            return datetime.datetime.fromtimestamp(int(val))

        sqlite3.register_converter("date", convert_date)
        sqlite3.register_converter("datetime", convert_datetime)
        sqlite3.register_converter("timestamp", convert_timestamp)

    def _init_executor(self, query: str, arguments: list) -> sqlite3.Cursor:
        """ Initialize SQL executor with args for 'Prepared Statements' """
        prep = SQLStatements(arguments)
        data = self.db.execute(query, prep.prepared)
        return data

    def execute(self, query: str, *args) -> str:
        """ Execute SQL command with args for 'Prepared Statements' """
        data = self._init_executor(query, [g for g in args])

        status_word = query.split(' ')[0].strip().upper()
        status_code = data.rowcount if data.rowcount > 0 else 0
        if status_word == "SELECT":
            status_code = len(data.fetchall())

        return f"{status_word} {status_code}"

    def fetch(self, query: str, *args) -> list:
        """ Fetch DB data with args for 'Prepared Statements' """
        data = self._init_executor(query, args).fetchall()
        return data

    def fetchrow(self, query: str, *args) -> dict:
        """ Fetch DB row (one row only) with args for 'Prepared Statements' """
        data = self._init_executor(query, args).fetchone()
        return data
