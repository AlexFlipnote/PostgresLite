import sqlite3


def dict_factory(cursor, row) -> dict:
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

    def _init_executor(self, query: str, arguments: list) -> sqlite3.Cursor:
        """ Initialize SQL executor with args for 'Prepared Statements' """
        prep = SQLStatements(arguments)
        data = self.db.execute(query, prep.prepared)
        return data

    def execute(self, query: str, *args) -> str:
        """ Execute SQL command with args for 'Prepared Statements' """
        data = self._init_executor(query, [g for g in args])

        status_word = query.split(' ')[0].upper()
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
