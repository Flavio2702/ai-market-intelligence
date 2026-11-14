"""Initialize the PostgreSQL database schema."""

from pathlib import Path

from sqlalchemy import text

from db import get_engine


REPAIR_DUPLICATES_SQL = """
DO $$
BEGIN
    IF to_regclass('public.page_insights') IS NOT NULL THEN
        DELETE FROM page_insights pi
        USING page_insights duplicate
        WHERE pi.raw_page_id IS NOT NULL
          AND duplicate.raw_page_id = pi.raw_page_id
          AND duplicate.id > pi.id;
    END IF;

    IF to_regclass('public.topic_documents') IS NOT NULL THEN
        DELETE FROM topic_documents td
        USING topic_documents duplicate
        WHERE td.raw_page_id IS NOT NULL
          AND duplicate.raw_page_id = td.raw_page_id
          AND duplicate.id > td.id;
    END IF;

    IF to_regclass('public.controlled_topic_documents') IS NOT NULL THEN
        DELETE FROM controlled_topic_documents ctd
        USING controlled_topic_documents duplicate
        WHERE ctd.raw_page_id IS NOT NULL
          AND duplicate.raw_page_id = ctd.raw_page_id
          AND duplicate.controlled_topic_id = ctd.controlled_topic_id
          AND duplicate.id > ctd.id;
    END IF;

    IF to_regclass('public.kpi_competitor_daily') IS NOT NULL THEN
        DELETE FROM kpi_competitor_daily kpi
        USING kpi_competitor_daily duplicate
        WHERE kpi.competitor_id IS NOT NULL
          AND kpi.date IS NOT NULL
          AND duplicate.competitor_id = kpi.competitor_id
          AND duplicate.date = kpi.date
          AND duplicate.id > kpi.id;
    END IF;
END $$;
"""

PRECHECK_OWNED_DOMAIN_SQL = """
DO $$
DECLARE
    owned_domain_count INTEGER;
BEGIN
    IF to_regclass('public.competitors') IS NOT NULL
       AND EXISTS (
           SELECT 1
           FROM pg_attribute
           WHERE attrelid = 'public.competitors'::regclass
             AND attname = 'is_owned_domain'
             AND NOT attisdropped
       ) THEN
        SELECT COUNT(*)
        INTO owned_domain_count
        FROM competitors
        WHERE is_owned_domain = TRUE;

        IF owned_domain_count > 1 THEN
            RAISE EXCEPTION
                'Cannot enforce single owned domain: found % competitors with is_owned_domain=true',
                owned_domain_count;
        END IF;
    END IF;
END $$;
"""

PREPARE_OWNED_DOMAIN_COLUMN_SQL = """
ALTER TABLE IF EXISTS competitors
    ADD COLUMN IF NOT EXISTS is_owned_domain BOOLEAN DEFAULT FALSE;
"""

