"""Print basic data quality checks for the local market intelligence database."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import text

from db import get_engine


@dataclass(frozen=True)
class DataQualitySnapshot:
    competitors: int
    source_urls: int
    successful_raw_pages: int
    failed_raw_pages: int
    short_raw_pages: int
    extraction_eligible_assets: int
    valid_analytical_assets: int
    extracted_insights: int
    invalid_asset_insights: int
    topic_documents: int
    latest_kpi_snapshot_date: Any
    pricing_pages: int

    @property
    def extraction_coverage(self) -> float:
        if self.extraction_eligible_assets == 0:
            return 0.0

        return self.valid_analytical_assets / self.extraction_eligible_assets


def fetch_count(connection, sql: str) -> int:
    """Fetch a single integer count from the database."""
    value = connection.execute(text(sql)).scalar()
    return int(value or 0)


def fetch_value(connection, sql: str):
    """Fetch a single scalar value from the database."""
    return connection.execute(text(sql)).scalar()


def analytical_asset_count_sql(*, require_insight: bool) -> str:
    insight_condition = "AND has_insight = TRUE" if require_insight else ""
    return f"""
        SELECT COUNT(*)
        FROM v_content_asset_validity
        WHERE (
            is_valid_content_asset = TRUE
            OR validity_reason = 'missing_insight'
        )
          {insight_condition}
    """


def fetch_snapshot(connection) -> DataQualitySnapshot:
    """Collect read-only data quality metrics from PostgreSQL."""
    return DataQualitySnapshot(
        competitors=fetch_count(connection, "SELECT COUNT(*) FROM competitors"),
        source_urls=fetch_count(connection, "SELECT COUNT(*) FROM source_urls"),
        successful_raw_pages=fetch_count(
            connection,
            "SELECT COUNT(*) FROM raw_pages WHERE success = TRUE",
        ),
        failed_raw_pages=fetch_count(
            connection,
            "SELECT COUNT(*) FROM raw_pages WHERE success = FALSE",
        ),
        short_raw_pages=fetch_count(
            connection,
            """
            SELECT COUNT(*)
            FROM raw_pages
            WHERE success = TRUE AND COALESCE(word_count, 0) < 150
            """,
        ),
        extraction_eligible_assets=fetch_count(
            connection,
            analytical_asset_count_sql(require_insight=False),
        ),
        valid_analytical_assets=fetch_count(
            connection,
            analytical_asset_count_sql(require_insight=True),
        ),
        extracted_insights=fetch_count(connection, "SELECT COUNT(*) FROM page_insights"),
        invalid_asset_insights=fetch_count(
            connection,
            """
            SELECT COUNT(*)
            FROM page_insights pi
            JOIN v_content_asset_validity cav ON cav.raw_page_id = pi.raw_page_id
            WHERE cav.is_valid_content_asset = FALSE
            """,
        ),
        topic_documents=fetch_count(connection, "SELECT COUNT(*) FROM topic_documents"),
        latest_kpi_snapshot_date=fetch_value(
            connection,
            "SELECT MAX(date) FROM kpi_competitor_daily",
        ),
        pricing_pages=fetch_count(
            connection,
            """
            SELECT COUNT(*)
            FROM source_urls
            WHERE LOWER(source_type) = 'pricing'
            """,
        ),
    )


def build_warnings(snapshot: DataQualitySnapshot) -> list[str]:
    """Return non-fatal warnings for weak or incomplete local data."""
    warnings: list[str] = []

    if snapshot.competitors < 3:
        warnings.append("fewer than 3 competitors")

    if snapshot.successful_raw_pages < 10:
        warnings.append("fewer than 10 successful pages")

    if snapshot.extraction_eligible_assets > 0 and snapshot.extraction_coverage < 0.8:
        warnings.append(
            "valid analytical asset coverage below 80% "
            f"({snapshot.extraction_coverage:.0%})"
        )

    if snapshot.pricing_pages == 0:
        warnings.append("no pricing pages")

    if snapshot.topic_documents == 0:
        warnings.append("no topic documents")

    return warnings


def format_kpi_date(value) -> str:
    if value is None:
        return "not_available"

    return str(value)


def print_report(snapshot: DataQualitySnapshot) -> None:
    """Print metrics and warnings in a stable, readable format."""
    print("Data quality summary:")
    print(f"  competitors: {snapshot.competitors}")
    print(f"  source URLs: {snapshot.source_urls}")
    print(f"  successful raw pages: {snapshot.successful_raw_pages}")
    print(f"  failed raw pages: {snapshot.failed_raw_pages}")
    print(f"  pages with word_count < 150: {snapshot.short_raw_pages}")
    print(f"  extraction-eligible assets: {snapshot.extraction_eligible_assets}")
    print(f"  valid analytical assets: {snapshot.valid_analytical_assets}")
    print(f"  extracted insights: {snapshot.extracted_insights}")
    print(f"  invalid-asset insights: {snapshot.invalid_asset_insights}")
    print(f"  topic documents: {snapshot.topic_documents}")
    print(f"  latest KPI snapshot date: {format_kpi_date(snapshot.latest_kpi_snapshot_date)}")
    print(f"  valid analytical asset coverage: {snapshot.extraction_coverage:.0%}")

    warnings = build_warnings(snapshot)
    if not warnings:
        print("Warnings: none")
        return

    print("Warnings:")
    for warning in warnings:
        print(f"  - {warning}")


def main() -> None:
    engine = get_engine()
    with engine.connect() as connection:
        snapshot = fetch_snapshot(connection)

    print_report(snapshot)


if __name__ == "__main__":
    main()
