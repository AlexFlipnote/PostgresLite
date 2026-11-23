import os
import tempfile
import unittest

from helpers import make_sync_pool
from postgreslite import PostgresLite
from postgreslite.schema import _normalize_sql


class TestNormalizeSql(unittest.TestCase):
    def test_single_line_gets_if_not_exists(self):
        self.assertEqual(
            _normalize_sql("CREATE TABLE a (id INTEGER)"),
            "CREATE TABLE IF NOT EXISTS a (id INTEGER)"
        )

    def test_multi_line_is_reindented(self):
        sql = "CREATE TABLE a (\n        id INTEGER,\n  name TEXT\n)"
        self.assertEqual(
            _normalize_sql(sql),
            "CREATE TABLE IF NOT EXISTS a (\n    id INTEGER,\n    name TEXT\n)"
        )

    def test_two_lines_have_no_blank_line(self):
        self.assertEqual(
            _normalize_sql("CREATE TABLE a (\nid INTEGER)"),
            "CREATE TABLE IF NOT EXISTS a (\nid INTEGER)"
        )

    def test_existing_if_not_exists_is_kept(self):
        sql = "CREATE TABLE IF NOT EXISTS a (id INTEGER)"
        self.assertEqual(_normalize_sql(sql), sql)

    def test_quoted_name(self):
        self.assertEqual(
            _normalize_sql('CREATE TABLE "my table" (id INTEGER)'),
            'CREATE TABLE IF NOT EXISTS "my table" (id INTEGER)'
        )

    def test_index(self):
        self.assertEqual(
            _normalize_sql("CREATE UNIQUE INDEX ix ON a (id)"),
            "CREATE UNIQUE INDEX IF NOT EXISTS ix ON a (id)"
        )


class TestDumpSchema(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = PostgresLite(os.path.join(self.tmp.name, "t.db"))
        with self.db.connect() as pool:
            pool.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT)")
            pool.execute("CREATE TABLE posts (id INTEGER PRIMARY KEY, user_id INTEGER)")
            pool.execute("CREATE INDEX ix_posts_user ON posts (user_id)")

    def tearDown(self):
        self.tmp.cleanup()

    def test_dump_is_runnable(self):
        schema = self.db.dump_schema(include_indexes=True)
        self.assertIn("CREATE INDEX IF NOT EXISTS ix_posts_user", schema)
        with self.db.connect() as pool:
            pool._conn.executescript(schema)  # Running it again on the same database must not fail

    def test_without_indexes(self):
        self.assertNotIn("INDEX", self.db.dump_schema())

    def test_file_output(self):
        path = os.path.join(self.tmp.name, "out", "schema.sql")
        schema = self.db.dump_schema(output=path)
        with open(path, encoding="utf-8") as f:
            self.assertEqual(f.read(), schema)

    def test_folder_output(self):
        folder = os.path.join(self.tmp.name, "schema")
        self.db.dump_schema(include_indexes=True, output=folder)
        self.assertEqual(sorted(os.listdir(folder)), ["posts.sql", "users.sql"])
        with open(os.path.join(folder, "posts.sql"), encoding="utf-8") as f:
            self.assertIn("ix_posts_user", f.read())

    def test_memory_database(self):
        with self.assertRaises(ValueError):
            PostgresLite(":memory:").dump_schema()
        pool = make_sync_pool()
        pool.execute("CREATE TABLE a (id INTEGER)")
        self.assertEqual(pool.dump_schema(), "CREATE TABLE IF NOT EXISTS a (id INTEGER);")
        pool.close()


if __name__ == "__main__":
    unittest.main()
