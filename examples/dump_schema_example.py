from postgreslite import PostgresLite

db = PostgresLite("./hello_world.db")
pool = db.connect()

pool.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL
    )
""")
pool.execute("""
    CREATE TABLE IF NOT EXISTS posts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER REFERENCES users(id),
        title TEXT NOT NULL
    )
""")
pool.close()

# Print schema to stdout
schema = db.dump_schema()
print(schema)

# Write schema to a single file
db.dump_schema(output="./schema.sql")

# Write one .sql file per table into a folder
db.dump_schema(output="./schema/")
