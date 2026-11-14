"""Load manually curated CSV inputs into PostgreSQL."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from sqlalchemy import bindparam, text

from db import get_engine


REPO_ROOT = Path(__file__).resolve().parents[1]
COMPETITORS_CSV = REPO_ROOT / "data" / "competitors.csv"
URLS_CSV = REPO_ROOT / "data" / "urls.csv"

COMPETITOR_COLUMNS = ["name", "website", "category", "country", "notes"]
OPTIONAL_COMPETITOR_COLUMNS = ["is_owned_domain"]
URL_COLUMNS = ["competitor_name", "url", "source_type"]

REQUIRED_COMPETITOR_FIELDS = ["name", "website"]
REQUIRED_URL_FIELDS = ["competitor_name", "url", "source_type"]


class InputLoadError(RuntimeError):
    """Raised when CSV inputs cannot be loaded safely."""


@dataclass
class LoadSummary:
    competitors_inserted: int = 0
    competitors_existing: int = 0
    urls_inserted: int = 0
    urls_existing: int = 0
    dataset_reset: bool = False


def read_input_csv(
    path: Path,
    required_columns: list[str],
    optional_columns: list[str] | None = None,
) -> pd.DataFrame:
    """Read a CSV as strings and validate its expected header."""
    if not path.exists():
        raise InputLoadError(f"Missing required CSV file: {path}")

    dataframe = pd.read_csv(path, dtype=str, keep_default_na=False)
    missing_columns = [column for column in required_columns if column not in dataframe]
    if missing_columns:
        joined = ", ".join(missing_columns)
        raise InputLoadError(f"{path} is missing required column(s): {joined}")

    optional_columns = optional_columns or []
    for column in optional_columns:
        if column not in dataframe:
            dataframe[column] = ""

    dataframe = dataframe[required_columns + optional_columns].copy()
    for column in required_columns + optional_columns:
        dataframe[column] = dataframe[column].fillna("").astype(str).str.strip()

    return dataframe


def validate_required_values(
    dataframe: pd.DataFrame, required_fields: list[str], label: str
) -> None:
    """Fail clearly when required CSV fields are blank."""
    errors: list[str] = []

    for index, row in dataframe.iterrows():
        missing_fields = [field for field in required_fields if not row[field]]
        if missing_fields:
            csv_row_number = index + 2
            joined = ", ".join(missing_fields)
            errors.append(f"{label} row {csv_row_number} has blank field(s): {joined}")

    if errors:
        raise InputLoadError("\n".join(errors))


def validate_owned_domain_count(competitors: pd.DataFrame) -> None:
    """Allow zero or one owned domain marker before destructive reload."""
    if "is_owned_domain" not in competitors:
        return

    owned_names = [
        row["name"]
        for row in competitors.to_dict("records")
        if parse_bool(row.get("is_owned_domain", ""))
    ]
    if len(owned_names) > 1:
        joined = ", ".join(owned_names)
        raise InputLoadError(
            "competitors.csv can mark at most one owned domain with "
            f"is_owned_domain=true; found {len(owned_names)}: {joined}"
        )


def reset_dataset(connection) -> None:
    """Clear configured and derived dataset tables before loading fresh CSV inputs."""
    connection.execute(
        text(
            """
            TRUNCATE page_insights,
                     controlled_topic_documents,
                     topic_documents,
                     kpi_competitor_daily,
                     raw_pages,
                     source_urls,
                     competitors
            RESTART IDENTITY
            """
        )
    )


def load_competitors(connection, competitors: pd.DataFrame) -> LoadSummary:
    """Insert competitors that are not already present by name."""
    summary = LoadSummary()
    seen_names: set[str] = set()
    unique_names = list(dict.fromkeys(competitors["name"].tolist()))
    existing_names = set(fetch_existing_competitor_names(connection, unique_names))

    for row in competitors.to_dict("records"):
        name = row["name"]
        if name in seen_names or name in existing_names:
            summary.competitors_existing += 1
            seen_names.add(name)
            continue

        result = connection.execute(
            text(
                """
                INSERT INTO competitors (
                    name,
                    website,
                    category,
                    country,
                    notes,
                    is_owned_domain
                )
                VALUES (
                    :name,
                    :website,
                    :category,
                    :country,
                    :notes,
                    :is_owned_domain
                )
                ON CONFLICT (name) DO NOTHING
                """
            ),
            {
                "name": name,
                "website": row["website"],
                "category": row["category"] or None,
                "country": row["country"] or None,
                "notes": row["notes"] or None,
                "is_owned_domain": parse_bool(row.get("is_owned_domain", "")),
            },
        )

        if result.rowcount == 1:
            summary.competitors_inserted += 1
        else:
            summary.competitors_existing += 1

        seen_names.add(name)

    return summary


def fetch_existing_competitor_names(connection, names: list[str]) -> list[str]:
    if not names:
        return []

    result = connection.execute(
        text("SELECT name FROM competitors WHERE name IN :names").bindparams(
            bindparam("names", expanding=True)
        ),
        {"names": names},
    )
    return [row._mapping["name"] for row in result]


def fetch_competitor_ids(connection, names: list[str]) -> dict[str, int]:
    if not names:
        return {}

    result = connection.execute(
        text("SELECT id, name FROM competitors WHERE name IN :names").bindparams(
            bindparam("names", expanding=True)
        ),
        {"names": list(dict.fromkeys(names))},
    )
    return {row._mapping["name"]: row._mapping["id"] for row in result}


def load_source_urls(connection, urls: pd.DataFrame) -> LoadSummary:
    """Insert source URLs that are not already present for a competitor."""
    summary = LoadSummary()
    competitor_ids = fetch_competitor_ids(connection, urls["competitor_name"].tolist())
    missing_names = sorted(set(urls["competitor_name"]) - set(competitor_ids))

    if missing_names:
        joined = ", ".join(missing_names)
        raise InputLoadError(
            "urls.csv references competitor_name value(s) not found in "
            f"competitors.csv or the database: {joined}"
        )

    seen_keys: set[tuple[int, str]] = set()
    existing_keys = fetch_existing_source_url_keys(connection, urls, competitor_ids)

    for row in urls.to_dict("records"):
        competitor_id = competitor_ids[row["competitor_name"]]
        key = (competitor_id, row["url"])

        if key in seen_keys or key in existing_keys:
            summary.urls_existing += 1
            seen_keys.add(key)
            continue

        result = connection.execute(
            text(
                """
                INSERT INTO source_urls (competitor_id, url, source_type)
                VALUES (:competitor_id, :url, :source_type)
                ON CONFLICT (competitor_id, url) DO NOTHING
                """
            ),
            {
                "competitor_id": competitor_id,
                "url": row["url"],
                "source_type": row["source_type"],
            },
        )

        if result.rowcount == 1:
            summary.urls_inserted += 1
        else:
            summary.urls_existing += 1

        seen_keys.add(key)

    return summary


def fetch_existing_source_url_keys(
    connection, urls: pd.DataFrame, competitor_ids: dict[str, int]
) -> set[tuple[int, str]]:
    if urls.empty:
        return set()

    requested_keys: set[tuple[int, str]] = set()
    for row in urls.to_dict("records"):
        requested_keys.add((competitor_ids[row["competitor_name"]], row["url"]))

    result = connection.execute(
        text(
            """
            SELECT competitor_id, url
            FROM source_urls
            WHERE competitor_id IN :competitor_ids
              AND url IN :urls
            """
        ).bindparams(
            bindparam("competitor_ids", expanding=True),
            bindparam("urls", expanding=True),
        ),
        {
            "competitor_ids": sorted(
                {competitor_id for competitor_id, _url in requested_keys}
            ),
            "urls": sorted({url for _competitor_id, url in requested_keys}),
        },
    )

    return {
        (record._mapping["competitor_id"], record._mapping["url"])
        for record in result
        if (record._mapping["competitor_id"], record._mapping["url"]) in requested_keys
    }


def load_inputs(
    competitors_path: Path = COMPETITORS_CSV, urls_path: Path = URLS_CSV
) -> LoadSummary:
    try:
        competitors = read_input_csv(
            competitors_path,
            COMPETITOR_COLUMNS,
            OPTIONAL_COMPETITOR_COLUMNS,
        )
    except TypeError:
        competitors = read_input_csv(competitors_path, COMPETITOR_COLUMNS)
        for column in OPTIONAL_COMPETITOR_COLUMNS:
            if column not in competitors:
                competitors[column] = ""
    urls = read_input_csv(urls_path, URL_COLUMNS)

    validate_required_values(
        competitors, REQUIRED_COMPETITOR_FIELDS, competitors_path.name
    )
    validate_required_values(urls, REQUIRED_URL_FIELDS, urls_path.name)
    validate_owned_domain_count(competitors)

    engine = get_engine()
    with engine.begin() as connection:
        reset_dataset(connection)
        competitor_summary = load_competitors(connection, competitors)
        url_summary = load_source_urls(connection, urls)

    return LoadSummary(
        competitors_inserted=competitor_summary.competitors_inserted,
        competitors_existing=competitor_summary.competitors_existing,
        urls_inserted=url_summary.urls_inserted,
        urls_existing=url_summary.urls_existing,
        dataset_reset=True,
    )


def parse_bool(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y", "owned"}


def print_summary(summary: LoadSummary) -> None:
    print("Input load summary:")
    if summary.dataset_reset:
        print("  previous dataset reset: yes")
    print(f"  competitors inserted: {summary.competitors_inserted}")
    print(f"  competitors already existing: {summary.competitors_existing}")
    print(f"  URLs inserted: {summary.urls_inserted}")
    print(f"  URLs already existing: {summary.urls_existing}")


def main() -> None:
    try:
        summary = load_inputs()
    except InputLoadError as exc:
        print("Input load failed:")
        print(f"  errors: {exc}")
        raise SystemExit(1) from exc

    print_summary(summary)


if __name__ == "__main__":
    main()
