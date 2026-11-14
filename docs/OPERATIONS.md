# AI Market Intelligence

Local-first MVP for crawling competitor pages, storing raw and structured data in PostgreSQL, extracting market intelligence with OpenAI structured outputs, computing KPIs, preparing BERTopic topic modeling outputs, and serving data to Apache Superset.

## Overview

This project is designed for a single-user local workflow. Inputs are simple CSV files. Processing happens through Python scripts. PostgreSQL is the source of truth. Superset is used only as an external dashboard layer connected to PostgreSQL.

No paid SaaS services are required except optional external API usage, especially the OpenAI API.

## Quickstart

Run these commands from the repository root.

1. Create and activate a Python virtual environment, then install dependencies:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

On Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

2. Create `.env` from the example and fill in the values:

```bash
cp .env.example .env
```

On Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

Required values:

```text
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/ai_market_intelligence
OPENAI_API_KEY=your_openai_api_key_here
```

3. Start PostgreSQL and create the database named in `DATABASE_URL`.

The pipeline initializes tables and views, but it does not create the database
itself. Verify the connection if needed:

```bash
psql "$DATABASE_URL" -c "SELECT 1;"
```

On Windows PowerShell, first load the value from `.env` if it is not already in
your shell:

```powershell
$env:DATABASE_URL = ((Get-Content .env | Where-Object { $_ -match '^DATABASE_URL=' }) -replace '^DATABASE_URL=', '')
psql $env:DATABASE_URL -c "SELECT 1;"
```

4. Edit the CSV inputs:

- `data/competitors.csv`: add the competitors you want to compare.
- `data/urls.csv`: add the exact pages to crawl for those competitors.

5. Run the local pipeline with safe first-run limits:

```bash
python scripts/run_pipeline.py --crawl-limit 15 --extract-limit 15
```

This initializes the schema, loads CSVs, crawls selected URLs, extracts
structured insights, runs topic modeling when enough documents exist, computes
KPIs, refreshes Superset-friendly views, and writes a Markdown report.

Loading CSVs resets the current dataset after validation. Each full pipeline
run replaces old competitors, URLs, raw crawls, insights, topics, and KPI
snapshots with data derived from the current CSV files.

6. Open the generated report path printed at the end, usually:

```text
outputs/reports/market_report_YYYY-MM-DD.md
```

7. Connect Apache Superset to PostgreSQL when you are ready to build dashboards.
Superset is external to this project; use
[docs/superset_setup.md](superset_setup.md) for Docker setup, connection
strings, datasets, and chart recipes.

## Recommended First Experiment

Start small so you can inspect quality before trusting any dashboard:

- Track 3 competitors.
- Add 5 URLs per competitor in `data/urls.csv`.
- Run with `--crawl-limit 15`.
- Run with `--extract-limit 15`.
- Manually review at least 5 generated `page_insights` records or report
  examples before treating the dashboard as reliable.

## Limitations

- This MVP does not calculate true market share unless you add external market,
  revenue, customer, traffic, or survey data and explicitly model it.
- Crawled Word Share Proxy is corpus-based: it is the share of successfully
  crawled words in your selected URL dataset, not a measure of the whole market
  or brand demand.
- AI extraction can be wrong. Treat extracted claims, pricing, sentiment, and
  positioning as analyst drafts that need review.
- Crawling quality depends on the selected URLs and whether pages are reachable,
  renderable, substantial, and allowed by robots.txt.
- BERTopic needs enough documents. Fewer than five eligible crawled pages will
  skip topic modeling, and small corpora can produce weak topics.

## Do Not Do This In v1

- No full internet crawling.
- Do not add automated outreach.
- Do not add paid SaaS integrations.
- Do not create fake market share numbers from proxy metrics.
- Do not build a frontend before the data pipeline is reliable.

## Architecture

