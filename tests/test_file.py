from postgreslite import PostgresLite

pool = PostgresLite("./test_file.db").connect()

test = pool.run_sql("./test_file.sql")
print(test)

pool.execute("INSERT INTO users (name) VALUES (?)", "AlexFlipnote")
print(pool.fetch("SELECT * FROM users"))
