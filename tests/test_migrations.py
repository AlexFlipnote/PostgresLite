import os
import tempfile
import unittest

from postgreslite import MigrationError, PostgresLite
from postgreslite.migrations import split_statements


class TestSplitStatements(unittest.TestCase):
    def test_semicolons_in_literals_comments_and_triggers(self):
        script = (
            "-- setup; first\n"
            "CREATE TABLE a (x TEXT DEFAULT 'a;b');\n"
            "/* ; */ CREATE TRIGGER t AFTER INSERT ON a BEGIN UPDATE a SET x = 'y;'; END;\n"
            "INSERT INTO a VALUES ('z')\n"
            "-- trailing comment"
        )
        self.assertEqual(list(split_statements(script)), [
            "-- setup; first\nCREATE TABLE a (x TEXT DEFAULT 'a;b');",
            "/* ; */ CREATE TRIGGER t AFTER INSERT ON a BEGIN UPDATE a SET x = 'y;'; END;",
            "INSERT INTO a VALUES ('z')\n-- trailing comment",
        ])

    def test_empty_statements_are_skipped(self):
        self.assertEqual(list(split_statements(" ;; \n SELECT 1;\n\n")), ["SELECT 1;"])


class TestMigrations(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = os.path.join(self.tmp.name, "migrations")
        os.makedirs(self.folder)
        self.pool = PostgresLite(os.path.join(self.tmp.name, "t.db")).connect()

    def tearDown(self):
        self.pool.close()
        self.tmp.cleanup()

    def write(self, name, sql):
        with open(os.path.join(self.folder, name), "w", encoding="utf-8") as f:
            f.write(sql)

    def applied(self):
        return [row["name"] for row in self.pool.fetch("SELECT name FROM _migrations ORDER BY name")]

    def test_applies_in_order_and_only_once(self):
        self.write("002_add_bio.sql", "ALTER TABLE users ADD COLUMN bio TEXT;")
        self.write("001_init.sql", "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT);")
        self.write("notes.txt", "not a migration")

        self.assertEqual(self.pool.migrate(self.folder), ["001_init.sql", "002_add_bio.sql"])
        self.assertEqual(self.pool.migrate(self.folder), [])
        self.assertEqual([c.name for c in self.pool.table_columns("users")], ["id", "name", "bio"])

        self.write("003_index.sql", "CREATE INDEX ix_users_name ON users (name);")
        self.assertEqual(self.pool.migrate(self.folder), ["003_index.sql"])
        self.assertEqual(len(self.applied()), 3)

    def test_existing_database_is_baselined(self):
        self.pool.execute("CREATE TABLE users (id INTEGER PRIMARY KEY)")
        self.write("001_init.sql", "CREATE TABLE users (id INTEGER PRIMARY KEY);")
        self.write("002_posts.sql", "CREATE TABLE posts (id INTEGER PRIMARY KEY);")

        self.assertEqual(self.pool.migrate(self.folder), [])
        self.assertEqual(self.applied(), ["001_init.sql", "002_posts.sql"])
        self.assertFalse(self.pool.table_exists("posts"))

        self.write("003_tags.sql", "CREATE TABLE tags (id INTEGER PRIMARY KEY);")
        self.assertEqual(self.pool.migrate(self.folder), ["003_tags.sql"])

    def test_failed_migration_rolls_back(self):
        self.write("001_init.sql", "CREATE TABLE users (id INTEGER PRIMARY KEY);")
        self.write("002_broken.sql", "CREATE TABLE posts (id INTEGER);\nINSERT INTO nope VALUES (1);")

        with self.assertRaisesRegex(MigrationError, "002_broken.sql failed"):
            self.pool.migrate(self.folder)
        self.assertEqual(self.applied(), ["001_init.sql"])
        self.assertFalse(self.pool.table_exists("posts"))

        self.write("002_broken.sql", "CREATE TABLE posts (id INTEGER);")
        self.assertEqual(self.pool.migrate(self.folder), ["002_broken.sql"])

    def test_transaction_statements_are_rejected(self):
        self.write("001_init.sql", "CREATE TABLE users (id INTEGER);\nCOMMIT;\nCREATE TABLE posts (id INTEGER);")
        with self.assertRaisesRegex(MigrationError, "must not contain BEGIN"):
            self.pool.migrate(self.folder)
        self.assertFalse(self.pool.table_exists("users"))
        self.assertEqual(self.applied(), [])

    def test_changed_migration_is_rejected(self):
        self.write("001_init.sql", "CREATE TABLE users (id INTEGER);")
        self.pool.migrate(self.folder)

        self.write("001_init.sql", "CREATE TABLE users (id INTEGER, name TEXT);")
        self.write("002_posts.sql", "CREATE TABLE posts (id INTEGER);")
        with self.assertRaisesRegex(MigrationError, "001_init.sql was changed"):
            self.pool.migrate(self.folder)
        self.assertFalse(self.pool.table_exists("posts"))

    def test_line_endings_dont_count_as_changes(self):
        self.write("001_init.sql", "CREATE TABLE users (\n    id INTEGER\n);\n")
        self.pool.migrate(self.folder)
        with open(os.path.join(self.folder, "001_init.sql"), "w", encoding="utf-8", newline="\r\n") as f:
            f.write("CREATE TABLE users (\n    id INTEGER\n);\n")
        self.assertEqual(self.pool.migrate(self.folder), [])

    def test_table_rebuild_does_not_cascade(self):
        self.write("001_init.sql", (
            "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT);\n"
            "CREATE TABLE posts (id INTEGER PRIMARY KEY, user_id INTEGER REFERENCES users(id) ON DELETE CASCADE);"
        ))
        self.pool.migrate(self.folder)
        self.pool.execute("INSERT INTO users VALUES (1, 'a')")
        self.pool.execute("INSERT INTO posts VALUES (1, 1)")

        # SQLite's recommended way to change a column: rebuild the table
        self.write("002_rebuild_users.sql", (
            "CREATE TABLE users_new (id INTEGER PRIMARY KEY, name TEXT NOT NULL);\n"
            "INSERT INTO users_new SELECT id, name FROM users;\n"
            "DROP TABLE users;\n"
            "ALTER TABLE users_new RENAME TO users;"
        ))
        self.assertEqual(self.pool.migrate(self.folder), ["002_rebuild_users.sql"])
        self.assertEqual(self.pool.fetchval("SELECT COUNT(*) FROM posts"), 1)
        self.assertEqual(self.pool.fetchval("PRAGMA foreign_keys"), 1)

    def test_foreign_key_violations_are_rejected(self):
        self.write("001_init.sql", (
            "CREATE TABLE users (id INTEGER PRIMARY KEY);\n"
            "CREATE TABLE posts (id INTEGER PRIMARY KEY, user_id INTEGER REFERENCES users(id));"
        ))
        self.write("002_bad_data.sql", "INSERT INTO posts VALUES (1, 42);")
        with self.assertRaisesRegex(MigrationError, "foreign key violations in: posts"):
            self.pool.migrate(self.folder)
        self.assertEqual(self.pool.fetchval("SELECT COUNT(*) FROM posts"), 0)
        self.assertEqual(self.pool.fetchval("PRAGMA foreign_keys"), 1)

    def test_inside_transaction_is_rejected(self):
        with self.assertRaises(MigrationError), self.pool.transaction():
            self.pool.migrate(self.folder)

    def test_missing_folder(self):
        with self.assertRaises(FileNotFoundError):
            self.pool.migrate(os.path.join(self.tmp.name, "nope"))


class TestMigrationsAsync(unittest.IsolatedAsyncioTestCase):
    async def test_migrate(self):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "001_init.sql"), "w", encoding="utf-8") as f:
                f.write("CREATE TABLE users (id INTEGER PRIMARY KEY);")
            async with PostgresLite(":memory:").connect_async() as pool:
                self.assertEqual(await pool.migrate(tmp), ["001_init.sql"])
                self.assertTrue(await pool.table_exists("users"))


class TestRunSqlInTransaction(unittest.TestCase):
    def test_run_sql_does_not_commit_open_transaction(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "seed.sql")
            with open(path, "w", encoding="utf-8") as f:
                f.write("INSERT INTO t VALUES (1);\nINSERT INTO t VALUES (2);")

            with PostgresLite(":memory:").connect() as pool:
                pool.execute("CREATE TABLE t (x INTEGER)")
                with self.assertRaises(RuntimeError), pool.transaction():
                    pool.run_sql(path)
                    raise RuntimeError
                self.assertEqual(pool.fetchval("SELECT COUNT(*) FROM t"), 0)


if __name__ == "__main__":
    unittest.main()