```text
data/competitors.csv
data/urls.csv
        |
        v
scripts/run_pipeline.py
        |
        v
scripts/init_db.py
        |
        v
PostgreSQL schema
        |
        v
scripts/00_load_inputs.py
        |
        v
scripts/01_crawl.py
        |
        v
Raw crawl tables
        |
        v
scripts/02_extract_insights.py
        |
        v
Structured insight tables
        |
        +----------------------+
        |                      |
        v                      v
scripts/04_compute_kpis.py   scripts/03_topic_modeling.py
        |                      |
        v                      v
KPI tables/views             Topic modeling tables/files
        |                      |
        +----------+-----------+
                   |
                   v
       scripts/refresh_views.py
                   |
                   v
       scripts/05_generate_report.py
                   |
                   v
        Markdown reports and Superset dashboards
```

## Local Prerequisites

- Python 3.11 or newer
- PostgreSQL running locally
- A local PostgreSQL database for this project
- OpenAI API key for structured extraction
- Optional: Apache Superset for dashboards

## Setup

Create a virtual environment and install dependencies:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

On Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Create local environment configuration:

```bash
cp .env.example .env
```

On Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

Then edit `.env`:

```text
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/ai_market_intelligence
OPENAI_API_KEY=your_openai_api_key_here
```

Initialize the PostgreSQL schema manually if you want to validate setup before
running the full pipeline:

```bash
python scripts/init_db.py
```

## Input Files

`data/competitors.csv` contains manually curated competitor metadata:

```csv
name,website,category,country,notes,is_owned_domain
Acme Analytics,https://example.com/acme,Analytics,United States,Placeholder competitor for testing the MVP pipeline.,false
```

Optional column:

- `is_owned_domain`: set to `true`, `yes`, `1`, `y`, or `owned` for one row if
  you want owned-site topic gap analysis. Leave it blank or omit the column for
  competitor-only analysis. The bundled CSV contains fictional example domains and must be replaced before live crawling. For competitor-only datasets
  with no owned row configured in PostgreSQL, owned-domain gap analysis is unavailable by default.

`data/urls.csv` contains pages to crawl, linked by `competitor_name` to
`competitors.name`:

```csv
competitor_name,url,source_type
Acme Analytics,https://example.com/acme/pricing,pricing
```

Allowed `source_type` examples include:

- `homepage`
- `pricing`
- `product`
- `blog`
- `newsroom`
- `docs`
- `case_studies`
- `reviews`
- `comparison`

The sample rows are placeholders. Replace them with the competitors and URLs you want to monitor.

Load CSV inputs into PostgreSQL after initializing the schema:

```bash
python scripts/00_load_inputs.py
```

The loader is a full dataset refresh. It validates both CSV files first; if
validation passes, it clears old competitors, source URLs, raw crawls, extracted
insights, BERTopic assignments, controlled topic assignments, and KPI snapshots,
then loads only the current CSV contents. If validation fails, the database is
left unchanged.

## Pipeline Run Order

After `.env`, PostgreSQL, and CSV inputs are ready, run the full MVP pipeline
with one command:

```bash
python scripts/run_pipeline.py --crawl-limit 15 --extract-limit 15
```

The runner initializes the schema, loads CSV inputs, crawls pages, extracts
insights, runs topic modeling when enough documents exist, computes KPIs,
refreshes Superset-friendly views, and writes the Markdown report. It prints
each stage header and finishes with the report path.

Because CSV loading resets the dataset, running the pipeline with `--skip-crawl`
after editing CSVs will leave `raw_pages` and downstream analysis tables empty
until you run crawling and extraction again.

Useful options:

```bash
python scripts/run_pipeline.py --skip-crawl
python scripts/run_pipeline.py --skip-extraction
python scripts/run_pipeline.py --skip-topics
python scripts/run_pipeline.py --use-llm-summary
```

Use `--crawl-limit` and `--extract-limit` for first runs or small batches.
`--use-llm-summary` passes through to report generation and requires
`OPENAI_API_KEY`.

Run commands from the repository root:

```bash
python scripts/01_init_db.py
python scripts/00_load_inputs.py
python scripts/01_crawl.py --limit 3
python scripts/02_extract_insights.py --limit 3
python scripts/03_topic_modeling.py --limit 100
python scripts/04_compute_kpis.py
python scripts/refresh_views.py
python scripts/05_generate_report.py
```

`scripts/01_init_db.py` delegates to the canonical `scripts/init_db.py`
initializer. Future implementations should keep steps idempotent where possible.
The intentional exception is `scripts/00_load_inputs.py`, which resets the
configured dataset before loading fresh CSV inputs.

