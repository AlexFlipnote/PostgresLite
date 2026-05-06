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

pool.close()
