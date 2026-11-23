import hashlib
import os
import sqlite3

from collections.abc import Iterator

__all__ = (
    "MigrationError",
)

MIGRATIONS_TABLE = "_migrations"


class MigrationError(Exception):
    """ Raised when migrations can't be applied. Nothing from the failing migration is kept. """


def split_statements(script: str) -> Iterator[str]:
    """ Split a SQL script into statements, respecting string literals, comments and trigger bodies. """
    buffer = ""
    for piece in script.split(";"):
        buffer += piece + ";"
        if sqlite3.complete_statement(buffer):
            if buffer.strip(" \t\r\n;"):
                yield buffer.strip()
            buffer = ""

    # Whatever is left never completed (e.g. a trailing comment), so drop the ";" added above
    leftover = buffer[:-1].strip()
    if leftover:
        yield leftover


def _checksum(sql: str) -> str:
    # Line endings are normalised, so a CRLF checkout doesn't look like an edited migration
    return hashlib.sha256(sql.replace("\r\n", "\n").encode()).hexdigest()


def _read_folder(folder: str) -> dict[str, str]:
    files = {}
    for name in sorted(os.listdir(folder)):
        if name.endswith(".sql"):
            with open(os.path.join(folder, name), encoding="utf-8") as f:
                files[name] = f.read()
    return files


def _baseline(cur: sqlite3.Cursor, files: dict[str, str]) -> bool:
    """
    Create the migrations table.

    An existing database without one is assumed to be up to date,
    so every migration is recorded as applied without running it.

    Returns
    -------
        True if the database was baselined.
    """
    existing = cur.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchone()

    cur.execute("BEGIN")
    try:
        cur.execute(
            f"CREATE TABLE {MIGRATIONS_TABLE} ("
            "name TEXT PRIMARY KEY, "
            "checksum TEXT NOT NULL, "
            "applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)"
        )
        if existing:
            cur.executemany(
                f"INSERT INTO {MIGRATIONS_TABLE} (name, checksum) VALUES (?, ?)",
                [(name, _checksum(sql)) for name, sql in files.items()]
            )
        cur.execute("COMMIT")
    except BaseException:
        cur.execute("ROLLBACK")
        raise
    return existing is not None


def _apply(conn: sqlite3.Connection, cur: sqlite3.Cursor, name: str, sql: str) -> None:
    denied = False

    def authorizer(action: int, *_: object) -> int:
        nonlocal denied
        if action in (sqlite3.SQLITE_TRANSACTION, sqlite3.SQLITE_SAVEPOINT):
            denied = True
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    # Foreign keys are checked once at the end instead, so tables can be rebuilt
    # (create, copy, drop, rename) without cascades firing on the drop
    foreign_keys = cur.execute("PRAGMA foreign_keys").fetchone()[0]
    cur.execute("PRAGMA foreign_keys = OFF")
    cur.execute("BEGIN")
    try:
        conn.set_authorizer(authorizer)
        try:
            for statement in split_statements(sql):
                cur.execute(statement)
        finally:
            conn.set_authorizer(None)

        if foreign_keys:
            violations = cur.execute("PRAGMA foreign_key_check").fetchall()
            if violations:
                tables = ", ".join(sorted({row[0] for row in violations}))
                raise MigrationError(f"{name} leaves foreign key violations in: {tables}")

        cur.execute(f"INSERT INTO {MIGRATIONS_TABLE} (name, checksum) VALUES (?, ?)", (name, _checksum(sql)))
        cur.execute("COMMIT")
    except BaseException as e:
        if conn.in_transaction:
            cur.execute("ROLLBACK")
        if denied:
            raise MigrationError(
                f"{name} must not contain BEGIN, COMMIT, ROLLBACK, SAVEPOINT or RELEASE, "
                "every migration already runs in its own transaction"
            ) from e
        if isinstance(e, sqlite3.Error):
            raise MigrationError(f"{name} failed: {e}") from e
        raise
    finally:
        cur.execute(f"PRAGMA foreign_keys = {'ON' if foreign_keys else 'OFF'}")


def migrate(conn: sqlite3.Connection, folder: str | os.PathLike[str]) -> list[str]:
    """
    Apply the .sql files in a folder that haven't been applied yet, in filename order.

    Parameters
    ----------
    conn:
        The connection to migrate.
    folder:
        Folder with migration files, e.g. '001_init.sql', '002_add_bio.sql'.

    Returns
    -------
        The names of the migrations that were applied.
    """
    if conn.in_transaction:
        raise MigrationError("Migrations can't run inside a transaction")

    files = _read_folder(os.fspath(folder))
    cur = conn.cursor()
    cur.row_factory = None

    try:
        tracked = cur.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (MIGRATIONS_TABLE,)
        ).fetchone()
        if tracked is None and _baseline(cur, files):
            return []

        applied = dict(cur.execute(f"SELECT name, checksum FROM {MIGRATIONS_TABLE}").fetchall())

        # Verify everything before applying anything
        for name, sql in files.items():
            if name in applied and applied[name] != _checksum(sql):
                raise MigrationError(f"{name} was changed after it was applied")

        pending = [(name, sql) for name, sql in files.items() if name not in applied]
        for name, sql in pending:
            _apply(conn, cur, name, sql)
        return [name for name, _ in pending]
    finally:
        cur.close()
