from postgreslite import PostgresLite

pool = PostgresLite(":memory:").connect()

pool.execute("CREATE TABLE accounts (id INTEGER PRIMARY KEY, balance INTEGER NOT NULL)")
pool.execute("INSERT INTO accounts VALUES (1, 500)")
pool.execute("INSERT INTO accounts VALUES (2, 300)")

# Both updates commit together, or neither does
try:
    with pool.transaction():
        pool.execute("UPDATE accounts SET balance = balance - 100 WHERE id = 1")
        pool.execute("UPDATE accounts SET balance = balance + 100 WHERE id = 2")
except Exception:
    print("Transfer failed, rolled back")

rows = pool.fetch("SELECT * FROM accounts")
print(rows)  # [{'id': 1, 'balance': 400}, {'id': 2, 'balance': 400}]

# Nested transactions become savepoints, so the inner one can fail on its own
with pool.transaction():
    pool.execute("UPDATE accounts SET balance = balance + 50 WHERE id = 1")
    try:
        with pool.transaction():
            pool.execute("UPDATE accounts SET balance = balance - 1000 WHERE id = 2")
            raise ValueError("Not enough money")
    except ValueError:
        pass

rows = pool.fetch("SELECT * FROM accounts")
print(rows)  # [{'id': 1, 'balance': 450}, {'id': 2, 'balance': 400}]

# Or control it yourself
tr = pool.transaction()
tr.start()
pool.execute("DELETE FROM accounts")
tr.rollback()

pool.close()
