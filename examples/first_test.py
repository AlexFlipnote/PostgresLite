from litedb import LiteDB

# Create database (or uses existing one)
db = LiteDB("hello_world.db")

# Create table
data1 = db.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL)")
print(data1)

# Insert data
data2 = db.execute(
    "INSERT INTO users (name) VALUES (?) ON CONFLICT DO NOTHING",
    "AlexFlipnote"
)
print(data2)

# Check if data exists
data3 = db.fetch("SELECT * FROM users")
print(data3)
