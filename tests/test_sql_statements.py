import unittest

from postgreslite.pool import SQLStatements, _command_tag


class TestSQLStatements(unittest.TestCase):
    def test_plain_query_passthrough(self):
        s = SQLStatements("SELECT 1")
        self.assertEqual(s.query, "SELECT 1")
        self.assertEqual(s.prepared, ())

    def test_asyncpg_placeholder_detection(self):
        self.assertTrue(SQLStatements("SELECT $1").is_asyncpg())
        self.assertFalse(SQLStatements("SELECT ?").is_asyncpg())

    def test_asyncpg_placeholder_replacement(self):
        s = SQLStatements("INSERT INTO t VALUES ($1, $2)", "a", "b")
        self.assertEqual(s.query, "INSERT INTO t VALUES (?, ?)")
        self.assertEqual(s.prepared, ("a", "b"))

    def test_asyncpg_out_of_order_args(self):
        s = SQLStatements("SELECT $2, $1", "first", "second")
        self.assertEqual(s.prepared, ("second", "first"))

    def test_asyncpg_reused_arg(self):
        s = SQLStatements("SELECT $1, $1", "x")
        self.assertEqual(s.prepared, ("x", "x"))

    def test_positional_args_passthrough(self):
        s = SQLStatements("SELECT ? + ?", 1, 2)
        self.assertEqual(s.prepared, (1, 2))

    def test_dollar_in_string_literal_is_ignored(self):
        s = SQLStatements("SELECT '$1 off', $1 -- costs $2\n", "x")
        self.assertEqual(s.query, "SELECT '$1 off', ? -- costs $2\n")
        self.assertEqual(s.prepared, ("x",))

    def test_missing_argument_raises(self):
        with self.assertRaises(ValueError):
            _ = SQLStatements("SELECT $1, $2", "only one").prepared

    def test_values_are_adapted(self):
        s = SQLStatements("SELECT ?, ?", {"a": 1}, [1, 2])
        self.assertEqual(s.prepared, ('{"a": 1}', "[1, 2]"))


class TestCommandTag(unittest.TestCase):
    def test_dml(self):
        self.assertEqual(_command_tag("INSERT INTO t VALUES (1)", 1, 0), "INSERT 0 1")
        self.assertEqual(_command_tag("replace into t values (1)", 1, 0), "INSERT 0 1")
        self.assertEqual(_command_tag("UPDATE t SET x = 1", 3, 0), "UPDATE 3")
        self.assertEqual(_command_tag("DELETE FROM t", 2, 0), "DELETE 2")
        self.assertEqual(_command_tag("SELECT * FROM t", -1, 5), "SELECT 5")

    def test_whitespace_and_comments(self):
        self.assertEqual(_command_tag("\n  -- note\n  INSERT\nINTO t VALUES (1)", 1, 0), "INSERT 0 1")

    def test_cte(self):
        query = "WITH x AS (SELECT 1 AS id) DELETE FROM t WHERE id IN (SELECT id FROM x)"
        self.assertEqual(_command_tag(query, 1, 0), "DELETE 1")
        self.assertEqual(_command_tag("WITH x AS (SELECT 1) SELECT * FROM x", -1, 1), "SELECT 1")

    def test_ddl(self):
        self.assertEqual(_command_tag("CREATE TABLE IF NOT EXISTS t (x)", -1, 0), "CREATE TABLE")
        self.assertEqual(_command_tag("CREATE UNIQUE INDEX i ON t (x)", -1, 0), "CREATE INDEX")
        self.assertEqual(_command_tag("DROP TABLE t", -1, 0), "DROP TABLE")
        self.assertEqual(_command_tag("PRAGMA foreign_keys = ON", -1, 0), "PRAGMA")


if __name__ == "__main__":
    unittest.main()
