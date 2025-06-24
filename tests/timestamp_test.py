import os

from postgreslite import PostgresLite
from datetime import datetime, UTC

try:
    os.remove("./test_timestamp.db")
except FileNotFoundError:
    pass

db = PostgresLite("./test_timestamp.db").connect()

print(db.execute("""
    CREATE TABLE IF NOT EXISTS test (
        id INTEGER PRIMARY KEY UNIQUE,
        timer DATETIME
    );
"""))

print(db.execute("""
    INSERT INTO test (id, timer)
    VALUES (1, ?)
    ON CONFLICT (id) DO NOTHING
""", datetime.now(UTC)))

print(db.fetchrow("SELECT * FROM test WHERE id = 1"))
