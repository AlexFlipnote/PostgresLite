import asyncio
import unittest

from postgreslite import PostgresLite


class TestAsyncPoolConnection(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.pool = PostgresLite(":memory:").connect_async()
        await self.pool.execute(
            "CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL)"
        )

    async def asyncTearDown(self):
        await self.pool.close()

    async def test_execute_returns_status(self):
        status = await self.pool.execute("INSERT INTO users (name) VALUES (?)", "Alice")
        self.assertEqual(status, "INSERT 1")

    async def test_fetch_returns_list(self):
        await self.pool.execute("INSERT INTO users (name) VALUES (?)", "Bob")
        rows = await self.pool.fetch("SELECT * FROM users")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], "Bob")

    async def test_fetchrow_returns_dict(self):
        await self.pool.execute("INSERT INTO users (name) VALUES (?)", "Carol")
        row = await self.pool.fetchrow("SELECT * FROM users WHERE name = ?", "Carol")
        self.assertIsNotNone(row)
        self.assertEqual(row["name"], "Carol")

    async def test_fetchrow_returns_none_when_missing(self):
        row = await self.pool.fetchrow("SELECT * FROM users WHERE name = ?", "Ghost")
        self.assertIsNone(row)

    async def test_fetchval_returns_scalar(self):
        await self.pool.execute("INSERT INTO users (name) VALUES (?)", "Dave")
        val = await self.pool.fetchval("SELECT name FROM users WHERE name = ?", "Dave")
        self.assertEqual(val, "Dave")

    async def test_executemany(self):
        await self.pool.executemany(
            "INSERT INTO users (name) VALUES (?)",
            [("Eve",), ("Frank",)]
        )
        rows = await self.pool.fetch("SELECT * FROM users")
        self.assertEqual(len(rows), 2)

    async def test_asyncpg_placeholders(self):
        status = await self.pool.execute("INSERT INTO users (name) VALUES ($1)", "Grace")
        self.assertEqual(status, "INSERT 1")
        row = await self.pool.fetchrow("SELECT * FROM users WHERE name = $1", "Grace")
        self.assertEqual(row["name"], "Grace")

    async def test_transaction_commit(self):
        async with self.pool.transaction():
            await self.pool.execute("INSERT INTO users (name) VALUES (?)", "Heidi")
        count = await self.pool.fetchval("SELECT COUNT(*) FROM users")
        self.assertEqual(count, 1)

    async def test_transaction_rollback(self):
        try:
            async with self.pool.transaction():
                await self.pool.execute("INSERT INTO users (name) VALUES (?)", "Ivan")
                raise RuntimeError("force rollback")
        except RuntimeError:
            pass
        count = await self.pool.fetchval("SELECT COUNT(*) FROM users")
        self.assertEqual(count, 0)

    async def test_tables(self):
        tables = await self.pool.tables()
        self.assertIn("users", tables)

    async def test_table_columns(self):
        cols = await self.pool.table_columns("users")
        names = [c.name for c in cols]
        self.assertIn("id", names)
        self.assertIn("name", names)

    async def test_table_columns_rejects_invalid_name(self):
        with self.assertRaises(ValueError):
            await self.pool.table_columns("bad; name")

    async def test_concurrent_inserts(self):
        tasks = [
            asyncio.create_task(
                self.pool.execute("INSERT INTO users (name) VALUES (?)", f"User{i}")
            )
            for i in range(10)
        ]
        results = await asyncio.gather(*tasks)
        self.assertTrue(all(r == "INSERT 1" for r in results))
        count = await self.pool.fetchval("SELECT COUNT(*) FROM users")
        self.assertEqual(count, 10)


if __name__ == "__main__":
    unittest.main()
