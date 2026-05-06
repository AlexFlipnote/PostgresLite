import sqlite3
import re
import asyncio

from contextlib import contextmanager, asynccontextmanager
from collections.abc import AsyncIterator, Iterator
from typing import Any, Self

__all__ = (
    "AsyncPoolConnection",
    "PoolConnection",
    "SQLStatements",
    "TableColumn",
)

re_asyncpg_arg = re.compile(r"\$(\d+)")
re_valid_identifier = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class TableColumn:
    __slots__ = ("default", "name", "notnull", "pk", "type")

    def __init__(self, *, name: str, type: str, notnull: bool, default: Any, pk: bool):  # noqa: ANN401, A002
        self.name = name
        self.type = type
        self.notnull = notnull
        self.default = default
        self.pk = pk

    @classmethod
    def _from_row(cls, row: dict) -> "TableColumn":
        return cls(
            name=row["name"],
            type=row["type"],
            notnull=bool(row["notnull"]),
            default=row["dflt_value"],
            pk=bool(row["pk"]),
        )

    def __repr__(self) -> str:
        return (
            f"<TableColumn name={self.name!r} type={self.type!r} "
            f"notnull={self.notnull} default={self.default}>"
        )


class SQLStatements:
    def __init__(self, query: str, *args: Any):  # noqa: ANN401
        self._raw_query = query
        self._args = args

    def is_asyncpg(self) -> bool:
        """ Check if the query is prepared for asyncpg. """
        return re_asyncpg_arg.search(self._raw_query) is not None

    @property
    def query(self) -> str:
        """ Returns the query, replacing asyncpg placeholders with SQLite placeholders. """
        return re_asyncpg_arg.sub(r"?", self._raw_query)

    @property
    def prepared(self) -> tuple:
        """ Prepare statements for SQLite with *args provided from earlier. """
        if len(self._args) <= 0:
            return ()

        if self.is_asyncpg():
            args = self._args
            return tuple(
                args[int(match.group(1)) - 1]
                for match in re_asyncpg_arg.finditer(self._raw_query)
            )

        return self._args


