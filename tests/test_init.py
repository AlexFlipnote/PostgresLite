import unittest

from postgreslite import PostgresLite


class TestPostgresLiteInit(unittest.TestCase):
    def test_accepts_db_extension(self):
        db = PostgresLite("test.db")
        self.assertEqual(db._filename, "test.db")

    def test_accepts_memory(self):
        db = PostgresLite(":memory:")
        self.assertEqual(db._filename, ":memory:")

    def test_rejects_invalid_extension(self):
        with self.assertRaises(ValueError):
            PostgresLite("test.sqlite")

    def test_rejects_no_extension(self):
        with self.assertRaises(ValueError):
            PostgresLite("test")


if __name__ == "__main__":
    unittest.main()
