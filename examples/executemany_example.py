from postgreslite import PostgresLite

pool = PostgresLite(":memory:").connect()

pool.execute("CREATE TABLE products (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, price REAL)")

rows = [
    ("Apple", 0.99),
    ("Banana", 0.49),
    ("Cherry", 2.49),
]

status = pool.executemany("INSERT INTO products (name, price) VALUES (?, ?)", rows)
print(status)  # INSERT 3

all_products = pool.fetch("SELECT * FROM products")
print(all_products)

pool.close()
