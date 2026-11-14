CREATE TABLE IF NOT EXISTS competitors (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    website TEXT NOT NULL,
    category TEXT,
    country TEXT,
    notes TEXT,
    is_owned_domain BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS source_urls (
    id SERIAL PRIMARY KEY,
    competitor_id INTEGER NOT NULL REFERENCES competitors(id),
    url TEXT NOT NULL,
    source_type TEXT NOT NULL,
    active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE (competitor_id, url)
);

CREATE TABLE IF NOT EXISTS raw_pages (
    id SERIAL PRIMARY KEY,
    source_url_id INTEGER NOT NULL REFERENCES source_urls(id),
    competitor_id INTEGER NOT NULL REFERENCES competitors(id),
    url TEXT NOT NULL,
    fetched_at TIMESTAMP DEFAULT NOW(),
    markdown TEXT,
    title TEXT,
    asset_type TEXT,
    language TEXT,
    status_code INTEGER,
    canonical_url TEXT,
    meta_description TEXT,
    h1 TEXT,
    h2_list JSONB DEFAULT '[]'::jsonb,
    h3_list JSONB DEFAULT '[]'::jsonb,
    published_date DATE,
    modified_date DATE,
    word_count INTEGER,
    internal_links_count INTEGER DEFAULT 0,
    external_links_count INTEGER DEFAULT 0,
    faq_count INTEGER DEFAULT 0,
    table_count INTEGER DEFAULT 0,
    conversion_links JSONB DEFAULT '[]'::jsonb,
    content_depth_score INTEGER DEFAULT 0,
    metadata_completeness_score INTEGER DEFAULT 0,
    freshness_bucket TEXT NOT NULL DEFAULT 'unknown',
    content_hash TEXT,
    success BOOLEAN DEFAULT TRUE,
    error_message TEXT,
    CONSTRAINT raw_pages_freshness_bucket_check
        CHECK (freshness_bucket IN ('fresh', 'recent', 'old', 'unknown'))
);

CREATE TABLE IF NOT EXISTS page_insights (
    id SERIAL PRIMARY KEY,
    raw_page_id INTEGER NOT NULL REFERENCES raw_pages(id),
    competitor_id INTEGER NOT NULL REFERENCES competitors(id),
    source_type TEXT,
    extracted_at TIMESTAMP DEFAULT NOW(),
    main_value_proposition TEXT,
    value_proposition_themes JSONB DEFAULT '[]'::jsonb,
    messaging_pillars JSONB DEFAULT '[]'::jsonb,
    target_audience TEXT,
    tone_of_voice TEXT,
    tone_label TEXT,
    tone_explanation TEXT,
    sentiment TEXT NOT NULL DEFAULT 'not_found',
    positioning TEXT,
    pricing_model TEXT,
    key_features JSONB,
    features JSONB DEFAULT '[]'::jsonb,
    benefits JSONB DEFAULT '[]'::jsonb,
    pain_points JSONB DEFAULT '[]'::jsonb,
    claims JSONB,
    proof_elements JSONB DEFAULT '[]'::jsonb,
    objections_handled JSONB,
    ctas JSONB,
    cta_texts JSONB DEFAULT '[]'::jsonb,
    cta_types JSONB DEFAULT '[]'::jsonb,
    cta_targets JSONB DEFAULT '[]'::jsonb,
    has_cta BOOLEAN DEFAULT FALSE,
    funnel_stage TEXT NOT NULL DEFAULT 'unknown',
    search_intent TEXT DEFAULT 'unknown',
    has_pricing_signal BOOLEAN DEFAULT FALSE,
    has_case_study_signal BOOLEAN DEFAULT FALSE,
    conversion_links JSONB DEFAULT '[]'::jsonb,
    bofu_strength_score INTEGER DEFAULT 0,
    proof_score INTEGER DEFAULT 0,
    freshness_score INTEGER DEFAULT 0,
    structure_score INTEGER DEFAULT 0,
    clarity_score INTEGER DEFAULT 0,
    clarity_reason TEXT,
    cta_alignment_score INTEGER DEFAULT 0,
    content_quality_score INTEGER DEFAULT 0,
    quality_warnings JSONB DEFAULT '[]'::jsonb,
    genericity_score INTEGER DEFAULT 0,
    differentiators JSONB,
    summary TEXT,
    CONSTRAINT page_insights_sentiment_check
        CHECK (sentiment IN (
            'positive', 'neutral', 'negative', 'mixed', 'not_found'
        )),
    CONSTRAINT page_insights_funnel_stage_check
        CHECK (funnel_stage IN (
            'TOFU', 'MOFU', 'BOFU', 'retention/support', 'unknown'
        ))
);

CREATE TABLE IF NOT EXISTS topic_documents (
    id SERIAL PRIMARY KEY,
    raw_page_id INTEGER NOT NULL REFERENCES raw_pages(id),
    competitor_id INTEGER NOT NULL REFERENCES competitors(id),
    topic_id INTEGER,
    topic_label TEXT,
    topic_probability FLOAT,
    funnel_stage TEXT NOT NULL DEFAULT 'unknown',
    topic_saturation TEXT DEFAULT 'low',
    is_gap_vs_own_site BOOLEAN DEFAULT FALSE,
    emerging_status TEXT DEFAULT 'not_enough_time_series_data',
    created_at TIMESTAMP DEFAULT NOW(),
    CONSTRAINT topic_documents_funnel_stage_check
        CHECK (funnel_stage IN (
            'TOFU', 'MOFU', 'BOFU', 'retention/support', 'unknown'
        ))
);

CREATE TABLE IF NOT EXISTS controlled_topic_documents (
    id SERIAL PRIMARY KEY,
    raw_page_id INTEGER NOT NULL REFERENCES raw_pages(id),
    competitor_id INTEGER NOT NULL REFERENCES competitors(id),
    controlled_topic_id TEXT NOT NULL,
    controlled_topic_label TEXT NOT NULL,
    controlled_topic_confidence TEXT NOT NULL DEFAULT 'low',
    controlled_topic_assignment_reason TEXT,
    matched_terms JSONB DEFAULT '[]'::jsonb,
    funnel_stage TEXT NOT NULL DEFAULT 'unknown',
    created_at TIMESTAMP DEFAULT NOW(),
    CONSTRAINT controlled_topic_confidence_check
        CHECK (controlled_topic_confidence IN ('low', 'medium', 'high')),
    CONSTRAINT controlled_topic_documents_funnel_stage_check
        CHECK (funnel_stage IN (
            'TOFU', 'MOFU', 'BOFU', 'retention/support', 'unknown'
        ))
);

CREATE TABLE IF NOT EXISTS kpi_competitor_daily (
    id SERIAL PRIMARY KEY,
    competitor_id INTEGER NOT NULL REFERENCES competitors(id),
    date DATE NOT NULL DEFAULT CURRENT_DATE,
    pages_analyzed INTEGER,
    total_words INTEGER,
    share_of_voice FLOAT,
    sentiment_positive_share FLOAT,
    sentiment_negative_share FLOAT,
    pricing_mentions INTEGER,
    feature_mentions INTEGER,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_source_urls_competitor_id
    ON source_urls (competitor_id);

CREATE INDEX IF NOT EXISTS idx_source_urls_active_order
    ON source_urls (competitor_id, id)
    WHERE active = TRUE;

CREATE UNIQUE INDEX IF NOT EXISTS idx_competitors_single_owned_domain
    ON competitors ((is_owned_domain))
    WHERE is_owned_domain = TRUE;

CREATE INDEX IF NOT EXISTS idx_raw_pages_source_url_id
    ON raw_pages (source_url_id);

CREATE INDEX IF NOT EXISTS idx_raw_pages_competitor_id
    ON raw_pages (competitor_id);

CREATE INDEX IF NOT EXISTS idx_raw_pages_success_eligible_order
    ON raw_pages (fetched_at, id)
    WHERE success = TRUE
      AND markdown IS NOT NULL
      AND btrim(markdown) <> '';

CREATE INDEX IF NOT EXISTS idx_raw_pages_success_source_content
    ON raw_pages (source_url_id, content_hash)
    WHERE success = TRUE AND content_hash IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_page_insights_raw_page_id_unique
    ON page_insights (raw_page_id);

CREATE INDEX IF NOT EXISTS idx_page_insights_competitor_id
    ON page_insights (competitor_id);

CREATE INDEX IF NOT EXISTS idx_page_insights_pricing_present
    ON page_insights (competitor_id, extracted_at DESC, id DESC)
    WHERE pricing_model IS NOT NULL
      AND btrim(pricing_model) <> ''
      AND lower(btrim(pricing_model)) <> 'not_found';

CREATE UNIQUE INDEX IF NOT EXISTS idx_topic_documents_raw_page_id_unique
    ON topic_documents (raw_page_id);

CREATE INDEX IF NOT EXISTS idx_topic_documents_competitor_id
    ON topic_documents (competitor_id);

CREATE INDEX IF NOT EXISTS idx_topic_documents_topic_competitor_raw_page
    ON topic_documents (topic_id, competitor_id, raw_page_id);

CREATE UNIQUE INDEX IF NOT EXISTS idx_controlled_topic_documents_raw_page_topic_unique
    ON controlled_topic_documents (raw_page_id, controlled_topic_id);

CREATE INDEX IF NOT EXISTS idx_controlled_topic_documents_competitor_id
    ON controlled_topic_documents (competitor_id);

CREATE INDEX IF NOT EXISTS idx_controlled_topic_documents_topic_id
    ON controlled_topic_documents (controlled_topic_id);

CREATE INDEX IF NOT EXISTS idx_controlled_topic_documents_topic_competitor_raw_page
    ON controlled_topic_documents (controlled_topic_id, competitor_id, raw_page_id);

CREATE INDEX IF NOT EXISTS idx_kpi_competitor_daily_date
    ON kpi_competitor_daily (date);

CREATE UNIQUE INDEX IF NOT EXISTS idx_kpi_competitor_daily_competitor_date_unique
    ON kpi_competitor_daily (competitor_id, date);
