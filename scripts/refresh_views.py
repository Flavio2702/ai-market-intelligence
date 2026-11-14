"""Create or refresh PostgreSQL views used by Apache Superset."""

from __future__ import annotations

import re
from pathlib import Path

from db import get_engine


def split_sql_statements(sql: str) -> list[str]:
    statements: list[str] = []
    current: list[str] = []
    quote: str | None = None
    index = 0

    while index < len(sql):
        char = sql[index]
        next_char = sql[index + 1] if index + 1 < len(sql) else ""

        if quote is None and char == "-" and next_char == "-":
            while index < len(sql) and sql[index] != "\n":
                current.append(sql[index])
                index += 1
            continue

        if quote is None and char in {"'", '"'}:
            quote = char
            current.append(char)
            index += 1
            continue

        if quote == char and char in {"'", '"'}:
            current.append(char)
            if next_char == char:
                current.append(next_char)
                index += 2
                continue
            quote = None
            index += 1
            continue

        if quote is None and char == ";":
            statement = "".join(current).strip()
            if statement:
                statements.append(statement)
            current = []
            index += 1
            continue

        current.append(char)
        index += 1

    statement = "".join(current).strip()
    if statement:
        statements.append(statement)

    return statements


def extract_view_names(sql: str) -> list[str]:
    return re.findall(
        r"CREATE\s+OR\s+REPLACE\s+VIEW\s+([a-zA-Z_][a-zA-Z0-9_]*)\s+AS\b",
        sql,
        flags=re.IGNORECASE,
    )


def execute_statements_with_retries(connection, statements: list[str]) -> None:
    pending = list(statements)
    last_error: Exception | None = None

    while pending:
        remaining: list[str] = []
        progressed = False
        for statement in pending:
            if not hasattr(connection, "begin_nested"):
                connection.exec_driver_sql(statement)
                progressed = True
                continue

            savepoint = connection.begin_nested()
            try:
                connection.exec_driver_sql(statement)
            except Exception as exc:
                savepoint.rollback()
                remaining.append(statement)
                last_error = exc
            else:
                savepoint.commit()
                progressed = True

        if not progressed:
            raise last_error or RuntimeError("view refresh made no progress")
        pending = remaining


def refresh_views() -> Path:
    repo_root = Path(__file__).resolve().parents[1]
    views_path = repo_root / "sql" / "views.sql"
    views_sql = views_path.read_text(encoding="utf-8")
    view_names = extract_view_names(views_sql)

    engine = get_engine()
    with engine.begin() as connection:
        for view_name in reversed(view_names):
            connection.exec_driver_sql(f"DROP VIEW IF EXISTS {view_name} CASCADE")
        execute_statements_with_retries(connection, split_sql_statements(views_sql))

    return views_path


def main() -> None:
    try:
        views_path = refresh_views()
    except Exception as exc:
        print("Superset view refresh failed:")
        print(f"  errors: {exc}")
        print("  fix: verify PostgreSQL is running and DATABASE_URL points to an initialized database.")
        raise SystemExit(1) from exc

    print(f"Superset views refreshed from {views_path}.")


if __name__ == "__main__":
    main()
