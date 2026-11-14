import csv
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def read_repo_file(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def read_csv_header(relative_path: str) -> list[str]:
    with (REPO_ROOT / relative_path).open(newline="", encoding="utf-8") as handle:
        return next(csv.reader(handle))


def test_required_project_files_exist():
    for relative_path in [
        "sql/schema.sql",
        "sql/views.sql",
        "data/competitors.csv",
        "data/urls.csv",
        "scripts/run_pipeline.py",
        "scripts/refresh_views.py",
    ]:
        assert (REPO_ROOT / relative_path).exists()


def test_input_csvs_have_required_headers():
    assert read_csv_header("data/competitors.csv") == [
        "name",
        "website",
        "category",
        "country",
        "notes",
        "is_owned_domain",
    ]
    assert read_csv_header("data/urls.csv") == [
        "competitor_name",
        "url",
        "source_type",
    ]


def test_schema_creates_required_tables_idempotently():
    schema = read_repo_file("sql/schema.sql").lower()

    for table_name in [
        "competitors",
        "source_urls",
        "raw_pages",
        "page_insights",
        "topic_documents",
        "kpi_competitor_daily",
    ]:
        assert f"create table if not exists {table_name}" in schema


def test_schema_includes_required_constraints_and_types():
    schema = read_repo_file("sql/schema.sql").lower()

    assert "unique (competitor_id, url)" in schema
    assert "jsonb" in schema
    assert "timestamp default now()" in schema
    assert "date date not null default current_date" in schema
    assert "boolean default true" in schema
    assert "float" in schema
    assert "competitor_id integer not null references competitors(id)" in schema
    assert "source_url_id integer not null references source_urls(id)" in schema
    assert "raw_page_id integer not null references raw_pages(id)" in schema
    assert "idx_source_urls_active_order" in schema
    assert "idx_raw_pages_success_eligible_order" in schema
    assert "idx_raw_pages_success_source_content" in schema
    assert "idx_page_insights_raw_page_id_unique" in schema
    assert "idx_page_insights_pricing_present" in schema
    assert "idx_topic_documents_raw_page_id_unique" in schema
    assert "idx_topic_documents_topic_competitor_raw_page" in schema
    assert "on topic_documents (topic_id, competitor_id, raw_page_id)" in schema
    assert "idx_controlled_topic_documents_raw_page_topic_unique" in schema
    assert "idx_controlled_topic_documents_topic_competitor_raw_page" in schema
    assert (
        "on controlled_topic_documents "
        "(controlled_topic_id, competitor_id, raw_page_id)"
    ) in schema
    assert "idx_kpi_competitor_daily_competitor_date_unique" in schema
    assert "idx_page_insights_raw_page_id\n" not in schema
    assert "idx_topic_documents_raw_page_id\n" not in schema
    assert "idx_kpi_competitor_daily_competitor_id\n" not in schema


def test_schema_enforces_single_owned_domain_target_state():
    schema = read_repo_file("sql/schema.sql").lower()

    assert "idx_competitors_single_owned_domain" in schema, (
        "competitors must have a DB-level safeguard allowing at most one "
        "is_owned_domain=true row"
    )
    assert "create unique index if not exists idx_competitors_single_owned_domain" in schema
    assert "on competitors ((is_owned_domain))" in schema
    assert "where is_owned_domain = true" in schema


def test_schema_enforces_controlled_value_domains_target_state():
    schema = read_repo_file("sql/schema.sql").lower()

    expected_constraints = {
        "page_insights_sentiment_check": [
            "sentiment",
            "'positive'",
            "'neutral'",
            "'negative'",
            "'mixed'",
            "'not_found'",
        ],
        "page_insights_funnel_stage_check": [
            "funnel_stage",
            "'tofu'",
            "'mofu'",
            "'bofu'",
            "'retention/support'",
            "'unknown'",
        ],
        "topic_documents_funnel_stage_check": [
            "funnel_stage",
            "'tofu'",
            "'mofu'",
            "'bofu'",
            "'retention/support'",
            "'unknown'",
        ],
        "controlled_topic_documents_funnel_stage_check": [
            "funnel_stage",
            "'tofu'",
            "'mofu'",
            "'bofu'",
            "'retention/support'",
            "'unknown'",
        ],
        "raw_pages_freshness_bucket_check": [
            "freshness_bucket",
            "'fresh'",
            "'recent'",
            "'old'",
            "'unknown'",
        ],
        "controlled_topic_confidence_check": [
            "controlled_topic_confidence",
            "'low'",
            "'medium'",
            "'high'",
        ],
    }

    for constraint_name, expected_terms in expected_constraints.items():
        assert constraint_name in schema, (
            f"{constraint_name} must document and enforce the allowed DB value "
            "set before views or reports branch on that field"
        )
        constraint_start = schema.find(constraint_name)
        constraint_sql = schema[constraint_start : constraint_start + 600]
        assert "check" in constraint_sql
        for term in expected_terms:
            assert term in constraint_sql, (
                f"{constraint_name} is missing expected controlled value {term}"
            )


def test_db_helper_exposes_get_engine_from_database_url():
    db_py = read_repo_file("scripts/db.py")

    assert "def get_engine" in db_py
    assert "DATABASE_URL" in db_py
    assert "load_dotenv" in db_py
    assert "create_engine" in db_py


def test_init_db_reads_schema_and_uses_engine():
    init_db_py = read_repo_file("scripts/init_db.py")

    assert "schema.sql" in init_db_py
    assert "get_engine" in init_db_py
    assert "engine.begin" in init_db_py
    assert "REPAIR_DUPLICATES_SQL" in init_db_py
    assert "to_regclass('public.page_insights')" in init_db_py
    assert "to_regclass('public.topic_documents')" in init_db_py
    assert "to_regclass('public.kpi_competitor_daily')" in init_db_py
    assert "ENFORCE_CORE_NOT_NULL_SQL" in init_db_py
    assert "ENFORCE_CONTROLLED_DOMAIN_SQL" in init_db_py
    assert "PREPARE_OWNED_DOMAIN_COLUMN_SQL" in init_db_py
    assert "ALTER TABLE IF EXISTS competitors" in init_db_py
    assert "pg_attribute" in init_db_py
    assert "attname = 'is_owned_domain'" in init_db_py
    assert "ALTER COLUMN raw_page_id SET NOT NULL" in init_db_py
    assert "ALTER COLUMN source_url_id SET NOT NULL" in init_db_py


def test_init_db_adds_controlled_constraints_idempotently():
    init_db_py = read_repo_file("scripts/init_db.py")

    assert "pg_constraint" in init_db_py
    assert "Cannot enforce single owned domain" in init_db_py
    assert "CREATE UNIQUE INDEX IF NOT EXISTS idx_competitors_single_owned_domain" in init_db_py

    for constraint_name in [
        "page_insights_sentiment_check",
        "page_insights_funnel_stage_check",
        "topic_documents_funnel_stage_check",
        "controlled_topic_documents_funnel_stage_check",
        "raw_pages_freshness_bucket_check",
        "controlled_topic_confidence_check",
    ]:
        assert constraint_name in init_db_py
        assert f"conname = '{constraint_name}'" in init_db_py


def test_views_file_creates_required_superset_views():
    views = read_repo_file("sql/views.sql").lower()

    for view_name in [
        "v_competitor_share_of_voice",
        "v_competitor_sentiment",
        "v_competitor_pricing",
        "v_competitor_features",
        "v_competitor_claims",
        "v_competitor_ctas",
        "v_competitor_overview",
        "v_page_insights_dashboard",
        "v_topic_trends",
        "v_competitive_gaps",
    ]:
        assert f"create or replace view {view_name}" in views


def test_views_file_includes_required_proxy_metric_queries():
    views = read_repo_file("sql/views.sql").lower()

    assert "share_of_voice" in views
    assert "jsonb_array_length" in views
    assert "pricing_model" in views
    assert "ctas" in views
    assert "claims" in views
    assert "positive_share" in views
    assert "negative_share" in views
    assert "nullif" in views


def test_superset_setup_doc_exists():
    assert (REPO_ROOT / "docs" / "superset_setup.md").exists()


def test_superset_setup_doc_includes_required_dashboard_guidance():
    doc = read_repo_file("docs/superset_setup.md").lower()

    assert (
        "postgresql+psycopg2://postgres:postgres@host.docker.internal:5432/ai_market_intelligence"
        in doc
    )
    assert "does not implement, embed, or install apache superset" in doc
    assert "is_owned_domain" in doc
    assert "topic gap analysis remains" in doc
    assert "unavailable and the report will say so explicitly" in doc

    for page_name in [
        "competitor overview",
        "messaging & positioning",
        "topics & trends",
        "pricing & offer",
        "competitive gaps",
    ]:
        assert page_name in doc


def test_readme_includes_productization_sections():
    readme = read_repo_file("docs/OPERATIONS.md").lower()

    for section in [
        "## quickstart",
        "## recommended first experiment",
        "## limitations",
        "## do not do this in v1",
        "## troubleshooting",
    ]:
        assert section in readme

    for phrase in [
        "python scripts/run_pipeline.py --crawl-limit 15 --extract-limit 15",
        "crawled word share proxy is corpus-based",
        "ai extraction can be wrong",
        "no full internet crawling",
        "host.docker.internal",
        "is_owned_domain",
        "owned-domain gap analysis is unavailable by default",
        "raw insight records from valid insight",
        "v_content_asset_validity",
    ]:
        assert phrase in readme
