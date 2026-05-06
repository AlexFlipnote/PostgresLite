import os
from postgreslite import PostgresLite

db = PostgresLite("sync_schema_example.db")

# Initial schema
result = db.sync_schema("""
    CREATE TABLE users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        email TEXT
    )
""")
print(result.tables_created)   # ['users']

# Add a new column
result = db.sync_schema("""
    CREATE TABLE users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        email TEXT,
        bio TEXT
    )
""")
print(result.columns_added)    # {'users': ['bio']}

# Remove a column, safe_mode=True (default) warns but does not drop
result = db.sync_schema("""
    CREATE TABLE users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL
    )
""")
print(result.warnings)         # ["Column 'email' ... would be dropped ...", "Column 'bio' ..."]

# Remove a column, safe_mode=False actually drops it
result = db.sync_schema("""
    CREATE TABLE users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL
    )
""", safe_mode=False)
print(result.columns_removed)  # {'users': ['email', 'bio']}

# No changes, table and columns already exist
result = db.sync_schema("""
    CREATE TABLE users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL
    )
""")
print(result.skipped)          # ['users']

os.remove("sync_schema_example.db")
