import asyncio

from postgreslite import PostgresLite

db = PostgresLite("./hello_world.db")


async def main():
    pool = db.connect_async()

    await pool.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL
        )
    """)

    await pool.execute(
        "INSERT INTO users (name) VALUES (?) ON CONFLICT DO NOTHING",
        "AlexFlipnote"
    )

    data = await pool.fetch("SELECT * FROM users")
    print(data)

    await pool.close()


asyncio.run(main())
