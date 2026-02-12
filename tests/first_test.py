from postgreslite import PostgresLite

# Create database (or uses existing one)
db = PostgresLite("./hello_world.db").connect()

# Create table
print(db.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
"""))

# Insert data
print(db.execute(
    "INSERT INTO users (name) VALUES (?) ON CONFLICT DO NOTHING",
    "AlexFlipnote"
))

print(db.execute(
    "INSERT INTO users (name) VALUES (?) ON CONFLICT DO NOTHING",
    "AlexFlipnote2"
))

print(db.execute(
    "INSERT INTO users (name) VALUES (?) ON CONFLICT DO NOTHING",
    "AlexFlipnote3"
))


print(db.execute(
    "INSERT INTO users (name) VALUES (?) ON CONFLICT DO NOTHING",
    "AlexFlipnote4"
))

# Check if data exists
print(db.fetch("SELECT * FROM users"))
