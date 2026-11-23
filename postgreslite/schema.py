import os
import re

__all__ = ()

_re_create_table = re.compile(r"^CREATE\s+TABLE\s+(?!IF\s+NOT\s+EXISTS\b)", re.IGNORECASE)
_re_create_index = re.compile(r"^CREATE\s+(UNIQUE\s+)?INDEX\s+(?!IF\s+NOT\s+EXISTS\b)", re.IGNORECASE)


def _normalize_sql(sql: str) -> str:
    """ Re-indent a CREATE statement and make it safe to run again (IF NOT EXISTS). """
    lines = [line.strip() for line in sql.splitlines() if line.strip()]
    if len(lines) > 2:
        lines = [lines[0], *(f"    {line}" for line in lines[1:-1]), lines[-1]]
    result = "\n".join(lines)

    result = _re_create_table.sub("CREATE TABLE IF NOT EXISTS ", result, count=1)
    return _re_create_index.sub(
        lambda m: f"CREATE {m.group(1) or ''}INDEX IF NOT EXISTS ",
        result, count=1,
    )


def _join(parts: list[str]) -> str:
    return ";\n\n".join(parts) + ";" if parts else ""


def render_schema(
    tables: list[tuple[str, str]],
    indexes: list[tuple[str, str]],
    output: str | os.PathLike[str] | None,
) -> str:
    """
    Render (name, sql) pairs from sqlite_master as a schema, and optionally write it to disk.

    Parameters
    ----------
    tables:
        (table name, CREATE TABLE sql) pairs.
    indexes:
        (table name, CREATE INDEX sql) pairs.
    output:
        A '.sql' file to write everything to, a folder to write one '{table}.sql' per table, or None.

    Returns
    -------
        The full schema as a SQL string.
    """
    indexes_by_table: dict[str, list[str]] = {}
    for table, sql in indexes:
        indexes_by_table.setdefault(table, []).append(_normalize_sql(sql))

    files = {
        name: [_normalize_sql(sql), *indexes_by_table.get(name, [])]
        for name, sql in tables
    }
    full = _join([sql for parts in files.values() for sql in parts])

    if output is None:
        return full

    output = os.fspath(output)
    if output.endswith(".sql"):
        os.makedirs(os.path.dirname(os.path.abspath(output)), exist_ok=True)
        with open(output, "w", encoding="utf-8") as f:
            f.write(full)
        return full

    os.makedirs(output, exist_ok=True)
    for name, parts in files.items():
        with open(os.path.join(output, f"{name}.sql"), "w", encoding="utf-8") as f:
            f.write(_join(parts))
    return full
