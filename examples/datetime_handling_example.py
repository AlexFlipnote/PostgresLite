from datetime import date, datetime
from postgreslite import PostgresLite

pool = PostgresLite(":memory:").connect()

pool.execute("""
    CREATE TABLE events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        event_date DATE,
        created_at DATETIME,
        updated_at TIMESTAMP
    )
""")

pool.execute(
    "INSERT INTO events (name, event_date, created_at, updated_at) VALUES (?, ?, ?, ?)",
    "Launch",
    date(2024, 6, 15),
    datetime(2024, 6, 15, 9, 0, 0),
    datetime(2024, 6, 15, 9, 0, 0),
)

row = pool.fetchrow("SELECT * FROM events WHERE name = ?", "Launch")
print(row["event_date"])    # datetime.date(2024, 6, 15)
print(row["created_at"])    # datetime.datetime(2024, 6, 15, 9, 0)
print(row["updated_at"])    # datetime.datetime(2024, 6, 15, 9, 0, tzinfo=datetime.timezone.utc)

pool.close()