ENFORCE_CORE_NOT_NULL_SQL = """
DO $$
BEGIN
    IF to_regclass('public.page_insights') IS NOT NULL THEN
        DELETE FROM page_insights
        WHERE raw_page_id IS NULL OR competitor_id IS NULL;

        ALTER TABLE page_insights
            ALTER COLUMN raw_page_id SET NOT NULL,
            ALTER COLUMN competitor_id SET NOT NULL;
    END IF;

    IF to_regclass('public.topic_documents') IS NOT NULL THEN
        DELETE FROM topic_documents
        WHERE raw_page_id IS NULL OR competitor_id IS NULL;

        ALTER TABLE topic_documents
            ALTER COLUMN raw_page_id SET NOT NULL,
            ALTER COLUMN competitor_id SET NOT NULL;
    END IF;

    IF to_regclass('public.controlled_topic_documents') IS NOT NULL THEN
        DELETE FROM controlled_topic_documents
        WHERE raw_page_id IS NULL OR competitor_id IS NULL;

        ALTER TABLE controlled_topic_documents
            ALTER COLUMN raw_page_id SET NOT NULL,
            ALTER COLUMN competitor_id SET NOT NULL,
            ALTER COLUMN controlled_topic_id SET NOT NULL,
            ALTER COLUMN controlled_topic_label SET NOT NULL;
    END IF;

    IF to_regclass('public.kpi_competitor_daily') IS NOT NULL THEN
        DELETE FROM kpi_competitor_daily
        WHERE competitor_id IS NULL OR date IS NULL;

        ALTER TABLE kpi_competitor_daily
            ALTER COLUMN competitor_id SET NOT NULL,
            ALTER COLUMN date SET NOT NULL;
    END IF;

    IF to_regclass('public.raw_pages') IS NOT NULL THEN
        DELETE FROM page_insights
        WHERE raw_page_id IN (
            SELECT id
            FROM raw_pages
            WHERE source_url_id IS NULL OR competitor_id IS NULL
        );

        DELETE FROM topic_documents
        WHERE raw_page_id IN (
            SELECT id
            FROM raw_pages
            WHERE source_url_id IS NULL OR competitor_id IS NULL
        );

        IF to_regclass('public.controlled_topic_documents') IS NOT NULL THEN
            DELETE FROM controlled_topic_documents
            WHERE raw_page_id IN (
                SELECT id
                FROM raw_pages
                WHERE source_url_id IS NULL OR competitor_id IS NULL
            );
        END IF;

        DELETE FROM raw_pages
        WHERE source_url_id IS NULL OR competitor_id IS NULL;

        ALTER TABLE raw_pages
            ALTER COLUMN source_url_id SET NOT NULL,
            ALTER COLUMN competitor_id SET NOT NULL;
    END IF;

    IF to_regclass('public.source_urls') IS NOT NULL THEN
        DELETE FROM page_insights
        WHERE raw_page_id IN (
            SELECT rp.id
            FROM raw_pages rp
            JOIN source_urls su ON su.id = rp.source_url_id
            WHERE su.competitor_id IS NULL
        );

        DELETE FROM topic_documents
        WHERE raw_page_id IN (
            SELECT rp.id
            FROM raw_pages rp
            JOIN source_urls su ON su.id = rp.source_url_id
            WHERE su.competitor_id IS NULL
        );

        IF to_regclass('public.controlled_topic_documents') IS NOT NULL THEN
            DELETE FROM controlled_topic_documents
            WHERE raw_page_id IN (
                SELECT rp.id
                FROM raw_pages rp
                JOIN source_urls su ON su.id = rp.source_url_id
                WHERE su.competitor_id IS NULL
            );
        END IF;

        DELETE FROM raw_pages
        WHERE source_url_id IN (
            SELECT id
            FROM source_urls
            WHERE competitor_id IS NULL
        );

        DELETE FROM source_urls
        WHERE competitor_id IS NULL;

        ALTER TABLE source_urls
            ALTER COLUMN competitor_id SET NOT NULL;
    END IF;
END $$;
"""

