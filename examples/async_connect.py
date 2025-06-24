import asyncio

from postgreslite import PostgresLite

loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

db = PostgresLite("./hello_world.db", loop=loop)
pool = db.connect_async()

async def main():
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


loop.run_until_complete(main())
