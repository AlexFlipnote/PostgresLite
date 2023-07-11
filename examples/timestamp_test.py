from postgreslite import PostgresLite
from datetime import datetime

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
""", datetime.now()))

print(db.fetchrow("SELECT * FROM test WHERE id = 1"))