ENFORCE_CONTROLLED_DOMAIN_SQL = """
DO $$
DECLARE
    owned_domain_count INTEGER;
BEGIN
    SELECT COUNT(*)
    INTO owned_domain_count
    FROM competitors
    WHERE is_owned_domain = TRUE;

    IF owned_domain_count > 1 THEN
        RAISE EXCEPTION
            'Cannot enforce single owned domain: found % competitors with is_owned_domain=true',
            owned_domain_count;
    END IF;

    UPDATE page_insights
    SET sentiment = CASE
        WHEN lower(btrim(COALESCE(sentiment, ''))) IN (
            'positive', 'neutral', 'negative', 'mixed', 'not_found'
        )
            THEN lower(btrim(sentiment))
        ELSE 'not_found'
    END;

    UPDATE page_insights
    SET funnel_stage = CASE lower(btrim(COALESCE(funnel_stage, '')))
        WHEN 'tofu' THEN 'TOFU'
        WHEN 'mofu' THEN 'MOFU'
        WHEN 'bofu' THEN 'BOFU'
        WHEN 'retention/support' THEN 'retention/support'
        WHEN 'unknown' THEN 'unknown'
        ELSE 'unknown'
    END;

    UPDATE topic_documents
    SET funnel_stage = CASE lower(btrim(COALESCE(funnel_stage, '')))
        WHEN 'tofu' THEN 'TOFU'
        WHEN 'mofu' THEN 'MOFU'
        WHEN 'bofu' THEN 'BOFU'
        WHEN 'retention/support' THEN 'retention/support'
        WHEN 'unknown' THEN 'unknown'
        ELSE 'unknown'
    END;

    UPDATE controlled_topic_documents
    SET funnel_stage = CASE lower(btrim(COALESCE(funnel_stage, '')))
        WHEN 'tofu' THEN 'TOFU'
        WHEN 'mofu' THEN 'MOFU'
        WHEN 'bofu' THEN 'BOFU'
        WHEN 'retention/support' THEN 'retention/support'
        WHEN 'unknown' THEN 'unknown'
        ELSE 'unknown'
    END;

    UPDATE raw_pages
    SET freshness_bucket = CASE lower(btrim(COALESCE(freshness_bucket, '')))
        WHEN 'fresh' THEN 'fresh'
        WHEN 'recent' THEN 'recent'
        WHEN 'old' THEN 'old'
        WHEN 'unknown' THEN 'unknown'
        ELSE 'unknown'
    END;

    UPDATE controlled_topic_documents
    SET controlled_topic_confidence = CASE
        WHEN lower(btrim(COALESCE(controlled_topic_confidence, ''))) IN (
            'low', 'medium', 'high'
        )
            THEN lower(btrim(controlled_topic_confidence))
        ELSE 'low'
    END;

    ALTER TABLE page_insights
        ALTER COLUMN sentiment SET DEFAULT 'not_found',
        ALTER COLUMN sentiment SET NOT NULL,
        ALTER COLUMN funnel_stage SET DEFAULT 'unknown',
        ALTER COLUMN funnel_stage SET NOT NULL;

    ALTER TABLE topic_documents
        ALTER COLUMN funnel_stage SET DEFAULT 'unknown',
        ALTER COLUMN funnel_stage SET NOT NULL;

    ALTER TABLE controlled_topic_documents
        ALTER COLUMN controlled_topic_confidence SET DEFAULT 'low',
        ALTER COLUMN controlled_topic_confidence SET NOT NULL,
        ALTER COLUMN funnel_stage SET DEFAULT 'unknown',
        ALTER COLUMN funnel_stage SET NOT NULL;

    ALTER TABLE raw_pages
        ALTER COLUMN freshness_bucket SET DEFAULT 'unknown',
        ALTER COLUMN freshness_bucket SET NOT NULL;

    CREATE UNIQUE INDEX IF NOT EXISTS idx_competitors_single_owned_domain
        ON competitors ((is_owned_domain))
        WHERE is_owned_domain = TRUE;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'page_insights_sentiment_check'
          AND conrelid = 'public.page_insights'::regclass
    ) THEN
        ALTER TABLE page_insights
            ADD CONSTRAINT page_insights_sentiment_check
            CHECK (sentiment IN (
                'positive', 'neutral', 'negative', 'mixed', 'not_found'
            ));
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'page_insights_funnel_stage_check'
          AND conrelid = 'public.page_insights'::regclass
    ) THEN
        ALTER TABLE page_insights
            ADD CONSTRAINT page_insights_funnel_stage_check
            CHECK (funnel_stage IN (
                'TOFU', 'MOFU', 'BOFU', 'retention/support', 'unknown'
            ));
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'topic_documents_funnel_stage_check'
          AND conrelid = 'public.topic_documents'::regclass
    ) THEN
        ALTER TABLE topic_documents
            ADD CONSTRAINT topic_documents_funnel_stage_check
            CHECK (funnel_stage IN (
                'TOFU', 'MOFU', 'BOFU', 'retention/support', 'unknown'
            ));
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'controlled_topic_documents_funnel_stage_check'
          AND conrelid = 'public.controlled_topic_documents'::regclass
    ) THEN
        ALTER TABLE controlled_topic_documents
            ADD CONSTRAINT controlled_topic_documents_funnel_stage_check
            CHECK (funnel_stage IN (
                'TOFU', 'MOFU', 'BOFU', 'retention/support', 'unknown'
            ));
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'raw_pages_freshness_bucket_check'
          AND conrelid = 'public.raw_pages'::regclass
    ) THEN
        ALTER TABLE raw_pages
            ADD CONSTRAINT raw_pages_freshness_bucket_check
            CHECK (freshness_bucket IN ('fresh', 'recent', 'old', 'unknown'));
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'controlled_topic_confidence_check'
          AND conrelid = 'public.controlled_topic_documents'::regclass
    ) THEN
        ALTER TABLE controlled_topic_documents
            ADD CONSTRAINT controlled_topic_confidence_check
            CHECK (controlled_topic_confidence IN ('low', 'medium', 'high'));
    END IF;
END $$;
"""