## Crawling Source URLs

The crawler reads active rows from `source_urls`, joins them to `competitors`,
crawls exactly those URLs with Crawl4AI, converts each page to Markdown, and
appends results to `raw_pages`.

Run a small crawl:

```bash
python scripts/01_crawl.py --limit 3
```

Optional filters:

```bash
python scripts/01_crawl.py --competitor "Acme Analytics"
python scripts/01_crawl.py --source-type pricing
python scripts/01_crawl.py --competitor "Acme Analytics" --source-type pricing --limit 3
```

Successful non-empty pages store Markdown, word count, content hash, and
`success = TRUE`. Failed crawls are stored with `success = FALSE` and an error
message. Previous `raw_pages` records are not deleted, but an unchanged
successful page for the same configured URL is skipped by content hash so reruns
do not inflate downstream metrics with identical crawl records.

`scripts/02_crawl_pages.py` remains available as a compatibility wrapper and
delegates to the canonical `scripts/01_crawl.py` entrypoint.

## Extracting Page Insights

The extractor reads successful crawled pages from `raw_pages`, sends each page's
Markdown to the OpenAI API, validates the structured response with Pydantic, and
stores one normalized record in `page_insights`.

Required environment variable:

```text
OPENAI_API_KEY=your_openai_api_key_here
```

Optional environment variable:

```text
OPENAI_MODEL=gpt-4.1
```

If `OPENAI_MODEL` is not set, the extractor defaults to `gpt-4o-mini`.

Start with a small limited run to control API spend:

```bash
python scripts/02_extract_insights.py --limit 3
```

Every eligible page can trigger an OpenAI API call, so use `--limit` for first
runs and batch cautiously as your crawl volume grows.

Optional filters:

```bash
python scripts/02_extract_insights.py --competitor "Acme Analytics"
python scripts/02_extract_insights.py --source-type pricing
python scripts/02_extract_insights.py --competitor "Acme Analytics" --source-type pricing --limit 3
```

By default, pages that already have `page_insights` are skipped so reruns do not
duplicate rows. Use `--force` to refresh existing insights for matching pages:

```bash
python scripts/02_extract_insights.py --force --limit 3
```

`scripts/03_extract_insights.py` remains available as a compatibility wrapper
and delegates to the canonical `scripts/02_extract_insights.py` entrypoint.
The database also enforces one insight row per raw page as a final idempotency
guard.

Extraction uses sanitized page text for both LLM prompt construction and
deterministic pain point classification. The sanitizer removes technical crawl
artifacts such as URL-encoded fragments, image paths, query strings, token-like
strings, and boilerplate before classification. Raw crawl Markdown remains in
`raw_pages` for diagnostics; the cleaned text is the analytical input. Discarded
sanitization fragments are logged in sanitizer metadata with explicit reasons such as
`technical_fragment` or `empty_after_sanitization` so weak evidence can be
audited instead of silently promoted.

## Computing KPI Proxy Metrics

KPI outputs in this MVP are local proxy indicators from the selected crawl
corpus. The current KPI hierarchy separates decision-useful KPI from diagnostics
and legacy compatibility fields:

- Core KPI: dataset reliability, sample confidence, content quality, funnel mix,
  proof evidence, pain point positioning, and opportunity backlog.
- Diagnostics: crawl volume, raw topic output, invalid or non-evaluable assets,
  generic CTA coverage, sentiment shares, and other technical context.
- Legacy compatibility: legacy view names remain available for existing
  dashboards, but they are not headline KPI unless they are also exposed through
  the `v_core_*` views.

These outputs are not true market share numbers, revenue share, customer share,
or externally validated market size estimates.

Crawled Word Share Proxy is not market share. In this project, the public report
label means a competitor's share of successfully crawled words in this local
dataset, not its actual share of customers, revenue, traffic, brand demand, or
the broader market. The legacy database column remains `share_of_voice` for
compatibility.

After crawling pages and extracting insights, compute the daily competitor KPI
snapshot:

```bash
python scripts/04_compute_kpis.py
```

