import os
import tempfile

from postgreslite import MigrationError, PostgresLite

folder = tempfile.mkdtemp()


def write(name: str, sql: str) -> None:
    with open(os.path.join(folder, name), "w", encoding="utf-8") as f:
        f.write(sql)


pool = PostgresLite(":memory:").connect()

write("001_init.sql", """
    CREATE TABLE users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL
    );
""")
print(pool.migrate(folder))  # ['001_init.sql']
print(pool.migrate(folder))  # [] (nothing new)

write("002_add_bio.sql", "ALTER TABLE users ADD COLUMN bio TEXT;")
print(pool.migrate(folder))  # ['002_add_bio.sql']

# A failing migration is rolled back completely
write("003_broken.sql", """
    CREATE TABLE posts (id INTEGER PRIMARY KEY);
    INSERT INTO does_not_exist VALUES (1);
""")
try:
    pool.migrate(folder)
except MigrationError as e:
    print(e)  # 003_broken.sql failed: no such table: does_not_exist

print(pool.tables())  # ['_migrations', 'users']

pool.close()
