from postgreslite import PostgresLite

# Create database (or uses existing one)
db = PostgresLite("./asyncpg_test.db").connect()

# Create table
print(db.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        old_name TEXT NULL,
        custom_id BIGINT
    )
"""))

# Insert data
print(db.execute(
    "INSERT INTO users (name, old_name) VALUES ($1, $1) ON CONFLICT DO NOTHING",
    "AlexFlipnote"
))

# Check if data exists
print(db.fetch("SELECT * FROM users"))