The script upserts today's `kpi_competitor_daily` rows in a single transaction,
so running it twice on the same day updates the existing snapshot instead of
duplicating or deleting rows first. It calculates pages analyzed, total crawled
words, crawled word share proxy, positive and negative sentiment shares, pricing
mentions, and feature mentions for compatibility. Crawled word volume and
sentiment shares are corpus diagnostics, not competitive strength or headline
dashboard KPI.
The database enforces one KPI snapshot per competitor per date.

Create or refresh the Superset-friendly views:

```bash
python scripts/refresh_views.py
```

The views include additive `v_core_*` datasets for decision-useful KPI and
`v_diagnostic_*` datasets for crawl volume, raw topic output, invalid assets,
CTA coverage, sentiment, and other technical context. Legacy view names remain
available for dashboard compatibility, but crawled word share proxy, sentiment,
generic CTA coverage, tone fields, and raw or low-confidence topic output are
diagnostics, not strategic KPI. Weak legacy metrics are diagnostics, not strategic KPI.
Apache Superset is external to this project and can connect directly to
PostgreSQL to use these tables and views as datasets.

`valid_assets` means assets that passed the analytical validity gate and have
usable extracted insight. Extraction coverage uses a separate
`extraction_eligible_assets` denominator so missing-insight pages can lower
coverage instead of making coverage 100 percent by construction.
Report dataset tables distinguish raw insight records from valid insight
records. Invalid-asset insight records can exist for diagnostics when an
extraction was produced before a page was later classified as placeholder, thin,
or otherwise non-evaluable; they must not feed core KPI or strategic sections.

## Reliability Rules

The reliability hardening sprint is designed to prevent weak evidence from
being presented as more comparable or strategic than it is. It does not make
scores higher, more optimistic, or more complete.

Quality Score uses active evidence dimensions only. When freshness is
unavailable, freshness is excluded from Quality Score and the remaining active
weights are redistributed across depth, proof, structure, clarity, and CTA
alignment. Freshness remains visible as a diagnostic field, but missing dates do
not automatically make the whole asset score low confidence.

The report and core views separate three confidence concepts:

- `Freshness Confidence`: page-level date evidence availability.
- `Asset Score Confidence`: page-level confidence in the active Quality Score
  dimensions, based on evidence quality, proof, structure, clarity, CTA
  alignment, and warnings.
- `Sample Confidence`: competitor-level confidence based on valid asset count
  and extraction coverage over extraction-eligible assets.

Low sample confidence means a competitor is directional only. Low-sample
competitors may remain visible for review, but they must not be treated as
fully comparable leaders, principal ranking winners, or high-confidence
recommendation sources. If the owned domain has low sample confidence,
owned-site gap analysis is marked `directional_only` and owned-gap opportunity
confidence is capped away from high confidence.

Proof density is calculated on valid analytical assets. Weighted Proof Points
per Valid Asset sums deduplicated recognized proof weights from valid assets and
divides by real `valid_assets`; configured URL counts are not the denominator.
This keeps proof scoring tied to usable analytical evidence rather than input
volume.

Weighted proof scores are validated before report interpretation. A `valid`
score is within the expected range and internally plausible for the available
proof mix. An `out_of_scale` score exceeds the defined metric range. An
`unreliable` score is internally incoherent, for example when weighted proof is
too high despite zero strong proof. Flagged proof values may remain visible as
diagnostics, but they are not comparable ranking values and must not support
leader claims.

Report section status is derived from row-level evidence, confidence, and gap
flags. A section header such as `fully comparable`, `directional only`, or
`not evaluable` must not be trusted if the underlying rows contain
contradictory blockers; the row flags and status reasons are the source of
truth.

Unavailable metrics render as `N/A` or `not available`, not as comparable
numeric values. For example, unavailable freshness can remain visible as a
date-evidence diagnostic, but it is excluded from active Quality Score and
should not be ranked as if it were measured.

Pain point evidence uses controlled evidence classes:

- `explicit`: visible problem or friction language with source text.
- `inferred_from_benefit`: benefit wording that implies a problem being solved.
- `keyword_fallback`: weak category-specific keyword support only.
- `not_pain_point`: copy that should not become pain-point evidence.

