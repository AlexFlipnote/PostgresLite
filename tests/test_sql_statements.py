import unittest

from postgreslite.pool import SQLStatements


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

    def test_positional_args_passthrough(self):
        s = SQLStatements("SELECT ? + ?", 1, 2)
        self.assertEqual(s.prepared, (1, 2))


if __name__ == "__main__":
    unittest.main()
