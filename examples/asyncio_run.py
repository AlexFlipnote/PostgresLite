import asyncio

from postgreslite import PostgresLite

loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)


async def background_task(pool, i: int):
    print(await pool.execute(
        "INSERT INTO users (name) VALUES (?) ON CONFLICT DO NOTHING",
        f"AlexFlipnote{i}"
    ))


async def main():
    db = PostgresLite(
        "./asyncio_test.db",
        loop=loop
    )

    pool = await db.connect_async()

    # Create table
    print(await pool.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL
        )
    """))

    for g in range(10):
        loop.create_task(background_task(pool, g))

    await asyncio.sleep(1)
    while pool.queue_size >= 1:
        await asyncio.sleep(0.1)

    # Check if data exists
    print(await pool.fetch("SELECT * FROM users"))

    await pool.close()


loop.run_until_complete(main())