Fallback-only and fallback-heavy pain point opportunities remain low confidence.
Medium opportunity confidence requires explicit evidence or multiple inferred
source URLs; keyword volume alone must not promote an opportunity.

Strategic topic analysis uses the controlled taxonomy in
`config/content_topics.yml`, not raw BERTopic token labels. The MVP taxonomy has
at most five strategic topics plus `unknown_other`. Valid assets can receive
zero or more controlled topics; when evidence is too weak, they receive
`unknown_other` with low confidence and an explicit insufficient-evidence
reason. BERTopic labels such as `download / audio / tracks` remain exploratory
diagnostics only.

Topic saturation requires at least 3 valid analytical documents across the
topic. Topics below that threshold use `insufficient data`, not `high`,
`medium`, or `low`, and must not drive high-confidence topic gaps or
recommendations.

For Docker or local Superset setup, PostgreSQL connection strings, recommended
datasets, and first-dashboard chart recipes, see
[docs/superset_setup.md](superset_setup.md).

## Topic Modeling

The topic modeling script reads successful crawled pages from `raw_pages`, fits
a BERTopic model in multilingual mode, and stores one document-topic assignment
per page in `topic_documents`. BERTopic output is kept for exploratory corpus
diagnostics and legacy dashboard compatibility.

The same script also applies the controlled strategic topic taxonomy from
`config/content_topics.yml` and stores 0-N controlled topic assignments per
valid page in `controlled_topic_documents`. Strategic topic coverage and
owned-site topic gap analysis use these controlled labels through
`v_controlled_topic_coverage` and `v_controlled_topic_gap`. If no controlled
topic has enough evidence, the page receives `unknown_other` with low
confidence instead of being forced into a weak topic.

Run a limited batch:

```bash
python scripts/03_topic_modeling.py --limit 100
```

Eligible pages must have `success = TRUE`, non-empty Markdown, and
`word_count >= --min-words`. The default minimum is 150 words:

```bash
python scripts/03_topic_modeling.py --min-words 150 --limit 100
```

By default, pages that already have `topic_documents` rows are skipped so reruns
do not duplicate topic assignments. This also skips controlled topic assignment
refresh for those pages. Use `--force` to refresh existing BERTopic and
controlled topic rows for matching pages:

```bash
python scripts/03_topic_modeling.py --force --limit 100
```

This step does not call the OpenAI API and does not require `OPENAI_API_KEY`.
Topic quality improves as the crawl corpus grows; very small corpora can produce
weak or mostly outlier topics. If fewer than five eligible documents are
available, the script prints a clear message and exits without error.

Model artifacts are optional for v1. If model saving is added later, save files
under `outputs/models/` so generated artifacts stay separate from source code.

`scripts/05_prepare_topics.py` remains available as a compatibility wrapper and
delegates to the canonical `scripts/03_topic_modeling.py` entrypoint.
The database enforces one BERTopic assignment per raw page, while controlled
topic assignments are stored separately to allow multiple controlled topics per
valid asset.

## Generating Markdown Reports

The report generator creates a readable Markdown market intelligence report from
the data already stored in PostgreSQL. It does not crawl the web, perform
uncontrolled research, or require the OpenAI API by default.

Run:

```bash
python scripts/05_generate_report.py
```

By default this writes:

```text
outputs/reports/market_report_YYYY-MM-DD.md
```

Optional arguments:

```bash
python scripts/05_generate_report.py --date 2026-04-27
python scripts/05_generate_report.py --output-dir outputs/reports
python scripts/05_generate_report.py --use-llm-summary
```

`--use-llm-summary` uses OpenAI only to polish the Executive Summary from
database-derived facts. It does not add external research and must not invent
competitor facts or market share. Without this flag, the full report is
deterministic and generated from SQL results.

The report includes dataset scope, competitor overview, Crawled Word Share
Proxy diagnostics, messaging and positioning, pricing signals, feature and claim
analysis, topic diagnostics, opportunities, risks, and recommended next research
actions. Crawled Word Share Proxy remains based on crawled content volume; it is
not true market share unless external market data is provided and explicitly
modeled.