class PoolConnection:
    def __init__(self, pool: sqlite3.Cursor, conn: sqlite3.Connection):
        self._pool = pool
        self._conn = conn

    def __enter__(self) -> "PoolConnection":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    @property
    def lastrowid(self) -> int | None:
        """ The row ID of the last inserted row. """
        return self._pool.lastrowid

    def _init_executor(self, query: str, *args: Any) -> sqlite3.Cursor:  # noqa: ANN401
        prep = SQLStatements(query, *args)
        return self._pool.execute(prep.query, prep.prepared)

    def execute(self, query: str, *args: Any) -> str:  # noqa: ANN401
        """
        Execute SQL command with args for 'Prepared Statements'.

        Parameters
        ----------
        query:
            The query to execute.
        *args:
            The arguments to pass to the query.

        Returns
        -------
            The status of the query, e.g. "INSERT 1", "DELETE 3".
        """
        data = self._init_executor(query, *args)
        status_word = query.strip().split(" ")[0].upper()
        return f"{status_word} {max(0, data.rowcount)}"

    def fetch(self, query: str, *args: Any) -> list[dict]:  # noqa: ANN401
        """
        Fetch all rows from a query.

        Parameters
        ----------
        query:
            The query to execute.
        *args:
            The arguments to pass to the query.

        Returns
        -------
            All rows from the query.
        """
        return self._init_executor(query, *args).fetchall()

    def fetchrow(self, query: str, *args: Any) -> dict | None:  # noqa: ANN401
        """
        Fetch a single row from a query.

        Parameters
        ----------
        query:
            The query to execute.
        *args:
            The arguments to pass to the query.

        Returns
        -------
            The first row from the query, or None if no rows.
        """
        return self._init_executor(query, *args).fetchone()

    def fetchval(self, query: str, *args: Any, column: int | str = 0) -> Any:  # noqa: ANN401
        """
        Fetch a single scalar value from the first row of a query.

        Parameters
        ----------
        query:
            The query to execute.
        *args:
            The arguments to pass to the query.
        column:
            The column index or name to return (default 0).

        Returns
        -------
            The value at the given column, or None if no rows.
        """
        row = self.fetchrow(query, *args)
        if row is None:
            return None
        if isinstance(column, str):
            return row[column]
        return list(row.values())[column]

    def executemany(self, query: str, args_seq: list) -> str:
        """
        Execute a query against each item in args_seq.

        Parameters
        ----------
        query:
            The query to execute.
        args_seq:
            A list of argument tuples, one per execution.

        Returns
        -------
            The status of the final execution.
        """
        prep_query = SQLStatements(query).query
        is_asyncpg = SQLStatements(query).is_asyncpg()

        converted = (
            [SQLStatements(query, *args).prepared for args in args_seq]
            if is_asyncpg else list(args_seq)
        )

        self._pool.executemany(prep_query, converted)
        status_word = query.strip().split(" ")[0].upper()
        return f"{status_word} {max(0, self._pool.rowcount)}"

    @contextmanager
    def transaction(self) -> Iterator[Self]:
        """ Sync context manager for explicit transactions. """
        self._pool.execute("BEGIN")
        try:
            yield self
            self._pool.execute("COMMIT")
        except Exception:
            self._pool.execute("ROLLBACK")
            raise

    def run_sql(self, filename: str) -> str:
        """
        Load and execute all SQL statements from a file.

        Parameters
        ----------
        filename:
            Path to the SQL file.

        Returns
        -------
            "SCRIPT OK" on success.
        """
        with open(filename, encoding="utf-8") as f:
            query = f.read()
        self._conn.executescript(query)
        return "SCRIPT OK"

    def tables(self) -> list[str]:
        """
        Return the names of all user-defined tables in the database.

        Returns
        -------
            Table names, sorted alphabetically.
        """
        rows = self._init_executor(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
        return [row["name"] for row in rows]

    def table_columns(self, table: str) -> list[TableColumn]:
        """
        Return column information for the given table.

        Parameters
        ----------
        table:
            The table name to inspect.

        Returns
        -------
            One TableColumn per column with attributes: name, type, notnull, default, pk.
        """
        if not re_valid_identifier.match(table):
            raise ValueError(f"Invalid table name: {table!r}")
        rows = self._init_executor(f"PRAGMA table_info({table})").fetchall()
        return [TableColumn._from_row(row) for row in rows]

    def table_exists(self, table: str) -> bool:
        """
        Return whether a table exists in the database.

        Parameters
        ----------
        table:
            The table name to check.

        Returns
        -------
            True if the table exists, False otherwise.
        """
        if not re_valid_identifier.match(table):
            raise ValueError(f"Invalid table name: {table!r}")
        row = self._init_executor(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", table
        ).fetchone()
        return row is not None

    def close(self) -> None:
        """ Close the cursor and connection. """
        self._pool.close()
        self._conn.close()


class AsyncPoolConnection(PoolConnection):
    def __init__(self, pool: sqlite3.Cursor, conn: sqlite3.Connection):
        super().__init__(pool, conn)
        self._lock = asyncio.Lock()

    async def __aenter__(self) -> "AsyncPoolConnection":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    async def _run(self, fn: Any, *args: Any) -> Any:  # noqa: ANN401
        loop = asyncio.get_running_loop()
        async with self._lock:
            return await loop.run_in_executor(None, fn, *args)

    async def _init_executor(self, query: str, *args: Any) -> sqlite3.Cursor:  # noqa: ANN401
        prep = SQLStatements(query, *args)
        return await self._run(self._pool.execute, prep.query, prep.prepared)

    async def execute(self, query: str, *args: Any) -> str:  # noqa: ANN401
        """
        Execute SQL command with args for 'Prepared Statements'.

        Parameters
        ----------
        query:
            The query to execute.
        *args:
            The arguments to pass to the query.

        Returns
        -------
            The status of the query, e.g. "INSERT 1", "DELETE 3".
        """
        data = await self._init_executor(query, *args)
        status_word = query.strip().split(" ")[0].upper()
        return f"{status_word} {max(0, data.rowcount)}"

    async def fetch(self, query: str, *args: Any) -> list[dict]:  # noqa: ANN401
        """
        Fetch all rows from a query.

        Parameters
        ----------
        query:
            The query to execute.
        *args:
            The arguments to pass to the query.

        Returns
        -------
            All rows from the query.
        """
        data = await self._init_executor(query, *args)
        return data.fetchall()

    async def fetchrow(self, query: str, *args: Any) -> dict | None:  # noqa: ANN401
        """
        Fetch a single row from a query.

        Parameters
        ----------
        query:
            The query to execute.
        *args:
            The arguments to pass to the query.

        Returns
        -------
            The first row from the query, or None if no rows.
        """
        data = await self._init_executor(query, *args)
        return data.fetchone()

    async def fetchval(self, query: str, *args: Any, column: int | str = 0) -> Any:  # noqa: ANN401
        """
        Fetch a single scalar value from the first row of a query.

        Parameters
        ----------
        query:
            The query to execute.
        *args:
            The arguments to pass to the query.
        column:
            The column index or name to return (default 0).

        Returns
        -------
            The value at the given column, or None if no rows.
        """
        row = await self.fetchrow(query, *args)
        if row is None:
            return None
        if isinstance(column, str):
            return row[column]
        return list(row.values())[column]

    async def executemany(self, query: str, args_seq: list) -> str:
        """
        Execute a query against each item in args_seq.

        Parameters
        ----------
        query:
            The query to execute.
        args_seq:
            A list of argument tuples, one per execution.

        Returns
        -------
            The status of the final execution.
        """
        prep_query = SQLStatements(query).query
        is_asyncpg = SQLStatements(query).is_asyncpg()

        converted = (
            [SQLStatements(query, *args).prepared for args in args_seq]
            if is_asyncpg else list(args_seq)
        )

        await self._run(self._pool.executemany, prep_query, converted)
        status_word = query.strip().split(" ")[0].upper()
        return f"{status_word} {max(0, self._pool.rowcount)}"

    async def run_sql(self, filename: str) -> str:
        """
        Load and execute all SQL statements from a file.

        Parameters
        ----------
        filename:
            Path to the SQL file.

        Returns
        -------
            "SCRIPT OK" on success.
        """
        def _read() -> str:
            with open(filename, encoding="utf-8") as f:
                return f.read()
        content = await asyncio.to_thread(_read)
        await self._run(self._conn.executescript, content)
        return "SCRIPT OK"

    async def tables(self) -> list[str]:
        """
        Return the names of all user-defined tables in the database.

        Returns
        -------
            Table names, sorted alphabetically.
        """
        data = await self._init_executor(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
        return [row["name"] for row in data.fetchall()]

    async def table_columns(self, table: str) -> list[TableColumn]:
        """
        Return column information for the given table.

        Parameters
        ----------
        table:
            The table name to inspect.

        Returns
        -------
            One TableColumn per column with attributes: name, type, notnull, default, pk.
        """
        if not re_valid_identifier.match(table):
            raise ValueError(f"Invalid table name: {table!r}")
        data = await self._init_executor(f"PRAGMA table_info({table})")
        return [TableColumn._from_row(row) for row in data.fetchall()]

    async def table_exists(self, table: str) -> bool:
        """
        Return whether a table exists in the database.

        Parameters
        ----------
        table:
            The table name to check.

        Returns
        -------
            True if the table exists, False otherwise.
        """
        if not re_valid_identifier.match(table):
            raise ValueError(f"Invalid table name: {table!r}")
        data = await self._init_executor(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", table
        )
        return data.fetchone() is not None

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[Self]:
        """ Async context manager for explicit transactions. """
        await self.execute("BEGIN")
        try:
            yield self
            await self.execute("COMMIT")
        except Exception:
            await self.execute("ROLLBACK")
            raise

    async def close(self) -> None:
        """ Close the cursor and connection. """
        async with self._lock:
            self._pool.close()
            self._conn.close()
