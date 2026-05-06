import unittest
from datetime import date, datetime, UTC

from helpers import make_sync_pool


class TestDatetimeHandlingSync(unittest.TestCase):
    def setUp(self):
        self.pool = make_sync_pool()
        self.pool.execute(
            "CREATE TABLE events ("
            "  d DATE,"
            "  dt DATETIME,"
            "  ts TIMESTAMP"
            ")"
        )

    def tearDown(self):
        self.pool.close()

    def test_date_roundtrip(self):
        d = date(2024, 6, 15)
        self.pool.execute("INSERT INTO events (d) VALUES (?)", d)
        row = self.pool.fetchrow("SELECT d FROM events")
        self.assertEqual(row["d"], d)

    def test_datetime_roundtrip(self):
        dt = datetime(2024, 6, 15, 12, 30, 0)
        self.pool.execute("INSERT INTO events (dt) VALUES (?)", dt)
        row = self.pool.fetchrow("SELECT dt FROM events")
        self.assertEqual(row["dt"], dt)

    def test_timestamp_has_utc(self):
        dt = datetime(2024, 1, 1, 0, 0, 0)
        self.pool.execute("INSERT INTO events (ts) VALUES (?)", dt)
        row = self.pool.fetchrow("SELECT ts FROM events")
        self.assertIsNotNone(row["ts"].tzinfo)
        self.assertEqual(row["ts"].tzinfo, UTC)


if __name__ == "__main__":
    unittest.main()
