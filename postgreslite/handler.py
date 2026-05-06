import json
import os
import re
import sqlite3
from dataclasses import dataclass, field

from .pool import PoolConnection, AsyncPoolConnection
from datetime import datetime, date, UTC

__all__ = (
    "PostgresLite",
    "SchemaSyncResult",
)


def _normalize_sql(sql: str) -> str:
    lines = [line.strip() for line in sql.splitlines() if line.strip()]
    if len(lines) <= 1:
        return lines[0] if lines else sql
    result = lines[0] + "\n" + "\n".join(f"    {line}" for line in lines[1:-1]) + "\n" + lines[-1]
    return re.sub(
        r"CREATE\s+TABLE\s+(?!IF\s+NOT\s+EXISTS\s+)(\w)",
        r"CREATE TABLE IF NOT EXISTS \1",
        result, count=1, flags=re.IGNORECASE,
    )


_re_create_table = re.compile(
    r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)",
    re.IGNORECASE,
)
_re_create_index = re.compile(
    r"CREATE\s+(UNIQUE\s+)?INDEX\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)",
    re.IGNORECASE,
)
_re_strip_comments = re.compile(r"--[^\n]*|/\*.*?\*/", re.DOTALL)


@dataclass
class SchemaSyncResult:
    tables_created: list[str] = field(default_factory=list)
    columns_added: dict[str, list[str]] = field(default_factory=dict)
    columns_removed: dict[str, list[str]] = field(default_factory=dict)
    skipped: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def dict_factory(cursor: sqlite3.Cursor, row: sqlite3.Row) -> dict:
    d = {}
    for index, col in enumerate(cursor.description):
        d[col[0]] = row[index]
    return d


