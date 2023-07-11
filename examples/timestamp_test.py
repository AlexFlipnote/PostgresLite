from postgreslite import PostgresLite
from datetime import datetime

db = PostgresLite("./test_timestamp.db").connect()

data1 = db.execute("""
    CREATE TABLE IF NOT EXISTS test (
        id INTEGER PRIMARY KEY UNIQUE,
        timer DATETIME
    );
""")
print(data1)

data2 = db.execute("""
    INSERT INTO test (id, timer)
    VALUES (1, ?)
    ON CONFLICT (id) DO NOTHING
""", datetime.now())
print(data2)

data3 = db.fetchrow("SELECT * FROM test WHERE id = 1")
print(data3)
