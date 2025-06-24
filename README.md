# PostgresLite
Python SQLite combined with syntax compared to asyncpg progject.

No longer do you need to use the default SQLite and rather have a more powerful and easy way to work with SQLite and have good, default additions for things like timestamps, dates.
It also supports async and sync connections, in case you need to use it in an async environment.

## Install
You can install it by running `pip install postgreslite`

## How to use
```py
from postgreslite import PostgresLite

db = PostgresLite("./hello_world.db")
pool = db.connect()

# Same syntax as asyncpg with pool connection
```
The value you put in PostgresLite will become the filename of the database.
If you leave it empty, it will use the default filename of `storage.db`.
