import os
import tempfile
import unittest

from helpers import make_sync_pool


class TestPoolConnectionSync(unittest.TestCase):
    def setUp(self):
        self.pool = make_sync_pool()
        self.pool.execute(
            "CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL)"
        )

    def tearDown(self):
        self.pool.close()

    def test_execute_returns_status(self):
        status = self.pool.execute("INSERT INTO users (name) VALUES (?)", "Alice")
        self.assertEqual(status, "INSERT 0 1")

    def test_execute_delete_status(self):
        self.pool.execute("INSERT INTO users (name) VALUES (?)", "Bob")
        status = self.pool.execute("DELETE FROM users WHERE name = ?", "Bob")
        self.assertEqual(status, "DELETE 1")

    def test_fetch_returns_list(self):
        self.pool.execute("INSERT INTO users (name) VALUES (?)", "Carol")
        rows = self.pool.fetch("SELECT * FROM users")
        self.assertIsInstance(rows, list)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], "Carol")

    def test_fetchrow_returns_dict(self):
        self.pool.execute("INSERT INTO users (name) VALUES (?)", "Dave")
        row = self.pool.fetchrow("SELECT * FROM users WHERE name = ?", "Dave")
        self.assertIsNotNone(row)
        self.assertEqual(row["name"], "Dave")

    def test_fetchrow_returns_none_when_missing(self):
        row = self.pool.fetchrow("SELECT * FROM users WHERE name = ?", "Ghost")
        self.assertIsNone(row)

    def test_fetchval_returns_scalar(self):
        self.pool.execute("INSERT INTO users (name) VALUES (?)", "Eve")
        val = self.pool.fetchval("SELECT name FROM users WHERE name = ?", "Eve")
        self.assertEqual(val, "Eve")

    def test_fetchval_returns_none_when_missing(self):
        val = self.pool.fetchval("SELECT name FROM users WHERE name = ?", "Ghost")
        self.assertIsNone(val)

    def test_executemany(self):
        status = self.pool.executemany(
            "INSERT INTO users (name) VALUES (?)",
            [("Frank",), ("Grace",), ("Heidi",)]
        )
        self.assertTrue(status.startswith("INSERT"))
        self.assertEqual(len(self.pool.fetch("SELECT * FROM users")), 3)

    def test_executemany_asyncpg_style(self):
        status = self.pool.executemany(
            "INSERT INTO users (name) VALUES ($1)",
            [("Ivan",), ("Judy",)]
        )
        self.assertTrue(status.startswith("INSERT"))

    def test_asyncpg_placeholders_in_execute(self):
        status = self.pool.execute("INSERT INTO users (name) VALUES ($1)", "Karl")
        self.assertEqual(status, "INSERT 0 1")
        row = self.pool.fetchrow("SELECT * FROM users WHERE name = $1", "Karl")
        self.assertEqual(row["name"], "Karl")

    def test_transaction_commit(self):
        with self.pool.transaction():
            self.pool.execute("INSERT INTO users (name) VALUES (?)", "Leo")
        self.assertEqual(self.pool.fetchval("SELECT COUNT(*) FROM users"), 1)

    def test_transaction_rollback(self):
        try:
            with self.pool.transaction():
                self.pool.execute("INSERT INTO users (name) VALUES (?)", "Mal")
                raise RuntimeError("force rollback")
        except RuntimeError:
            pass
        self.assertEqual(self.pool.fetchval("SELECT COUNT(*) FROM users"), 0)

    def test_tables(self):
        self.assertIn("users", self.pool.tables())

    def test_table_columns(self):
        cols = self.pool.table_columns("users")
        names = [c.name for c in cols]
        self.assertIn("id", names)
        self.assertIn("name", names)

    def test_table_columns_missing_table(self):
        self.assertEqual(self.pool.table_columns("drop; table"), [])

    def test_empty_fetch(self):
        rows = self.pool.fetch("SELECT * FROM users")
        self.assertEqual(rows, [])


    def test_status_tags(self):
        self.pool.execute("INSERT INTO users (name) VALUES ('a'), ('b')")
        self.assertEqual(self.pool.execute("UPDATE users SET name = name || '!'"), "UPDATE 2")
        self.assertEqual(self.pool.execute("SELECT * FROM users"), "SELECT 2")
        self.assertEqual(self.pool.execute("CREATE TABLE x (id INTEGER)"), "CREATE TABLE")
        self.assertEqual(
            self.pool.executemany("INSERT INTO x VALUES ($1)", [(1,), (2,), (3,)]),
            "INSERT 0 3"
        )

    def test_insert_returning_counts(self):
        status = self.pool.execute("INSERT INTO users (name) VALUES ('a'), ('b') RETURNING id")
        self.assertEqual(status, "INSERT 0 2")

    def test_lastrowid(self):
        self.pool.execute("INSERT INTO users (name) VALUES (?)", "a")
        self.assertEqual(self.pool.lastrowid, 1)
        self.pool.fetch("SELECT * FROM users")
        self.assertEqual(self.pool.lastrowid, 1)
        self.pool.executemany("INSERT INTO users (name) VALUES (?)", [("b",), ("c",)])
        self.assertEqual(self.pool.lastrowid, 3)

    def test_fetchval_column(self):
        self.pool.execute("INSERT INTO users (name) VALUES (?)", "a")
        self.assertEqual(self.pool.fetchval("SELECT id, name FROM users", column=1), "a")
        self.assertEqual(self.pool.fetchval("SELECT id, name FROM users", column="name"), "a")

    def test_fetchval_duplicate_column_names(self):
        self.pool.execute("INSERT INTO users (name) VALUES (?)", "a")
        val = self.pool.fetchval("SELECT 1 AS v, 2 AS v, 3 AS w", column=2)
        self.assertEqual(val, 3)

    def test_table_exists(self):
        self.assertTrue(self.pool.table_exists("users"))
        self.assertFalse(self.pool.table_exists("nope"))
        self.assertFalse(self.pool.table_exists("x'; DROP TABLE users; --"))

    def test_table_columns_quoted_name(self):
        self.pool.execute('CREATE TABLE "my-table" (id INTEGER PRIMARY KEY)')
        self.assertEqual([c.name for c in self.pool.table_columns("my-table")], ["id"])

    def test_run_sql(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "seed.sql")
            with open(path, "w", encoding="utf-8") as f:
                f.write("INSERT INTO users (name) VALUES ('a');\nINSERT INTO users (name) VALUES ('b');\n")
            self.assertEqual(self.pool.run_sql(path), "SCRIPT OK")
        self.assertEqual(self.pool.fetchval("SELECT COUNT(*) FROM users"), 2)

    def test_is_closed(self):
        pool = make_sync_pool()
        self.assertFalse(pool.is_closed())
        pool.close()
        self.assertTrue(pool.is_closed())


if __name__ == "__main__":
    unittest.main()
