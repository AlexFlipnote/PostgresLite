import unittest
from datetime import date, datetime, timedelta, timezone, UTC

from helpers import make_sync_pool


class TestDatetimeHandlingSync(unittest.TestCase):
    def setUp(self):
        self.pool = make_sync_pool()
        self.pool.execute(
            "CREATE TABLE events ("
            "  d DATE,"
            "  dt DATETIME,"
            "  ts TIMESTAMP,"
            "  data JSON"
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

    def test_timestamp_aware_is_converted_to_utc(self):
        dt = datetime(2024, 1, 1, 12, 0, tzinfo=timezone(timedelta(hours=2)))
        self.pool.execute("INSERT INTO events (ts) VALUES (?)", dt)
        value = self.pool.fetchval("SELECT ts FROM events")
        self.assertEqual(value, dt)
        self.assertEqual(value.hour, 10)
        self.assertEqual(value.tzinfo, UTC)

    def test_current_timestamp(self):
        self.pool.execute("INSERT INTO events (ts) VALUES (CURRENT_TIMESTAMP)")
        self.assertEqual(self.pool.fetchval("SELECT ts FROM events").tzinfo, UTC)

    def test_json_roundtrip(self):
        for value in ({"a": [1, 2], "b": None}, [1, "two"]):
            self.pool.execute("DELETE FROM events")
            self.pool.execute("INSERT INTO events (data) VALUES ($1)", value)
            self.assertEqual(self.pool.fetchval("SELECT data FROM events"), value)

    def test_executemany_adapts_values(self):
        self.pool.executemany(
            "INSERT INTO events (d, data) VALUES (?, ?)",
            [(date(2024, 1, 1), {"n": 1}), (date(2024, 1, 2), {"n": 2})]
        )
        rows = self.pool.fetch("SELECT d, data FROM events ORDER BY d")
        self.assertEqual(rows[1], {"d": date(2024, 1, 2), "data": {"n": 2}})


if __name__ == "__main__":
    unittest.main()