CONTENT_INTELLIGENCE_MIGRATION_SQL = """
ALTER TABLE competitors
    ADD COLUMN IF NOT EXISTS is_owned_domain BOOLEAN DEFAULT FALSE;

ALTER TABLE raw_pages
    ADD COLUMN IF NOT EXISTS asset_type TEXT,
    ADD COLUMN IF NOT EXISTS language TEXT,
    ADD COLUMN IF NOT EXISTS status_code INTEGER,
    ADD COLUMN IF NOT EXISTS canonical_url TEXT,
    ADD COLUMN IF NOT EXISTS meta_description TEXT,
    ADD COLUMN IF NOT EXISTS h1 TEXT,
    ADD COLUMN IF NOT EXISTS h2_list JSONB DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS h3_list JSONB DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS published_date DATE,
    ADD COLUMN IF NOT EXISTS modified_date DATE,
    ADD COLUMN IF NOT EXISTS internal_links_count INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS external_links_count INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS faq_count INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS table_count INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS conversion_links JSONB DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS content_depth_score INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS metadata_completeness_score INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS freshness_bucket TEXT DEFAULT 'unknown';

ALTER TABLE page_insights
    ADD COLUMN IF NOT EXISTS value_proposition_themes JSONB DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS messaging_pillars JSONB DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS tone_label TEXT,
    ADD COLUMN IF NOT EXISTS tone_explanation TEXT,
    ADD COLUMN IF NOT EXISTS features JSONB DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS benefits JSONB DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS pain_points JSONB DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS proof_elements JSONB DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS cta_texts JSONB DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS cta_types JSONB DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS cta_targets JSONB DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS has_cta BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS funnel_stage TEXT DEFAULT 'unknown',
    ADD COLUMN IF NOT EXISTS search_intent TEXT DEFAULT 'unknown',
    ADD COLUMN IF NOT EXISTS has_pricing_signal BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS has_case_study_signal BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS conversion_links JSONB DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS bofu_strength_score INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS proof_score INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS freshness_score INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS structure_score INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS clarity_score INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS clarity_reason TEXT,
    ADD COLUMN IF NOT EXISTS cta_alignment_score INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS content_quality_score INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS quality_warnings JSONB DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS genericity_score INTEGER DEFAULT 0;

ALTER TABLE topic_documents
    ADD COLUMN IF NOT EXISTS funnel_stage TEXT DEFAULT 'unknown',
    ADD COLUMN IF NOT EXISTS topic_saturation TEXT DEFAULT 'low',
    ADD COLUMN IF NOT EXISTS is_gap_vs_own_site BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS emerging_status TEXT DEFAULT 'not_enough_time_series_data';

CREATE TABLE IF NOT EXISTS controlled_topic_documents (
    id SERIAL PRIMARY KEY,
    raw_page_id INTEGER NOT NULL REFERENCES raw_pages(id),
    competitor_id INTEGER NOT NULL REFERENCES competitors(id),
    controlled_topic_id TEXT NOT NULL,
    controlled_topic_label TEXT NOT NULL,
    controlled_topic_confidence TEXT NOT NULL DEFAULT 'low',
    controlled_topic_assignment_reason TEXT,
    matched_terms JSONB DEFAULT '[]'::jsonb,
    funnel_stage TEXT DEFAULT 'unknown',
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_controlled_topic_documents_raw_page_topic_unique
    ON controlled_topic_documents (raw_page_id, controlled_topic_id);

CREATE INDEX IF NOT EXISTS idx_controlled_topic_documents_competitor_id
    ON controlled_topic_documents (competitor_id);

CREATE INDEX IF NOT EXISTS idx_controlled_topic_documents_topic_id
    ON controlled_topic_documents (controlled_topic_id);
"""


def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    schema_path = repo_root / "sql" / "schema.sql"
    schema_sql = schema_path.read_text(encoding="utf-8")

    engine = get_engine()
    with engine.begin() as connection:
        connection.execute(text(REPAIR_DUPLICATES_SQL))
        connection.execute(text(PRECHECK_OWNED_DOMAIN_SQL))
        connection.execute(text(PREPARE_OWNED_DOMAIN_COLUMN_SQL))
        connection.execute(text(schema_sql))
        connection.execute(text(CONTENT_INTELLIGENCE_MIGRATION_SQL))
        connection.execute(text(ENFORCE_CORE_NOT_NULL_SQL))
        connection.execute(text(ENFORCE_CONTROLLED_DOMAIN_SQL))

    print("Database schema initialized.")


if __name__ == "__main__":
    main()