Tone, positive/negative sentiment share, generic competitor-level CTA coverage,
and low-confidence topics are intentionally excluded from headline report KPI.
The final CTA decision for this sprint is removal from the main KPI hierarchy:
CTA extraction/storage and CTA class mix remain available for diagnostics, while
page-type-aware CTA intent alignment is deferred for a later, testable feature.
Sample confidence and asset score confidence are separate signals: sample
confidence summarizes competitor-level valid asset count plus extraction
coverage over extraction-eligible assets, while asset score confidence reflects
per-asset uncertainty from active scoring evidence and warnings. Freshness
confidence is separate: unavailable freshness is excluded from Quality Score
and remains a diagnostic date-evidence signal.
Report display gates fragile KPI: low sample confidence is shown as
`low / directional only`, low asset score confidence is shown as
`low confidence`, and owned-domain gap sections include a nearby status header
when the owned sample is directional. Directional rows may remain visible for
analysis, but they must not be treated as uncaveated leaders, principal
rankings, or high-confidence recommendations.

## Data Quality Checks

Run the local data quality summary after loading, crawling, extraction, KPI
computation, or topic modeling:

```bash
python scripts/check_data_quality.py
```

The command reports competitor and source URL counts, successful and failed raw
pages, short crawled pages, extraction-eligible assets, valid analytical assets,
extracted insights, invalid-asset insight records, topic documents, and the
latest KPI snapshot date. The validity counts come from
`v_content_asset_validity`, the same canonical validity layer used by the
report and core SQL views. The command also prints warnings for weak MVP data
coverage, including too few competitors, too few successful pages, valid
analytical asset coverage below 80%, no configured pricing pages, or no topic
documents.

Warnings are informational local quality signals. They help avoid silent
failures and weak analytics, but they do not fail the command.

## Expected Outputs

The implemented pipeline should produce:

- Raw crawl records in PostgreSQL.
- Structured page insights in PostgreSQL.
- KPI tables or views in PostgreSQL for Superset.
- Topic modeling inputs and outputs from BERTopic.
- Markdown reports under `outputs/reports/`.

Apache Superset should connect directly to PostgreSQL and use the KPI, insight, and topic tables or views as datasets.

## Troubleshooting

### Database connection fails

Check that PostgreSQL is running, the database named in `DATABASE_URL` exists,
and the username, password, host, and port in `.env` are correct. The pipeline
creates tables inside an existing database; it does not create the database.

Test the connection:

```bash
psql "$DATABASE_URL" -c "SELECT 1;"
python scripts/init_db.py
```

On Windows PowerShell, load `DATABASE_URL` from `.env` first if needed:

```powershell
$env:DATABASE_URL = ((Get-Content .env | Where-Object { $_ -match '^DATABASE_URL=' }) -replace '^DATABASE_URL=', '')
psql $env:DATABASE_URL -c "SELECT 1;"
python scripts/init_db.py
```

### Crawl4AI fails

Verify dependencies were installed with `pip install -r requirements.txt`.
Then check whether the URL is reachable in a browser, blocked by robots.txt,
requires login, or renders too little text for useful analysis. Crawl failures
are stored in `raw_pages` with `success = FALSE` and an error message.

### OpenAI key missing

Set `OPENAI_API_KEY` in `.env`. Extraction and `--use-llm-summary` require it.
Start with an extraction limit to control API spend:

```bash
python scripts/run_pipeline.py --crawl-limit 15 --extract-limit 15
```

### BERTopic has too few documents

Topic modeling needs at least five eligible documents. Eligible pages must be
successful crawls, non-empty, and at least the configured `--min-words`
threshold, which defaults to 150. Add better URLs or crawl more substantial
pages, then rerun the pipeline.

### Superset cannot connect to PostgreSQL

If Superset runs in Docker, use `host.docker.internal` instead of `localhost`
in the Superset SQLAlchemy URI:

```text
postgresql+psycopg2://postgres:postgres@host.docker.internal:5432/ai_market_intelligence
```

Refresh PostgreSQL views before adding datasets:

```bash
python scripts/refresh_views.py
```

See [docs/superset_setup.md](superset_setup.md) for the full setup and
dashboard guide.

## Testing

Run tests with:

```bash
pytest
```

External API calls should be mocked in automated tests unless an explicit integration test is added.