class PostgresLite:
    def __init__(self, filename: str = "storage.db"):
        self._prepare_settings()
        self._filename = filename

        if filename != ":memory:" and not filename.endswith(".db"):
            raise ValueError("Database filename must end with '.db'")

    def connect(self) -> PoolConnection:
        """ Makes a connection to the database and returns the pool (sync). """
        conn = sqlite3.connect(
            self._filename,
            isolation_level=None,
            detect_types=sqlite3.PARSE_DECLTYPES
        )
        conn.row_factory = dict_factory
        conn.execute("PRAGMA foreign_keys = ON")
        return PoolConnection(conn.cursor(), conn)

    def connect_async(self) -> AsyncPoolConnection:
        """ Makes a connection to the database and returns the pool (async). """
        conn = sqlite3.connect(
            self._filename,
            isolation_level=None,
            check_same_thread=False,
            detect_types=sqlite3.PARSE_DECLTYPES
        )
        conn.row_factory = dict_factory
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys = ON")
        return AsyncPoolConnection(conn.cursor(), conn)

    def dump_schema(self, include_indexes: bool = False, output: str | None = None) -> str:
        """
        Returns the current database schema as a SQL string.

        Parameters
        ----------
        include_indexes:
            Whether to include CREATE INDEX statements in the output (default False).
        output:
            If a path ending in '.sql', writes the full schema to that file.
            If a folder path, writes one '{table}.sql' file per table with indexes appended.
            If None, no file is written.

        Returns
        -------
            The full schema as a SQL string, regardless of output mode.
        """
        conn = sqlite3.connect(self._filename)
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT name, sql FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%' "
                "ORDER BY name"
            )
            tables = [(row[0], _normalize_sql(row[1])) for row in cur.fetchall() if row[1]]

            indexes_by_table: dict[str, list[str]] = {}
            if include_indexes:
                cur.execute(
                    "SELECT tbl_name, sql FROM sqlite_master "
                    "WHERE type='index' AND name NOT LIKE 'sqlite_%' "
                    "ORDER BY name"
                )
                for tbl, sql in cur.fetchall():
                    if sql:
                        indexes_by_table.setdefault(tbl, []).append(_normalize_sql(sql))
        finally:
            conn.close()

        if output is None or output.endswith(".sql"):
            parts = [sql for _, sql in tables]
            for idx_list in indexes_by_table.values():
                parts += idx_list
            full = ";\n\n".join(parts) + ";" if parts else ""
            if output is not None:
                os.makedirs(os.path.dirname(os.path.abspath(output)), exist_ok=True)
                with open(output, "w", encoding="utf-8") as f:
                    f.write(full)
            return full

        os.makedirs(output, exist_ok=True)
        all_parts = []
        for tbl_name, tbl_sql in tables:
            file_parts = [tbl_sql]
            for idx_sql in indexes_by_table.get(tbl_name, []):
                file_parts.append(idx_sql)
            content = ";\n\n".join(file_parts) + ";"
            with open(os.path.join(output, f"{tbl_name}.sql"), "w", encoding="utf-8") as f:
                f.write(content)
            all_parts.extend(file_parts)
        return ";\n\n".join(all_parts) + ";" if all_parts else ""

    def sync_schema(self, schema: str = "schema", safe_mode: bool = True) -> SchemaSyncResult:
        """
        Sync a schema definition to the database.

        Parameters
        ----------
        schema:
            An inline SQL string, a path to a .sql file, or a folder of .sql files
            (default folder name is "schema"). Only CREATE TABLE and CREATE INDEX statements
            are permitted; anything else raises ValueError.
        safe_mode:
            When True (default), extra columns are reported in result.warnings but not dropped.
            When False, extra columns are removed and reported in result.columns_removed.
            Note: columns with PRIMARY KEY or UNIQUE constraints cannot be added via ALTER TABLE.

        Returns
        -------
            A SchemaSyncResult with tables_created, columns_added, columns_removed, skipped, and warnings.
        """
        sql = self._load_schema_sql(schema)
        statements = self._parse_statements(sql)
        result = SchemaSyncResult()

        conn = sqlite3.connect(self._filename)
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
            existing_tables = {row[0] for row in cur.fetchall()}

            for kind, name, stmt in statements:
                if kind == "table":
                    safe_stmt = re.sub(
                        r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?",
                        "CREATE TABLE IF NOT EXISTS ",
                        stmt, count=1, flags=re.IGNORECASE,
                    )
                    cur.execute(safe_stmt)
                    conn.commit()

                    if name in existing_tables:
                        new_cols = self._get_desired_columns(name, stmt)
                        cur.execute(f"PRAGMA table_info({name})")
                        pragma_rows = cur.fetchall()
                        existing_cols = {row[1] for row in pragma_rows}
                        pk_cols = {row[1] for row in pragma_rows if row[5]}

                        added = []
                        for col_name, col_def in new_cols.items():
                            if col_name not in existing_cols:
                                try:
                                    cur.execute(f"ALTER TABLE {name} ADD COLUMN {col_def}")
                                    conn.commit()
                                    added.append(col_name)
                                except sqlite3.OperationalError:
                                    pass  # PRIMARY KEY / UNIQUE columns can't be added

                        removable = [c for c in existing_cols if c not in new_cols and c not in pk_cols]
                        if removable:
                            if safe_mode:
                                for col in removable:
                                    result.warnings.append(
                                        f"Column '{col}' on table '{name}' is not in the schema "
                                        f"and would be dropped. Re-run with safe_mode=False to apply."
                                    )
                            else:
                                removed = []
                                for col in removable:
                                    cur.execute(f"ALTER TABLE {name} DROP COLUMN {col}")
                                    conn.commit()
                                    removed.append(col)
                                if removed:
                                    result.columns_removed[name] = removed

                        if added:
                            result.columns_added[name] = added
                        elif not removable:
                            result.skipped.append(name)
                    else:
                        result.tables_created.append(name)

                elif kind == "index":
                    safe_stmt = re.sub(
                        r"CREATE\s+(UNIQUE\s+)?INDEX\s+(?:IF\s+NOT\s+EXISTS\s+)?",
                        lambda m: f"CREATE {m.group(1) or ''}INDEX IF NOT EXISTS ",
                        stmt, count=1, flags=re.IGNORECASE,
                    )
                    cur.execute(safe_stmt)
                    conn.commit()
        finally:
            conn.close()

        return result

    def _load_schema_sql(self, schema: str) -> str:
        if os.path.isdir(schema):
            parts = []
            for fname in sorted(os.listdir(schema)):
                if fname.endswith(".sql"):
                    with open(os.path.join(schema, fname), encoding="utf-8") as f:
                        parts.append(f.read())
            return "\n".join(parts)
        if schema.endswith(".sql") and os.path.isfile(schema):
            with open(schema, encoding="utf-8") as f:
                return f.read()
        return schema

    def _parse_statements(self, sql: str) -> list[tuple[str, str, str]]:
        sql = _re_strip_comments.sub("", sql)
        results = []
        for chunk in sql.split(";"):
            chunk = chunk.strip()
            if not chunk:
                continue
            first = chunk.split()[0].upper() if chunk.split() else ""
            second = chunk.split()[1].upper() if len(chunk.split()) > 1 else ""

            if first == "CREATE" and second == "TABLE":
                m = _re_create_table.search(chunk)
                if m:
                    results.append(("table", m.group(1), chunk))
            elif first == "CREATE" and second in ("INDEX", "UNIQUE"):
                m = _re_create_index.search(chunk)
                if m:
                    results.append(("index", m.group(2), chunk))
            else:
                raise ValueError(
                    f"sync_schema only permits CREATE TABLE and CREATE INDEX statements; got: {first} {second}".strip()
                )
        return results

    def _get_desired_columns(self, table_name: str, create_stmt: str) -> dict[str, str]:
        conn = sqlite3.connect(":memory:")
        try:
            safe_stmt = re.sub(
                r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?",
                "CREATE TABLE IF NOT EXISTS ",
                create_stmt, count=1, flags=re.IGNORECASE,
            )
            conn.execute(safe_stmt)
            cur = conn.execute(f"PRAGMA table_info({table_name})")
            cols = {}
            for row in cur.fetchall():
                col_name = row[1]
                col_type = row[2] or "TEXT"
                notnull = row[3]
                default = row[4]
                pk = row[5]
                if pk:
                    continue  # cannot ALTER TABLE ADD COLUMN with PRIMARY KEY
                defn = f"{col_name} {col_type}"
                if notnull:
                    defn += " NOT NULL"
                if default is not None:
                    defn += f" DEFAULT {default}"
                cols[col_name] = defn
        finally:
            conn.close()
        return cols

    def _prepare_settings(self) -> None:
        """ Prepare SQLite settings for better experience. """

        def adapt_date_iso(val: date) -> str:
            return val.isoformat()

        def adapt_datetime_iso(val: datetime) -> str:
            return val.isoformat()

        sqlite3.register_adapter(date, adapt_date_iso)
        sqlite3.register_adapter(datetime, adapt_datetime_iso)
        sqlite3.register_adapter(dict, json.dumps)
        sqlite3.register_adapter(list, json.dumps)

        def convert_date(val: bytes) -> date:
            return date.fromisoformat(val.decode())

        def convert_datetime(val: bytes) -> datetime:
            return datetime.fromisoformat(val.decode())

        def convert_timestamp(val: bytes) -> datetime:
            return datetime.fromisoformat(val.decode()).replace(tzinfo=UTC)

        def convert_json(val: bytes) -> object:
            return json.loads(val.decode())

        sqlite3.register_converter("date", convert_date)
        sqlite3.register_converter("datetime", convert_datetime)
        sqlite3.register_converter("timestamp", convert_timestamp)
        sqlite3.register_converter("json", convert_json)
