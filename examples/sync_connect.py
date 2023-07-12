from postgreslite import PostgresLite

db = PostgresLite("./hello_world.db")

pool = db.connect()

pool.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL
    )
""")

pool.execute(
    "INSERT INTO users (name) VALUES (?) ON CONFLICT DO NOTHING",
    "AlexFlipnote"
)

data = pool.fetch("SELECT * FROM users")
print(data)
