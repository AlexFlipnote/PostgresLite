import asyncio

from postgreslite import PostgresLite

loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)


async def background_task(db, i: int):
    print(await db.execute(
        "INSERT INTO users (name) VALUES (?) ON CONFLICT DO NOTHING",
        f"AlexFlipnote{i}"
    ))


async def main():
    db = await PostgresLite(
        "./asyncio_test.db",
        loop=loop
    ).connect_async()

    # Create table
    print(await db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL
        )
    """))

    for g in range(10):
        loop.create_task(background_task(db, g))

    await asyncio.sleep(1)
    while db.queue.qsize() >= 1:
        await asyncio.sleep(0.1)

    # Check if data exists
    print(await db.fetch("SELECT * FROM users"))

    await db.close()


loop.run_until_complete(main())
