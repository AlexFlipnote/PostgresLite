import sqlite3
import re
import asyncio

from typing import Any

__all__ = (
    "AsyncPoolConnection",
    "PoolConnection",
    "SQLStatements",
)

re_asyncpg_arg = re.compile(r"\$(\d+)")


class SQLStatements:
    def __init__(self, query: str, *args: Any):  # noqa: ANN401
        self._raw_query = query
        self._args = args

    def is_asyncpg(self) -> bool:
        """ Check if the query is prepared for asyncpg. """
        return re_asyncpg_arg.search(self._raw_query) is not None

    @property
    def query(self) -> str:
        """ Returns the query, and replaces asyncpg placeholders with SQLite placeholders. """
        return re_asyncpg_arg.sub(r"?", self._raw_query)

    @property
    def prepared(self) -> tuple:
        """ Prepare statements for SQLite with *args provided from earlier. """
        arg_len = len(self._args)

        if arg_len <= 0:
            return ()

        if self.is_asyncpg():
            args = self._args
            return tuple(
                args[int(match.group(1)) - 1]
                for match in re_asyncpg_arg.finditer(self._raw_query)
            )

        return self._args


class PoolConnection:
    def __init__(
        self,
        pool: sqlite3.Cursor
    ):
        self._pool = pool

    def _init_executor(self, query: str, *args: Any) -> sqlite3.Cursor:  # noqa: ANN401
        """ Initialize SQL executor with args for 'Prepared Statements'. """
        prep = SQLStatements(query, *args)
        return self._pool.execute(prep.query, prep.prepared)

    def execute(self, query: str, *args: Any) -> str:  # noqa: ANN401
        """
        Execute SQL command with args for 'Prepared Statements'.

        Parameters
        ----------
        query
            The query to execute.
        *args
            The arguments to pass to the query.

        Returns
        -------
        str
            The status of the query.
        """
        data = self._init_executor(query, *args)

        status_word = query.strip().split(" ")[0].upper()
        status_code = max(0, data.rowcount)
        if status_word == "SELECT":
            status_code = len(data.fetchall())

        return f"{status_word} {status_code}"

    def fetch(self, query: str, *args: Any) -> list[dict]:  # noqa: ANN401
        """
        Fetch DB data with args for 'Prepared Statements'.

        Parameters
        ----------
        query
            The query to execute.
        *args
            The arguments to pass to the query.

        Returns
        -------
        list[dict]
            The data from the query.
        """
        return self._init_executor(query, *args).fetchall()

    def fetchrow(self, query: str, *args: Any) -> dict:  # noqa: ANN401
        """
        Fetch DB row (one row only) with args for 'Prepared Statements'.

        Parameters
        ----------
        query
            The query to execute.
        *args
            The arguments to pass to the query.

        Returns
        -------
        dict
            The data from the query.
        """
        return self._init_executor(query, *args).fetchone()

    def run_sql(self, filename: str, *args: Any) -> str:  # noqa: ANN401
        """
        Run SQL file with args for 'Prepared Statements'.

        Parameters
        ----------
        filename
            The filename of the SQL file to execute.
        *args
            The arguments to pass to the query.

        Returns
        -------
        str
            The status of the query.
        """
        with open(filename, encoding="utf-8") as f:
            query = f.read()
        return self.execute(query, *args)


class AsyncPoolConnection(PoolConnection):
    def __init__(
        self,
        pool: sqlite3.Cursor,
        loop: asyncio.AbstractEventLoop
    ):
        super().__init__(pool)
        self.loop = loop

        self._queue = asyncio.Queue()
        self._task: asyncio.Task = self.loop.create_task(
            self._queue_manager()
        )

    async def _queue_manager(self) -> None:
        while True:
            query, args, future = await self._queue.get()

            try:
                await self._background_task(query, *args, future=future)
            except Exception:
                pass

            self._queue.task_done()

    async def _background_task(
        self,
        query: str,
        *args: Any,  # noqa: ANN401
        future: asyncio.Future
    ) -> None:
        prep = SQLStatements(query, *args)

        try:
            cursor: sqlite3.Cursor = await self.loop.run_in_executor(
                None,
                self._pool.execute,
                prep.query,
                prep.prepared
            )

            future.set_result(cursor)
        except Exception as e:
            future.set_exception(e)

    async def _init_executor(self, query: str, *args: Any) -> sqlite3.Cursor:  # noqa: ANN401
        """ Initialize SQL executor with args for 'Prepared Statements'. """
        future = self.loop.create_future()
        await self._queue.put((query, args, future))

        try:
            await future
            return future.result()
        except Exception as e:
            raise e

    @property
    def queue_size(self) -> int:
        """ Get the size of the queue. """
        return self._queue.qsize()

    async def close(self) -> None:
        """ Close the connection. """
        await self._queue.join()
        self._task.cancel()
        self._pool.close()

    async def execute(self, query: str, *args: Any) -> str:  # noqa: ANN401
        """
        Execute SQL command with args for 'Prepared Statements'.

        Parameters
        ----------
        query
            The query to execute.
        *args
            The arguments to pass to the query.

        Returns
        -------
        str
            The status of the query.
        """
        try:
            data = await self._init_executor(query, *args)
        except Exception as e:
            raise e

        status_word = query.strip().split(" ")[0].upper()
        status_code = max(0, data.rowcount)
        if status_word == "SELECT":
            status_code = len(data.fetchall())

        return f"{status_word} {status_code}"

    async def fetch(self, query: str, *args: Any) -> list:  # noqa: ANN401
        """
        Fetch DB data with args for 'Prepared Statements'.

        Parameters
        ----------
        query
            The query to execute.
        *args
            The arguments to pass to the query.

        Returns
        -------
        list[dict]
            The data from the query.
        """
        try:
            data = await self._init_executor(query, *args)
        except Exception as e:
            raise e

        return data.fetchall()

    async def fetchrow(self, query: str, *args: Any) -> dict:  # noqa: ANN401
        """
        Fetch DB row (one row only) with args for 'Prepared Statements'.

        Parameters
        ----------
        query
            The query to execute.
        *args
            The arguments to pass to the query.

        Returns
        -------
        dict
            The data from the query.
        """
        try:
            data = await self._init_executor(query, *args)
        except Exception as e:
            raise e

        return data.fetchone()
