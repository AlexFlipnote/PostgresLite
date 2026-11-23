import os
import tempfile
import unittest
from pathlib import Path

from postgreslite import PostgresLite


class TestPostgresLiteInit(unittest.TestCase):
    def test_accepts_db_extension(self):
        db = PostgresLite("test.db")
        self.assertEqual(db._filename, "test.db")

    def test_accepts_sqlite_extensions(self):
        for name in ("test.sqlite", "test.sqlite3", "test.db3"):
            PostgresLite(name)

    def test_accepts_memory(self):
        db = PostgresLite(":memory:")
        self.assertEqual(db._filename, ":memory:")

    def test_accepts_path(self):
        db = PostgresLite(Path("data") / "test.db")
        self.assertEqual(db._filename, os.path.join("data", "test.db"))

    def test_accepts_uri(self):
        with PostgresLite("file:uri_test?mode=memory").connect() as pool:
            self.assertEqual(pool.fetchval("SELECT 1"), 1)

    def test_rejects_invalid_extension(self):
        with self.assertRaises(ValueError):
            PostgresLite("test.txt")

    def test_rejects_no_extension(self):
        with self.assertRaises(ValueError):
            PostgresLite("test")

    def test_timeout_is_applied(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = PostgresLite(os.path.join(tmp, "t.db"), timeout=0.1)
            first, second = db.connect(), db.connect()
            try:
                first.execute("CREATE TABLE t (x)")
                first.execute("BEGIN IMMEDIATE")
                with self.assertRaisesRegex(Exception, "locked"):
                    second.execute("INSERT INTO t VALUES (1)")
                first.execute("ROLLBACK")
            finally:
                first.close()
                second.close()


if __name__ == "__main__":
    unittest.main()
