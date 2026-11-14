"""Compute daily proxy KPI snapshots for competitor market intelligence."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text

from db import get_engine


UPSERT_TODAYS_SNAPSHOTS_SQL = text(
    """
    -- KPI snapshot crawl-volume fields are technical crawl-health metrics:
    -- pages_analyzed counts pages that crawled OK, total_words sums those
    -- crawled pages, and share_of_voice is a crawled word share proxy.
    -- Valid analytical asset counts are exposed live through SQL views.
    WITH successful_pages AS (
        SELECT
            competitor_id,
            COUNT(*) AS pages_analyzed,
            COALESCE(SUM(COALESCE(word_count, 0)), 0) AS total_words
        FROM raw_pages
        WHERE success = TRUE
        GROUP BY competitor_id
    ),
    total_words_all AS (
        SELECT COALESCE(SUM(total_words), 0) AS total_words
        FROM successful_pages
    ),
    insight_metrics AS (
        SELECT
            competitor_id,
            COUNT(*) AS insight_count,
            COUNT(*) FILTER (WHERE sentiment = 'positive') AS positive_count,
            COUNT(*) FILTER (WHERE sentiment = 'negative') AS negative_count,
            COUNT(*) FILTER (
                WHERE pricing_model IS NOT NULL
                  AND btrim(pricing_model) <> ''
                  AND lower(btrim(pricing_model)) <> 'not_found'
            ) AS pricing_mentions,
            COALESCE(
                SUM(
                    CASE
                        WHEN jsonb_typeof(key_features) = 'array'
                            THEN jsonb_array_length(key_features)
                        WHEN jsonb_typeof(features) = 'array'
                            THEN jsonb_array_length(features)
                        ELSE 0
                    END
                ),
                0
            ) AS feature_mentions
        FROM page_insights
        GROUP BY competitor_id
    ),
    competitor_metrics AS (
        SELECT competitor_id FROM successful_pages
        UNION
        SELECT competitor_id FROM insight_metrics
    )
    INSERT INTO kpi_competitor_daily (
        competitor_id,
        date,
        pages_analyzed,
        total_words,
        share_of_voice,
        sentiment_positive_share,
        sentiment_negative_share,
        pricing_mentions,
        feature_mentions
    )
    SELECT
        cm.competitor_id,
        CURRENT_DATE,
        COALESCE(sp.pages_analyzed, 0),
        COALESCE(sp.total_words, 0),
        COALESCE(sp.total_words::FLOAT / NULLIF(twa.total_words, 0), 0),
        COALESCE(im.positive_count::FLOAT / NULLIF(im.insight_count, 0), 0),
        COALESCE(im.negative_count::FLOAT / NULLIF(im.insight_count, 0), 0),
        COALESCE(im.pricing_mentions, 0),
        COALESCE(im.feature_mentions, 0)
    FROM competitor_metrics cm
    CROSS JOIN total_words_all twa
    LEFT JOIN successful_pages sp ON sp.competitor_id = cm.competitor_id
    LEFT JOIN insight_metrics im ON im.competitor_id = cm.competitor_id
    ORDER BY cm.competitor_id
    ON CONFLICT (competitor_id, date) DO UPDATE SET
        pages_analyzed = EXCLUDED.pages_analyzed,
        total_words = EXCLUDED.total_words,
        share_of_voice = EXCLUDED.share_of_voice,
        sentiment_positive_share = EXCLUDED.sentiment_positive_share,
        sentiment_negative_share = EXCLUDED.sentiment_negative_share,
        pricing_mentions = EXCLUDED.pricing_mentions,
        feature_mentions = EXCLUDED.feature_mentions,
        created_at = NOW()
    """
)


@dataclass(frozen=True)
class KpiSummary:
    """Summary of one KPI snapshot run."""

    deleted_rows: int
    inserted_rows: int
    snapshot_date: str


def compute_kpis(connection) -> KpiSummary:
    """Upsert today's competitor KPI snapshot."""
    upserted = connection.execute(UPSERT_TODAYS_SNAPSHOTS_SQL)
    snapshot_date = connection.execute(text("SELECT CURRENT_DATE")).scalar_one()

    return KpiSummary(
        deleted_rows=0,
        inserted_rows=upserted.rowcount or 0,
        snapshot_date=str(snapshot_date),
    )


def main() -> None:
    engine = get_engine()
    with engine.begin() as connection:
        summary = compute_kpis(connection)

    print(
        "KPI snapshot computed: "
        f"date={summary.snapshot_date}, "
        f"deleted={summary.deleted_rows}, "
        f"inserted={summary.inserted_rows}"
    )


if __name__ == "__main__":
    main()
