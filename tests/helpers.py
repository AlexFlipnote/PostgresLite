from postgreslite import PostgresLite


def make_sync_pool():
    return PostgresLite(":memory:").connect()
