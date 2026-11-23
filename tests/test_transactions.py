import asyncio
import os
import tempfile
import unittest

from helpers import make_sync_pool
from postgreslite import PostgresLite


class TestTransactionsSync(unittest.TestCase):
    def setUp(self):
        self.pool = make_sync_pool()
        self.pool.execute("CREATE TABLE t (x INTEGER)")

    def tearDown(self):
        self.pool.close()

    def count(self):
        return self.pool.fetchval("SELECT COUNT(*) FROM t")

    def test_nested_rollback_keeps_outer(self):
        with self.pool.transaction():
            self.pool.execute("INSERT INTO t VALUES (1)")
            try:
                with self.pool.transaction():
                    self.pool.execute("INSERT INTO t VALUES (2)")
                    raise RuntimeError
            except RuntimeError:
                pass
        self.assertEqual(self.pool.fetch("SELECT x FROM t"), [{"x": 1}])

    def test_outer_rollback_discards_nested(self):
        with self.assertRaises(RuntimeError), self.pool.transaction():
            with self.pool.transaction():
                self.pool.execute("INSERT INTO t VALUES (1)")
            raise RuntimeError
        self.assertEqual(self.count(), 0)

    def test_manual_api(self):
        tr = self.pool.transaction()
        tr.start()
        self.pool.execute("INSERT INTO t VALUES (1)")
        tr.rollback()
        self.assertEqual(self.count(), 0)

        tr = self.pool.transaction()
        tr.start()
        self.pool.execute("INSERT INTO t VALUES (1)")
        tr.commit()
        self.assertEqual(self.count(), 1)

    def test_cannot_reuse(self):
        tr = self.pool.transaction()
        with tr:
            pass
        with self.assertRaises(Exception):
            tr.start()

    def test_base_exception_rolls_back(self):
        with self.assertRaises(KeyboardInterrupt), self.pool.transaction():
            self.pool.execute("INSERT INTO t VALUES (1)")
            raise KeyboardInterrupt
        self.assertEqual(self.count(), 0)
        with self.pool.transaction():
            pass

    def test_failed_commit_rolls_back(self):
        self.pool.execute("CREATE TABLE p (id INTEGER PRIMARY KEY)")
        self.pool.execute("CREATE TABLE c (p INTEGER REFERENCES p(id) DEFERRABLE INITIALLY DEFERRED)")
        with self.assertRaises(Exception), self.pool.transaction():
            self.pool.execute("INSERT INTO c VALUES (42)")
        self.assertEqual(self.pool.fetchval("SELECT COUNT(*) FROM c"), 0)
        with self.pool.transaction():
            pass


class TestTransactionsAsync(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.pool = PostgresLite(os.path.join(self.tmp.name, "t.db")).connect_async()
        await self.pool.execute("CREATE TABLE t (x INTEGER)")

    async def asyncTearDown(self):
        await self.pool.close()
        self.tmp.cleanup()

    async def count(self):
        return await self.pool.fetchval("SELECT COUNT(*) FROM t")

    async def test_cancel_inside_transaction_rolls_back(self):
        started = asyncio.Event()

        async def work():
            async with self.pool.transaction():
                await self.pool.execute("INSERT INTO t VALUES (1)")
                started.set()
                await asyncio.sleep(10)

        task = asyncio.create_task(work())
        await started.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task

        self.assertEqual(await self.count(), 0)
        async with self.pool.transaction():
            await self.pool.execute("INSERT INTO t VALUES (2)")
        self.assertEqual(await self.count(), 1)

    async def test_other_tasks_wait_for_transaction(self):
        inside = asyncio.Event()
        release = asyncio.Event()

        async def transfer():
            async with self.pool.transaction():
                await self.pool.execute("INSERT INTO t VALUES (1)")
                inside.set()
                await release.wait()
                raise RuntimeError("rollback")

        task = asyncio.create_task(transfer())
        await inside.wait()
        # This insert must not end up inside (and be rolled back with) the other task's transaction
        outsider = asyncio.create_task(self.pool.execute("INSERT INTO t VALUES (2)"))
        await asyncio.sleep(0.05)
        self.assertFalse(outsider.done())

        release.set()
        with self.assertRaises(RuntimeError):
            await task
        await outsider
        self.assertEqual(await self.pool.fetch("SELECT x FROM t"), [{"x": 2}])

    async def test_gather_inside_transaction(self):
        async with self.pool.transaction():
            await asyncio.gather(*(
                self.pool.execute("INSERT INTO t VALUES ($1)", i)
                for i in range(5)
            ))
        self.assertEqual(await self.count(), 5)

    async def test_nested_rollback_keeps_outer(self):
        async with self.pool.transaction():
            await self.pool.execute("INSERT INTO t VALUES (1)")
            try:
                async with self.pool.transaction():
                    await self.pool.execute("INSERT INTO t VALUES (2)")
                    raise RuntimeError
            except RuntimeError:
                pass
        self.assertEqual(await self.pool.fetch("SELECT x FROM t"), [{"x": 1}])

    async def test_acquire_like_asyncpg(self):
        async with self.pool.acquire() as conn, conn.transaction():
            await conn.execute("INSERT INTO t VALUES (1)")
        self.assertEqual(await self.count(), 1)
        self.assertFalse(self.pool.is_closed())


if __name__ == "__main__":
    unittest.main()
