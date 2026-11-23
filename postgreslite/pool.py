import asyncio
import json
import os
import re
import sqlite3

from collections.abc import AsyncIterator, Callable, Iterable, Iterator, Sequence
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
from datetime import date
from typing import Any, Self, TypeVar

from .migrations import migrate, split_statements
from .schema import render_schema

__all__ = (
    "AsyncPoolConnection",
    "AsyncTransaction",
    "PoolConnection",
    "SQLStatements",
    "TableColumn",
    "Transaction",
)

T = TypeVar("T")

# Matches string literals, quoted identifiers and comments (kept as-is) or a $n placeholder (group 1)
re_asyncpg_arg = re.compile(r"""'(?:[^']|'')*'|"(?:[^"]|"")*"|--[^\n]*|/\*.*?\*/|\$(\d+)""", re.DOTALL)
# Same as above, but captures parentheses (group 1) and words (group 2) for finding the command
re_sql_word = re.compile(r"""'(?:[^']|'')*'|"(?:[^"]|"")*"|--[^\n]*|/\*.*?\*/|([()])|([A-Za-z_]+)""", re.DOTALL)

_SQL_TABLES = "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
_SQL_INDEXES = "SELECT tbl_name, sql FROM sqlite_master WHERE type='index' AND sql IS NOT NULL ORDER BY name"
_SQL_TABLE_SQL = "SELECT name, sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND sql IS NOT NULL ORDER BY name"

# Connections the current task (and the tasks it spawns) holds a transaction on
_active_transactions: ContextVar[tuple["AsyncPoolConnection", ...]] = ContextVar("postgreslite_transactions", default=())


def _adapt(value: Any) -> Any:  # noqa: ANN401
    """ Convert Python values SQLite can't store natively, without touching sqlite3's global adapters. """
    if isinstance(value, dict | list):
        return json.dumps(value)
    if isinstance(value, date):  # Also covers datetime
        return value.isoformat()
    return value


def _top_level_words(query: str) -> Iterator[str]:
    depth = 0
    for match in re_sql_word.finditer(query):
        paren, word = match.groups()
        if paren == "(":
            depth += 1
        elif paren == ")":
            depth -= 1
        elif word and depth == 0:
            yield word.upper()


def _command_tag(query: str, rowcount: int, selected: int) -> str:
    """ Build a status string the way asyncpg/PostgreSQL does, e.g. "INSERT 0 1", "UPDATE 3", "CREATE TABLE". """
    words = _top_level_words(query)
    command = next(words, "")

    if command == "WITH":
        command = next((w for w in words if w in ("INSERT", "REPLACE", "UPDATE", "DELETE", "SELECT")), "SELECT")

    match command:
        case "INSERT" | "REPLACE":
            return f"INSERT 0 {max(rowcount, 0)}"
        case "UPDATE" | "DELETE":
            return f"{command} {max(rowcount, 0)}"
        case "SELECT" | "VALUES":
            return f"SELECT {selected}"
        case "CREATE" | "DROP" | "ALTER":
            target = next((w for w in words if w in ("TABLE", "INDEX", "VIEW", "TRIGGER")), None)
            return f"{command} {target}" if target else command
        case _:
            return command


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
            f"notnull={self.notnull} default={self.default} pk={self.pk}>"
        )


class SQLStatements:
    def __init__(self, query: str, *args: Any):  # noqa: ANN401
        self._raw_query = query
        self._args = args
        self._indexes = [
            int(match.group(1))
            for match in re_asyncpg_arg.finditer(query)
            if match.group(1)
        ]

    def is_asyncpg(self) -> bool:
        """ Check if the query is prepared for asyncpg. """
        return bool(self._indexes)

    @property
    def query(self) -> str:
        """ Returns the query, replacing asyncpg placeholders with SQLite placeholders. """
        return re_asyncpg_arg.sub(
            lambda m: "?" if m.group(1) else m.group(0),
            self._raw_query
        )

    @property
    def prepared(self) -> tuple:
        """ Prepare statements for SQLite with *args provided from earlier. """
        return self.bind(self._args)

    def bind(self, args: Sequence) -> tuple:
        """
        Order and convert arguments for this query.

        Parameters
        ----------
        args:
            The arguments, in the order the query numbers them ($1, $2, …) or positionally for '?'.

        Returns
        -------
            The arguments ready to pass to SQLite.
        """
        if not self._indexes:
            return tuple(_adapt(arg) for arg in args)

        missing = max(self._indexes) - len(args)
        if missing > 0:
            raise ValueError(
                f"Query uses ${max(self._indexes)}, but only {len(args)} argument(s) were given"
            )
        return tuple(_adapt(args[index - 1]) for index in self._indexes)


