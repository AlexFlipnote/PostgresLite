import sqlite3
import asyncio

from typing import Any

__all__ = (
    "PoolConnection",
    "AsyncPoolConnection",
    "SQLStatements",
)


class SQLStatements:
    def __init__(self, *args: Any):
        self._args = args

    @property
    def prepared(self) -> tuple:
        """ Prepare statements for SQLite with *args provided from earlier """
        arg_len = len(self._args)

        print(self._args)

        if arg_len <= 0:
            return ()
        return self._args


class PoolConnection:
    def __init__(
        self,
        pool: sqlite3.Connection
    ):
        self._pool = pool

    def _init_executor(self, query: str, *args: Any) -> sqlite3.Cursor:
        """ Initialize SQL executor with args for 'Prepared Statements' """
        prep = SQLStatements(*args)
        data = self._pool.execute(query, prep.prepared)
        return data

    def execute(self, query: str, *args: Any) -> str:
        """ Execute SQL command with args for 'Prepared Statements' """
        data = self._init_executor(query, *args)

        status_word = query.split(" ")[0].strip().upper()
        status_code = data.rowcount if data.rowcount > 0 else 0
        if status_word == "SELECT":
            status_code = len(data.fetchall())

        return f"{status_word} {status_code}"

    def fetch(self, query: str, *args: Any) -> list:
        """ Fetch DB data with args for 'Prepared Statements' """
        return self._init_executor(query, *args).fetchall()

    def fetchrow(self, query: str, *args: Any) -> dict:
        """ Fetch DB row (one row only) with args for 'Prepared Statements' """
        return self._init_executor(query, *args).fetchone()


class AsyncPoolConnection(PoolConnection):
    def __init__(
        self,
        pool: sqlite3.Connection,
        loop: asyncio.AbstractEventLoop
    ):
        super().__init__(pool)
        self.loop = loop

        self._queue = asyncio.Queue()
        self._task: asyncio.Task = None

    async def _queue_manager(self):
        while True:
            query, args, future = await self._queue.get()
            try:
                await self._background_task(query, *args, future=future)
            except Exception as e:
                print(e)
            self._queue.task_done()

    async def _background_task(self, query: str, *args: Any, future: asyncio.Future) -> None:
        prep = SQLStatements(*args)

        try:
            cursor: sqlite3.Cursor = await self.loop.run_in_executor(
                None,
                self._pool.execute,
                query,
                prep.prepared
            )
            future.set_result(cursor)
        except Exception as e:
            future.set_exception(e)

    async def _init_executor(self, query: str, *args: Any) -> sqlite3.Cursor:
        """ Initialize SQL executor with args for 'Prepared Statements' """
        future = self.loop.create_future()
        await self._queue.put((query, args, future))
        return await future

    @property
    def queue_size(self) -> int:
        """ Get the size of the queue """
        return self._queue.qsize()

    async def close(self) -> None:
        """ Close the connection """
        await self._queue.join()
        self._task.cancel()
        self._pool.close()

    async def execute(self, query: str, *args: Any) -> str:
        """ Execute SQL command with args for 'Prepared Statements' """
        data = await self._init_executor(query, *args)

        status_word = query.split(" ")[0].strip().upper()
        status_code = data.rowcount if data.rowcount > 0 else 0
        if status_word == "SELECT":
            status_code = len(data.fetchall())

        return f"{status_word} {status_code}"

    async def fetch(self, query: str, *args: Any) -> list:
        """ Fetch DB data with args for 'Prepared Statements' """
        data = await self._init_executor(query, *args)
        return data.fetchall()

    async def fetchrow(self, query: str, *args: Any) -> dict:
        """ Fetch DB row (one row only) with args for 'Prepared Statements' """
        data = await self._init_executor(query, *args)
        return data.fetchone()
