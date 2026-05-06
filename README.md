# PostgresLite
Python SQLite library built around asyncpg-style syntax.

No longer do you need to wrestle with raw SQLite. PostgresLite gives you a cleaner, asyncpg-inspired API with everything you'd expect out of the box:
- Automatic type conversion for `DATE`, `DATETIME`, `TIMESTAMP`, and `JSON` columns
- Transaction support via context managers
- Schema syncing and dumping
- Both sync and async connections, using the same API

## Installing
> You need **Python >=3.11** to use this library.

Install by using `pip install postgreslite` in the terminal.

## Quick example

**Sync**
```py
from postgreslite import PostgresLite

pool = PostgresLite("./hello_world.db").connect()

pool.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL)")
pool.execute("INSERT INTO users (name) VALUES (?) ON CONFLICT DO NOTHING", "AlexFlipnote")

data = pool.fetch("SELECT * FROM users")
print(data)  # [{'id': 1, 'name': 'AlexFlipnote'}]

pool.close()
```

**Async**
```py
import asyncio
from postgreslite import PostgresLite

async def main():
    pool = PostgresLite("./hello_world.db").connect_async()
    data = await pool.fetch("SELECT * FROM users")
    await pool.close()

asyncio.run(main())
```

Both connection types support the same API: `execute`, `fetch`, `fetchrow`, `fetchval`, `executemany`.
asyncpg-style placeholders (`$1`, `$2`, …) are also accepted and converted automatically.

## Type handling
Columns declared as `DATE`, `DATETIME`, `TIMESTAMP`, or `JSON` are automatically converted on read:

| Column type | Python type |
|-------------|-------------|
| `DATE` | `datetime.date` |
| `DATETIME` | `datetime.datetime` |
| `TIMESTAMP` | `datetime.datetime` (UTC) |
| `JSON` | `dict` / `list` |

## Transactions
```py
with pool.transaction():
    pool.execute("UPDATE accounts SET balance = balance - 100 WHERE id = 1")
    pool.execute("UPDATE accounts SET balance = balance + 100 WHERE id = 2")
```
Raises on error and rolls back automatically. Async pools use `async with pool.transaction()`.

## Schema utilities
```py
db = PostgresLite("./hello_world.db")

# Dump current schema to stdout, a file, or a folder of per-table files
db.dump_schema()
db.dump_schema(output="schema.sql")
db.dump_schema(output="schema/")

# Sync a schema definition (SQL string, .sql file, or folder) to the live database
result = db.sync_schema("schema/")
```
`sync_schema` adds new tables and missing columns non-destructively by default (`safe_mode=True`).

## Introspection
```py
pool.tables()                  # ['users', 'posts']
pool.table_exists("users")     # True
pool.table_columns("users")    # [<TableColumn name='id' ...>, ...]
```