class _BaseConnection:
    """ Shared, blocking implementation. The async connection runs these methods in a worker thread. """

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn
        self._lastrowid: int | None = None
        self._savepoints = 0
        self._closed = False

    @property
    def lastrowid(self) -> int | None:
        """ The row ID of the last inserted row. """
        return self._lastrowid

    def is_closed(self) -> bool:
        """ Whether the connection has been closed. """
        return self._closed

    def _next_savepoint(self) -> str:
        self._savepoints += 1
        return f"postgreslite_{self._savepoints}"

    def _query(
        self,
        query: str,
        args: Sequence,
        consume: Callable[[sqlite3.Cursor], T],
        *,
        raw: bool = False
    ) -> T:
        stmt = SQLStatements(query)
        cur = self._conn.cursor()
        try:
            if raw:
                cur.row_factory = None
            cur.execute(stmt.query, stmt.bind(args))
            result = consume(cur)
            if cur.lastrowid:
                self._lastrowid = cur.lastrowid
            return result
        finally:
            cur.close()

    def _raw(self, sql: str) -> None:
        self._conn.execute(sql).close()

    def _execute(self, query: str, args: Sequence) -> str:
        def consume(cur: sqlite3.Cursor) -> str:
            selected = len(cur.fetchall()) if cur.description else 0
            return _command_tag(query, cur.rowcount, selected)
        return self._query(query, args, consume)

    def _executemany(self, query: str, args_seq: Iterable[Sequence]) -> str:
        stmt = SQLStatements(query)
        cur = self._conn.cursor()
        try:
            cur.executemany(stmt.query, (stmt.bind(args) for args in args_seq))
            rowcount = cur.rowcount
        finally:
            cur.close()
        self._lastrowid = self._conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"] or self._lastrowid
        return _command_tag(query, rowcount, 0)

    def _fetch(self, query: str, args: Sequence) -> list[dict[str, Any]]:
        return self._query(query, args, lambda cur: cur.fetchall())

    def _fetchrow(self, query: str, args: Sequence) -> dict[str, Any] | None:
        return self._query(query, args, lambda cur: cur.fetchone())

    def _fetchval(self, query: str, args: Sequence, column: int | str) -> Any:  # noqa: ANN401
        # Integer columns read from the plain tuple, so duplicate column names don't shift the index
        row = self._query(query, args, lambda cur: cur.fetchone(), raw=isinstance(column, int))
        return None if row is None else row[column]

    def _run_sql(self, filename: str) -> str:
        with open(filename, encoding="utf-8") as f:
            script = f.read()
        # Unlike executescript(), this doesn't commit an open transaction first
        for statement in split_statements(script):
            self._raw(statement)
        return "SCRIPT OK"

    def _migrate(self, folder: str | os.PathLike[str]) -> list[str]:
        return migrate(self._conn, folder)

    def _tables(self) -> list[str]:
        return [row["name"] for row in self._fetch(_SQL_TABLES, ())]

    def _table_columns(self, table: str) -> list[TableColumn]:
        rows = self._fetch("SELECT * FROM pragma_table_info(?)", (table,))
        return [TableColumn._from_row(row) for row in rows]

    def _table_exists(self, table: str) -> bool:
        row = self._fetchrow("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,))
        return row is not None

    def _close(self) -> None:
        self._conn.close()
        self._closed = True

    def _dump_schema(self, include_indexes: bool, output: str | os.PathLike[str] | None) -> str:
        tables = [(row["name"], row["sql"]) for row in self._fetch(_SQL_TABLE_SQL, ())]
        indexes = [(row["tbl_name"], row["sql"]) for row in self._fetch(_SQL_INDEXES, ())] if include_indexes else []
        return render_schema(tables, indexes, output)


class _TransactionBase:
    def __init__(self, conn: _BaseConnection):
        self._conn = conn
        self._savepoint: str | None = None
        self._state = "new"

    def _begin_sql(self, nested: bool) -> str:
        if self._state != "new":
            raise sqlite3.InterfaceError(f"Cannot start the transaction; it is already {self._state}")
        if nested:
            self._savepoint = self._conn._next_savepoint()
            return f"SAVEPOINT {self._savepoint}"
        return "BEGIN"

    def _check_started(self) -> None:
        if self._state != "started":
            raise sqlite3.InterfaceError(f"Cannot finish the transaction; it is {self._state}")

    def _commit_sql(self) -> list[str]:
        return [f"RELEASE {self._savepoint}"] if self._savepoint else ["COMMIT"]

    def _rollback_sql(self) -> list[str]:
        if self._savepoint:
            return [f"ROLLBACK TO {self._savepoint}", f"RELEASE {self._savepoint}"]
        # SQLite rolls back by itself on some errors, so only roll back what is still open
        return ["ROLLBACK"] if self._conn._conn.in_transaction else []


class Transaction(_TransactionBase):
    """
    A transaction, or a savepoint when nested inside another one.

    Use it as a context manager, or call start(), commit() and rollback() yourself.
    """

    _conn: "PoolConnection"

    def __enter__(self) -> Self:
        self.start()
        return self

    def __exit__(self, exc_type: type[BaseException] | None, *_: object) -> None:
        if exc_type is not None:
            self.rollback()
            return
        try:
            self.commit()
        except BaseException:
            if self._state == "started":
                self.rollback()
            raise

    def start(self) -> None:
        """ Start the transaction. """
        self._conn._raw(self._begin_sql(nested=self._conn._depth > 0))
        self._conn._depth += 1
        self._state = "started"

    def commit(self) -> None:
        """ Commit the transaction. """
        self._check_started()
        for sql in self._commit_sql():
            self._conn._raw(sql)
        self._done()

    def rollback(self) -> None:
        """ Roll back the transaction. """
        self._check_started()
        try:
            for sql in self._rollback_sql():
                self._conn._raw(sql)
        finally:
            self._done()

    def _done(self) -> None:
        self._state = "done"
        self._conn._depth -= 1


class AsyncTransaction(_TransactionBase):
    """
    A transaction, or a savepoint when nested inside another one.

    While it is open, queries from other tasks wait until it is finished.
    Use it as an async context manager, or await start(), commit() and rollback() yourself.
    """

    _conn: "AsyncPoolConnection"

    def __init__(self, conn: "AsyncPoolConnection"):
        super().__init__(conn)
        self._owns_lock = False

    async def __aenter__(self) -> Self:
        await self.start()
        return self

    async def __aexit__(self, exc_type: type[BaseException] | None, *_: object) -> None:
        if exc_type is not None:
            await self.rollback()
            return
        try:
            await self.commit()
        except BaseException:
            if self._state == "started":
                await self.rollback()
            raise

    async def start(self) -> None:
        """ Start the transaction. """
        conn = self._conn
        nested = conn in _active_transactions.get()
        sql = self._begin_sql(nested=nested)

        if not nested:
            await conn._tx_lock.acquire()
            self._owns_lock = True
            _active_transactions.set((*_active_transactions.get(), conn))

        try:
            await conn._run(conn._raw, sql)
        except BaseException:
            self._release()
            raise
        self._state = "started"

    async def commit(self) -> None:
        """ Commit the transaction. """
        self._check_started()
        for sql in self._commit_sql():
            await self._conn._run(self._conn._raw, sql)
        self._done()

    async def rollback(self) -> None:
        """ Roll back the transaction. """
        self._check_started()
        try:
            for sql in self._rollback_sql():
                await self._conn._run(self._conn._raw, sql)
        finally:
            self._done()

    def _done(self) -> None:
        self._state = "done"
        self._release()

    def _release(self) -> None:
        if not self._owns_lock:
            return
        self._owns_lock = False
        _active_transactions.set(tuple(c for c in _active_transactions.get() if c is not self._conn))
        self._conn._tx_lock.release()


class PoolConnection(_BaseConnection):
    def __init__(self, conn: sqlite3.Connection):
        super().__init__(conn)
        self._depth = 0

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    @contextmanager
    def acquire(self) -> Iterator[Self]:
        """ Compatibility with asyncpg's Pool.acquire(); yields this connection. """
        yield self

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
            The status of the query, e.g. "INSERT 0 1", "DELETE 3", "CREATE TABLE".
        """
        return self._execute(query, args)

    def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:  # noqa: ANN401
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
        return self._fetch(query, args)

    def fetchrow(self, query: str, *args: Any) -> dict[str, Any] | None:  # noqa: ANN401
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
        return self._fetchrow(query, args)

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
        return self._fetchval(query, args, column)

    def executemany(self, query: str, args_seq: Iterable[Sequence]) -> str:
        """
        Execute a query against each item in args_seq.

        Parameters
        ----------
        query:
            The query to execute.
        args_seq:
            An iterable of argument tuples, one per execution.

        Returns
        -------
            The combined status of all executions, e.g. "INSERT 0 3".
        """
        return self._executemany(query, args_seq)

    def transaction(self) -> Transaction:
        """ Create a transaction, or a savepoint when already inside one. """
        return Transaction(self)

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
        return self._run_sql(filename)

    def migrate(self, folder: str | os.PathLike[str] = "migrations") -> list[str]:
        """
        Apply the .sql files in a folder that haven't been applied yet, in filename order.

        Each file runs in its own transaction and is recorded in the '_migrations' table.
        A database that already has tables but no '_migrations' table is assumed to be
        up to date: every file is recorded as applied without running it.

        Parameters
        ----------
        folder:
            Folder with migration files, e.g. '001_init.sql', '002_add_bio.sql'.

        Returns
        -------
            The names of the migrations that were applied.

        Raises
        ------
        MigrationError
            A migration failed (and was rolled back), contains its own transaction statements,
            or was changed after it was applied.
        """
        return self._migrate(folder)

    def tables(self) -> list[str]:
        """
        Return the names of all user-defined tables in the database.

        Returns
        -------
            Table names, sorted alphabetically.
        """
        return self._tables()

    def table_columns(self, table: str) -> list[TableColumn]:
        """
        Return column information for the given table.

        Parameters
        ----------
        table:
            The table name to inspect.

        Returns
        -------
            One TableColumn per column, or an empty list if the table doesn't exist.
        """
        return self._table_columns(table)

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
        return self._table_exists(table)

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
        return self._dump_schema(include_indexes, output)

    def close(self) -> None:
        """ Close the connection. """
        self._close()


class AsyncPoolConnection(_BaseConnection):
    def __init__(self, conn: sqlite3.Connection):
        super().__init__(conn)
        self._lock = asyncio.Lock()  # One statement at a time on the connection
        self._tx_lock = asyncio.Lock()  # Held by whichever task has an open transaction

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    async def _run(self, fn: Callable[..., T], *args: Any) -> T:  # noqa: ANN401
        if self in _active_transactions.get():
            return await self._run_locked(fn, *args)
        async with self._tx_lock:
            return await self._run_locked(fn, *args)

    async def _run_locked(self, fn: Callable[..., T], *args: Any) -> T:  # noqa: ANN401
        async with self._lock:
            fut = asyncio.get_running_loop().run_in_executor(None, fn, *args)
            try:
                return await asyncio.shield(fut)
            except asyncio.CancelledError:
                # Abort the running statement, and hold the lock until the
                # worker thread is done with the connection
                if not fut.done():
                    self._conn.interrupt()
                while not fut.done():
                    try:
                        await asyncio.wait([fut])
                    except asyncio.CancelledError:
                        pass
                raise

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[Self]:
        """ Compatibility with asyncpg's Pool.acquire(); yields this connection. """
        yield self

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
            The status of the query, e.g. "INSERT 0 1", "DELETE 3", "CREATE TABLE".
        """
        return await self._run(self._execute, query, args)

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:  # noqa: ANN401
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
        return await self._run(self._fetch, query, args)

    async def fetchrow(self, query: str, *args: Any) -> dict[str, Any] | None:  # noqa: ANN401
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
        return await self._run(self._fetchrow, query, args)

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
        return await self._run(self._fetchval, query, args, column)

    async def executemany(self, query: str, args_seq: Iterable[Sequence]) -> str:
        """
        Execute a query against each item in args_seq.

        Parameters
        ----------
        query:
            The query to execute.
        args_seq:
            An iterable of argument tuples, one per execution.

        Returns
        -------
            The combined status of all executions, e.g. "INSERT 0 3".
        """
        return await self._run(self._executemany, query, list(args_seq))

    def transaction(self) -> AsyncTransaction:
        """ Create a transaction, or a savepoint when already inside one. """
        return AsyncTransaction(self)

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
        return await self._run(self._run_sql, filename)

    async def migrate(self, folder: str | os.PathLike[str] = "migrations") -> list[str]:
        """
        Apply the .sql files in a folder that haven't been applied yet, in filename order.

        Each file runs in its own transaction and is recorded in the '_migrations' table.
        A database that already has tables but no '_migrations' table is assumed to be
        up to date: every file is recorded as applied without running it.

        Parameters
        ----------
        folder:
            Folder with migration files, e.g. '001_init.sql', '002_add_bio.sql'.

        Returns
        -------
            The names of the migrations that were applied.

        Raises
        ------
        MigrationError
            A migration failed (and was rolled back), contains its own transaction statements,
            or was changed after it was applied.
        """
        return await self._run(self._migrate, folder)

    async def tables(self) -> list[str]:
        """
        Return the names of all user-defined tables in the database.

        Returns
        -------
            Table names, sorted alphabetically.
        """
        return await self._run(self._tables)

    async def table_columns(self, table: str) -> list[TableColumn]:
        """
        Return column information for the given table.

        Parameters
        ----------
        table:
            The table name to inspect.

        Returns
        -------
            One TableColumn per column, or an empty list if the table doesn't exist.
        """
        return await self._run(self._table_columns, table)

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
        return await self._run(self._table_exists, table)

    async def dump_schema(self, include_indexes: bool = False, output: str | os.PathLike[str] | None = None) -> str:
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
        return await self._run(self._dump_schema, include_indexes, output)

    async def close(self) -> None:
        """ Close the connection, waiting for any open transaction to finish first. """
        await self._run(self._close)
