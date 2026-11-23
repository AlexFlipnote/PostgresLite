# PostgresLite
Python SQLite library built around asyncpg-style syntax.

No longer do you need to wrestle with raw SQLite. PostgresLite gives you a cleaner, asyncpg-inspired API with everything you'd expect out of the box:
- Automatic type conversion for `DATE`, `DATETIME`, `TIMESTAMP`, and `JSON` columns
- Transactions (and nested savepoints) via context managers
- asyncpg-style placeholders (`$1`, `$2`, …) and status strings (`"INSERT 0 1"`)
- Schema dumping and introspection
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
pool.execute("INSERT INTO users (name) VALUES ($1) ON CONFLICT DO NOTHING", "AlexFlipnote")

data = pool.fetch("SELECT * FROM users")
print(data)  # [{'id': 1, 'name': 'AlexFlipnote'}]

pool.close()
```

**Async**
```py
import asyncio
from postgreslite import PostgresLite

async def main():
    async with PostgresLite("./hello_world.db").connect_async() as pool:
        data = await pool.fetch("SELECT * FROM users")

asyncio.run(main())
```

Both connection types support the same API: `execute`, `executemany`, `fetch`, `fetchrow`, `fetchval`, `transaction`, `acquire`.
Queries run in a worker thread on the async connection, so they don't block the event loop.

`PostgresLite(filename, timeout=5.0)` accepts a `.db`, `.sqlite`, `.sqlite3` or `.db3` path, a `file:` URI, or `":memory:"`.
`timeout` is how many seconds to wait on another connection's lock before raising `database is locked`.

## Coming from asyncpg
Most asyncpg code works as-is, including `async with pool.acquire() as conn, conn.transaction():`.
The differences:

| | asyncpg | PostgresLite |
|---|---|---|
| Rows | `Record` | `dict` (so no `row[0]`; duplicate column names keep the last one) |
| `pool.acquire()` | Takes a connection from the pool | Yields the same single connection |
| Concurrent use | Raises "another operation is in progress" | Queries are queued; an open transaction blocks other tasks until it finishes |
| `executemany` | Returns `None` | Returns a status, e.g. `"INSERT 0 3"` |
| Placeholders | `$1` only | `$1` or `?` |

## Type handling
Columns declared as `DATE`, `DATETIME`, `TIMESTAMP`, or `JSON` are automatically converted on read:

| Column type | Python type |
|-------------|-------------|
| `DATE` | `datetime.date` |
| `DATETIME` | `datetime.datetime` |
| `TIMESTAMP` | `datetime.datetime` (converted to UTC) |
| `JSON` | `dict` / `list` |

`date`, `datetime`, `dict` and `list` arguments are converted on write.

> The column converters are registered with Python's `sqlite3` module, which is process-wide.
> They only affect connections opened with `detect_types=sqlite3.PARSE_DECLTYPES`.

## Transactions
```py
with pool.transaction():
    pool.execute("UPDATE accounts SET balance = balance - 100 WHERE id = 1")
    pool.execute("UPDATE accounts SET balance = balance + 100 WHERE id = 2")
```
Rolls back on any error (including cancellation) and re-raises.
Nested `transaction()` blocks become savepoints, and you can also call `start()`, `commit()` and `rollback()` yourself.
Async pools use `async with pool.transaction()`.

## Migrations
Put numbered `.sql` files in a folder, and apply the new ones on startup:
```
migrations/
├── 001_init.sql
├── 002_add_bio.sql
└── 003_posts.sql
```
```py
applied = pool.migrate("migrations")  # ['002_add_bio.sql', '003_posts.sql']
```
- Files run in filename order, each in its own transaction, and are recorded in a `_migrations` table, so each one only ever runs once.
- If a file fails, its changes are rolled back and `MigrationError` is raised. Fix it and run again.
- Don't edit a migration after it has been applied; add a new one. Edited files raise `MigrationError`.
- Files must not contain `BEGIN`, `COMMIT`, `ROLLBACK`, `SAVEPOINT` or `RELEASE`.
- Foreign keys are checked when each file finishes rather than per statement, so you can rebuild a table
  (create the new one, copy the rows, drop the old one, rename) without `ON DELETE CASCADE` wiping related rows.
- A database that already has tables but no `_migrations` table is assumed to be up to date:
  every current file is recorded as applied without running it.

## Schema utilities
```py
db = PostgresLite("./hello_world.db")

# Dump the current schema as a string, to a file, or to a folder of per-table files
db.dump_schema()
db.dump_schema(output="schema.sql")
db.dump_schema(include_indexes=True, output="schema/")

# For ":memory:" databases, dump from the connection instead
pool.dump_schema()
```
The output uses `IF NOT EXISTS`, so it can be run again safely, e.g. with `pool.run_sql("schema.sql")`.

## Introspection
```py
pool.tables()                  # ['users', 'posts']
pool.table_exists("users")     # True
pool.table_columns("users")    # [<TableColumn name='id' ...>, ...]
pool.lastrowid                 # ID of the last inserted row
```
