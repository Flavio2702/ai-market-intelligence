# Apache Superset Setup

This project does not implement, embed, or install Apache Superset. Superset is an external dashboard layer that connects directly to the PostgreSQL database populated by the Python pipeline.

This guide is Windows/Docker-first. The recommended path is:

1. Prepare this project's PostgreSQL data.
2. Start Superset with Docker Desktop.
3. Connect Superset to PostgreSQL.
4. Add the PostgreSQL views as Superset datasets.
5. Build the first dashboard pages.

## Before You Start

Install or confirm these tools:

- Docker Desktop is installed and running.
- PostgreSQL is running locally.
- This project has a `.env` file with `DATABASE_URL` and `OPENAI_API_KEY`.
- `psql` is available in PowerShell.

Check from PowerShell:

```powershell
docker --version
docker compose version
psql --version
Test-Path .env
```

Your `.env` should contain a database URL like this:

```text
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/ai_market_intelligence
OPENAI_API_KEY=your_openai_api_key_here
```

If your values are different, use your actual username, password, host, port, and database name in later steps.

Owned-site topic gaps are optional. To show gaps against your own site,
`data/competitors.csv` must have exactly one row marked `is_owned_domain` with
`true`, `yes`, `1`, `y`, or `owned` before running `scripts/00_load_inputs.py`
or the full pipeline. The bundled CSV marks Demo Aurora as owned. If your database was
loaded before that CSV change, the CSV alone is not enough: run an explicit
dataset refresh and rebuild before expecting owned-domain gap charts. If no
competitor is marked as owned in PostgreSQL, topic gap analysis remains
unavailable and the report will say so explicitly.

## Step 1: Prepare The Project Database

Open PowerShell in this repository root:

```powershell
cd C:\Projects\ai-market-intelligence
```

Activate the project virtual environment:

```powershell
.\.venv\Scripts\Activate.ps1
```

Load `DATABASE_URL` from `.env` into the current PowerShell session:

```powershell
$env:DATABASE_URL = ((Get-Content .env | Where-Object { $_ -match '^DATABASE_URL=' }) -replace '^DATABASE_URL=', '')
```

Verify PowerShell can see it:

```powershell
$env:DATABASE_URL
```

Run the pipeline with small limits first:

```powershell
python scripts/run_pipeline.py --crawl-limit 15 --extract-limit 15
```

The runner initializes the schema, loads CSV inputs, crawls selected pages, extracts insights, runs topic modeling when enough pages exist, computes KPIs, refreshes the Superset-friendly views from `sql/views.sql`, and writes a Markdown report.

The topic modeling step can skip itself if there are fewer than five eligible pages. That is acceptable for the first dashboard setup; the topic charts will populate after more crawled pages exist.

Verify the dashboard views exist:

```powershell
psql $env:DATABASE_URL -c "\dv v_*"
```

Verify there is at least some data:

```powershell
psql $env:DATABASE_URL -c "SELECT COUNT(*) AS competitors FROM competitors;"
psql $env:DATABASE_URL -c "SELECT COUNT(*) AS raw_pages FROM raw_pages;"
psql $env:DATABASE_URL -c "SELECT COUNT(*) AS page_insights FROM page_insights;"
psql $env:DATABASE_URL -c "SELECT * FROM v_competitor_overview LIMIT 5;"
```

If `page_insights` is zero, the Superset connection can still be created, but most charts will be empty until `scripts/02_extract_insights.py` succeeds.

## Step 2: Start Superset With Docker

Use a separate folder outside this project for Superset:

```powershell
cd C:\Projects
git clone --depth=1 https://github.com/apache/superset.git
cd superset
docker compose -f docker-compose-image-tag.yml up -d
```

The first startup can take several minutes.

Check that containers are running:

```powershell
docker compose -f docker-compose-image-tag.yml ps
```

Open Superset:

```text
http://localhost:8088
```

For the standard Docker Compose setup, the default login is usually:

```text
username: admin
password: admin
```

If that login does not work, check the current Apache Superset Docker Compose instructions in the official docs:

```text
https://superset.apache.org/admin-docs/installation/docker-compose
```

Stop Superset when you are done:

```powershell
docker compose -f docker-compose-image-tag.yml down
```

Start it again later:

```powershell
cd C:\Projects\superset
docker compose -f docker-compose-image-tag.yml up -d
```

## Step 3: Connect Superset To PostgreSQL

When Superset runs in Docker, `localhost` means the Superset container, not your Windows machine. Use `host.docker.internal` so Superset can reach PostgreSQL on your host.

In Superset:

1. Open **Settings > Database Connections**.
2. Click **+ Database**.
3. Choose **PostgreSQL**.
4. Paste a SQLAlchemy URI.
5. Click **Test Connection**.
6. Click **Connect** or **Save**.

Use this Docker-to-host PostgreSQL example:

```text
postgresql+psycopg2://postgres:postgres@host.docker.internal:5432/ai_market_intelligence
```

Map it from your `.env`:

```text
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/ai_market_intelligence
Superset URI=postgresql+psycopg2://postgres:postgres@host.docker.internal:5432/ai_market_intelligence
```

Only the host changes from `localhost` to `host.docker.internal`, and the scheme changes from `postgresql://` to `postgresql+psycopg2://`.

If Superset is installed locally instead of Docker, use `localhost`:

```text
postgresql+psycopg2://postgres:postgres@localhost:5432/ai_market_intelligence
```

## Step 4: Add Superset Datasets

Add the views first. They are easier than raw tables because the joins and metric names are already prepared.

In Superset:

1. Open **Data > Datasets**.
2. Click **+ Dataset**.
3. Select the PostgreSQL database connection.
4. Select the schema, usually `public`.
5. Select one view from the list below.
6. Click **Create Dataset and Create Chart** or **Add**.
7. Repeat for each recommended view.

Recommended core KPI views:

- `v_core_dataset_reliability`
- `v_core_competitor_scorecards`
- `v_core_content_quality`
- `v_core_funnel_mix`
- `v_core_pain_point_positioning`
- `v_core_proof_evidence`
- `v_core_opportunity_backlog`

Diagnostics and debug views:

- `v_diagnostic_crawl_volume`
- `v_diagnostic_topic_output`
- `v_diagnostic_invalid_assets`
- `v_diagnostic_cta_coverage`
- `v_diagnostic_sentiment`

Recommended strategic topic views:

- `v_controlled_topic_coverage`
- `v_controlled_topic_gap`

Legacy compatibility views are still available for older dashboards, but they
should not be treated as the recommended KPI hierarchy. Use them when you need
continuity with an existing dashboard or deeper raw inspection:

- `v_content_inventory`
- `v_asset_type_mix`
- `v_content_depth_by_competitor`
- `v_topic_coverage`
- `v_topic_share`
- `v_topic_gap`
- `v_messaging_matrix`
- `v_pain_point_coverage`
- `v_proof_density`
- `v_funnel_mix`
- `v_cta_intelligence`
- `v_conversion_links`
- `v_bofu_strength`
- `v_content_quality`
- `v_best_content_assets`
- `v_weak_content_assets`
- `v_opportunity_backlog`
- `v_competitor_overview`
- `v_competitor_share_of_voice`
- `v_competitor_sentiment`
- `v_competitor_pricing`
- `v_competitor_features`
- `v_competitor_claims`
- `v_competitor_ctas`
- `v_page_insights_dashboard`
- `v_topic_trends`
- `v_competitive_gaps`

Legacy views may expose share-of-crawled-words, sentiment shares, tone fields,
generic CTA coverage, and raw BERTopic labels. Treat those fields as
compatibility or diagnostics only. They are not headline competitive-strength
KPI, and low-confidence topic labels should not drive strategic conclusions.
Raw BERTopic topic output is diagnostic.
Use `v_controlled_topic_coverage` and `v_controlled_topic_gap` for strategic
topic coverage and owned-site topic gaps.

Useful base tables if you need deeper inspection:

- `competitors`
- `source_urls`
- `raw_pages`
- `page_insights`
- `topic_documents`
- `controlled_topic_documents`
- `kpi_competitor_daily`

## Metric Definitions

These metrics are local proxy metrics computed from the pages you crawl. They are useful for comparing your monitored dataset, but they are not official market share, revenue, traffic, or customer metrics.

Use `v_core_*` views for headline dashboard KPI. Use `v_diagnostic_*` views for
corpus balance, extraction/debug checks, generic CTA coverage, sentiment, and
topic-label inspection. Crawl-volume metrics describe the shape of the selected
corpus, not competitive strength.

| Metric | Meaning | Source |
| --- | --- | --- |
| `pages_analyzed` | Number of successfully crawled pages for a competitor. Failed crawls are not counted. | `raw_pages`, `v_competitor_overview`, `v_competitor_share_of_voice` |
| `total_words` | Total words captured from successfully crawled pages for a competitor. | `raw_pages`, `v_competitor_overview`, `v_competitor_share_of_voice` |
| `crawled_word_share_proxy` | Competitor's share of all successfully crawled words in this local dataset. This is corpus diagnostics only, not market share. | `v_diagnostic_crawl_volume` |
| `positive_share` | Diagnostic share of extracted page insights classified as `positive` for a competitor. | `v_diagnostic_sentiment`, `v_competitor_sentiment` |
| `negative_share` | Diagnostic share of extracted page insights classified as `negative` for a competitor. | `v_diagnostic_sentiment`, `v_competitor_sentiment` |
| `neutral_share` | Diagnostic share of extracted page insights classified as `neutral` for a competitor. | `v_diagnostic_sentiment`, `v_competitor_sentiment` |
| `mixed_share` | Diagnostic share of extracted page insights classified as `mixed` for a competitor. | `v_diagnostic_sentiment`, `v_competitor_sentiment` |
| `not_found_share` | Diagnostic share of extracted page insights where sentiment could not be found. | `v_diagnostic_sentiment`, `v_competitor_sentiment` |
| `pricing_mentions` | Count of pages where the extractor found a non-empty pricing model that is not `not_found`. | `v_competitor_pricing`, `v_competitor_overview` |
| `feature_mentions` | Total number of extracted key feature items across a competitor's pages. | `v_competitor_features`, `v_competitor_overview` |
| `claims_count` | Total number of extracted marketing or product claims across a competitor's pages. | `v_competitor_claims`, `v_competitor_overview` |
| `cta_mentions` | Total number of extracted calls to action across a competitor's pages. | `v_competitor_ctas`, `v_competitor_overview` |
| `topic_probability` | BERTopic confidence-style score for a page's assigned topic, when available. BERTopic output is exploratory diagnostics only. | `v_diagnostic_topic_output`, `v_topic_trends` |
| `controlled_topic_id` | Stable ID from the config-backed strategic topic taxonomy. `unknown_other` means evidence was too weak for a strategic topic. | `v_controlled_topic_coverage`, `v_controlled_topic_gap` |
| `controlled_topic_confidence` | Confidence in the controlled topic assignment. `unknown_other` remains low confidence and is excluded from strategic gaps. | `v_controlled_topic_coverage`, `v_controlled_topic_gap` |
| `missing_pricing_count` | Number of extracted pages where pricing was empty or `not_found`. This can indicate either a real messaging gap or a page where pricing is not discussed. | `v_competitive_gaps` |
| `missing_positioning_count` | Number of extracted pages where positioning was empty or `not_found`. This can indicate weak positioning or a page that is not meant to explain positioning. | `v_competitive_gaps` |
| `objections_handled_count` | Total number of extracted objections handled across a competitor's pages. | `v_competitive_gaps` |
| `differentiators_count` | Total number of extracted differentiators across a competitor's pages. | `v_competitive_gaps` |
| `content_depth_score` | Deterministic 0-100 score based on word count, headings, FAQ, tables, and structure signals. | `v_content_inventory`, `v_content_quality` |
| `metadata_completeness_score` | Deterministic 0-100 score based on title, meta description, H1, H2, canonical, and status signal. | `v_content_inventory`, `v_content_depth_by_competitor` |
| `cta_coverage` | Diagnostic share of extracted pages with at least one detected or classified CTA. Generic CTA coverage is not a core KPI. | `v_diagnostic_cta_coverage`, `v_cta_intelligence` |
| `bofu_strength_score` | 0-100 proxy for conversion-oriented strength based on BOFU stage, pricing, case studies, proof, and CTA. | `v_bofu_strength`, `v_content_quality` |
| `content_quality_score` | Comparative corpus score over active quality dimensions. Freshness contributes only when available; unavailable freshness is excluded from Quality Score and remains diagnostic. It is not an absolute quality measure. | `v_content_quality` |

Freshness confidence, asset score confidence, and sample confidence are
intentionally different. Freshness confidence is page-level date evidence
availability. Asset score confidence is page-level confidence in the active
Quality Score dimensions. Sample confidence is competitor-level: it reflects
valid asset count and extraction coverage. Low-sample competitors are
directional only and should not be displayed as fully comparable leaders.
If the owned domain has low sample confidence, owned-site gap analysis is
`directional_only` and recommendations from those gaps are capped away from high
confidence.

Unavailable metrics should be displayed as `N/A` or not available in Superset
tables and labels, not ranked as comparable numeric values. In particular,
unavailable freshness remains a diagnostic date-evidence field and is excluded
from active Quality Score.

## Step 5: Build Dashboard Pages

Create one Superset dashboard and use tabs, sections, or naming conventions for these pages.

### 1. Executive Overview

| Chart | Source | Metric | Visualization |
| --- | --- | --- | --- |
| Dataset reliability | `v_core_dataset_reliability` | valid assets, invalid/non-evaluable pages, insight coverage, sample confidence | Table |
| Competitor scorecard | `v_core_competitor_scorecards` | sample confidence, content quality, proof, asset score confidence counts | Table |
| Average content quality | `v_core_content_quality` | `AVG(content_quality_score)` grouped by `competitor_name` | Bar Chart |
| Top opportunities | `v_core_opportunity_backlog` | priority, reason, evidence, asset type, funnel stage | Table |

For competitor scorecards, include weighted proof validation columns when they
are available. `valid` weighted proof can be compared within the local corpus;
`out_of_scale` and `unreliable` values should be displayed as diagnostics and
excluded from leaderboards or headline ranking claims.

### 2. Content Inventory

| Chart | Source | Metric | Visualization |
| --- | --- | --- | --- |
| Total assets | `v_content_depth_by_competitor` | `total_content_assets` grouped by `competitor_name` | Bar Chart |
| Asset type mix | `v_asset_type_mix` | `asset_type_share` grouped by competitor and asset type | Stacked Bar Chart |
| Asset list | `v_content_inventory` | URL, type, word count, freshness, depth, metadata | Table |

### 3. Topic & Gap Intelligence

| Chart | Source | Metric | Visualization |
| --- | --- | --- | --- |
| Controlled topic coverage | `v_controlled_topic_coverage` | controlled topic label, confidence, assignment reason, documents, saturation | Table |
| Controlled topic gaps | `v_controlled_topic_gap` | controlled topic, competitor assets, owned assets, gap status, confidence | Table |
| Raw topic assignments | `v_diagnostic_topic_output` | BERTopic label, probability, label confidence, saturation; diagnostics only | Table |
| Topic label diagnostics | `v_topic_share` | BERTopic topic share, label confidence, saturation; diagnostics only | Table |

Controlled topic coverage and controlled topic gaps are the strategic topic
layer. Raw BERTopic labels remain useful for corpus review, but do not promote
them into strategic gap analysis. `unknown_other` is intentionally visible in
coverage diagnostics and should stay out of owned-site gap opportunities.
Topic saturation requires at least 3 valid analytical documents. Saturation
values of `insufficient data` mean the topic has too little distribution to
interpret as `high`, `medium`, or `low`; filter those rows out of strategic gap
and recommendation charts.
When gap status is `directional_only`, add the status and reason to the chart
title, subtitle, or table columns so users do not read low-owned-sample gaps as
fully comparable.

### 4. Messaging & Positioning

| Chart | Source | Metric | Visualization |
| --- | --- | --- | --- |
| Messaging matrix | `v_messaging_matrix` | pillars, value themes, pain points, proof, differentiation | Table |
| Proof evidence | `v_core_proof_evidence` | normalized proof density and weighted proof points | Bar Chart |
| Pain point positioning | `v_core_pain_point_positioning` | weighted evidence, evidence mix, source URLs | Table |

### 5. Funnel & CTA Intelligence

| Chart | Source | Metric | Visualization |
| --- | --- | --- | --- |
| Funnel stage mix | `v_core_funnel_mix` | `funnel_stage_share` grouped by competitor and stage | Stacked Bar Chart |
| CTA coverage diagnostics | `v_diagnostic_cta_coverage` | current CTA coverage and CTA class mix for debugging only; not conversion readiness | Table |
| Conversion links | `v_conversion_links` | source URL and conversion target | Table |

### 6. Content Quality

| Chart | Source | Metric | Visualization |
| --- | --- | --- | --- |
| Quality ranking | `v_core_content_quality` | `content_quality_score` grouped by URL or competitor | Bar Chart |
| Best content assets | `v_best_content_assets` | score breakdown and warnings | Table |
| Weak content assets | `v_weak_content_assets` | score breakdown and warnings | Table |

### 7. Opportunity Backlog

| Chart | Source | Metric | Visualization |
| --- | --- | --- | --- |
| Opportunity table | `v_core_opportunity_backlog` | priority, topic, reason, evidence, asset type, funnel stage | Table |

Opportunity and gap tables should expose status and reason columns. Section
status is derived from row-level flags such as low sample confidence,
directional gap status, unavailable owned-gap comparison, unreliable proof, or
insufficient topic saturation; a dashboard title should not imply full
comparability when any rendered row says otherwise.

The legacy pages below are still useful if you want continuity with the original
MVP dashboard. They are compatibility/debugging pages, not the recommended KPI
hierarchy.

### 1. Competitor Overview

| Chart | Source | Metric | Visualization |
| --- | --- | --- | --- |
| Pages analyzed | `v_competitor_overview` | `SUM(pages_analyzed)` | Big Number |
| Total crawled words | `v_competitor_overview` | `SUM(total_words)` | Big Number |
| Crawled word share diagnostics | `v_competitor_share_of_voice` | `share_of_voice` grouped by `competitor_name`; corpus balance only, not market share | Bar Chart |
| Compatibility overview table | `v_competitor_overview` | pages, words, share of crawled words, diagnostic sentiment shares, pricing, features, claims, CTAs | Table |

### 2. Messaging & Positioning

| Chart | Source | Metric | Visualization |
| --- | --- | --- | --- |
| Messaging table | `v_page_insights_dashboard` | `main_value_proposition`, `target_audience`, diagnostic `tone_of_voice`, `positioning` | Table |
| Sentiment diagnostics by competitor | `v_competitor_sentiment` | positive, neutral, negative, mixed counts or shares; not headline KPI | Stacked Bar Chart |
| Claims by competitor | `v_competitor_claims` | `claims_count` grouped by `competitor_name` | Bar Chart |
| CTA mentions by competitor | `v_competitor_ctas` | `cta_mentions` grouped by `competitor_name` | Bar Chart |

### 3. Topics & Trends

| Chart | Source | Metric | Visualization |
| --- | --- | --- | --- |
| Controlled topic coverage | `v_controlled_topic_coverage` | `COUNT(*)` grouped by `controlled_topic_label`; strategic topic taxonomy | Bar Chart |
| Controlled topic gaps | `v_controlled_topic_gap` | controlled topic, competitor assets, owned assets, gap status | Table |
| Diagnostic topic volume | `v_topic_trends` | `COUNT(*)` grouped by `topic_label`; do not promote low-confidence labels | Bar Chart |
| Diagnostic topics by competitor | `v_topic_trends` | `COUNT(*)` grouped by `competitor_name` and `topic_label`; corpus review only | Heatmap |
| Topic assignment detail | `v_topic_trends` | topic label, probability, competitor, URL, source type, and label quality context | Table |

If topic views are empty, crawl more pages and rerun topic modeling. Use the
refresh script so repo-managed views are recreated in dependency-safe order:

```powershell
python scripts/01_crawl.py --limit 30
python scripts/03_topic_modeling.py --limit 100 --force
python scripts/refresh_views.py
```

### 4. Pricing & Offer

| Chart | Source | Metric | Visualization |
| --- | --- | --- | --- |
| Pricing mentions | `v_competitor_pricing` | `pricing_mentions` grouped by `competitor_name` | Bar Chart |
| Pricing model detail | `v_page_insights_dashboard` | `pricing_model`, competitor, URL, source type | Table |
| Feature mentions | `v_competitor_features` | `feature_mentions` grouped by `competitor_name` | Bar Chart |

### 5. Competitive Gaps

| Chart | Source | Metric | Visualization |
| --- | --- | --- | --- |
| Gap signals table | `v_competitive_gaps` | missing pricing, missing positioning, differentiators, objections handled | Table |
| Claims vs feature mentions | `v_competitor_overview` | `claims_count` and `feature_mentions` grouped by `competitor_name` | Bar Chart |
| Low coverage competitors | `v_competitor_overview` | `pages_analyzed` sorted ascending | Table |

## Refresh Workflow

After adding new URLs, crawling more pages, or refreshing extraction data:

```powershell
cd C:\Projects\ai-market-intelligence
.\.venv\Scripts\Activate.ps1
$env:DATABASE_URL = ((Get-Content .env | Where-Object { $_ -match '^DATABASE_URL=' }) -replace '^DATABASE_URL=', '')
python scripts/run_pipeline.py --crawl-limit 15 --extract-limit 15
```

Then in Superset:

1. Open **Data > Datasets**.
2. Open the changed dataset.
3. Click **Sync columns from source** if new columns were added.
4. Refresh the dashboard.

## Troubleshooting

### `psql` is not recognized

PostgreSQL command-line tools are not on your PATH.

Options:

- Reinstall PostgreSQL and include command-line tools.
- Add PostgreSQL's `bin` folder to PATH.
- Run `psql` from its full path, for example:

```powershell
& "C:\Program Files\PostgreSQL\16\bin\psql.exe" $env:DATABASE_URL -f sql/views.sql
```

### `DATABASE_URL` is empty in PowerShell

Load it from `.env` again:

```powershell
$env:DATABASE_URL = ((Get-Content .env | Where-Object { $_ -match '^DATABASE_URL=' }) -replace '^DATABASE_URL=', '')
$env:DATABASE_URL
```

### Superset cannot connect to PostgreSQL

Check these items:

- PostgreSQL is running.
- The database name, username, and password are correct.
- Superset Docker URI uses `host.docker.internal`, not `localhost`.
- Windows firewall is not blocking PostgreSQL.
- PostgreSQL accepts local TCP connections on port `5432`.

Test PostgreSQL from PowerShell:

```powershell
psql $env:DATABASE_URL -c "SELECT 1;"
```

If that works but Superset still fails, try the Docker host URI again:

```text
postgresql+psycopg2://postgres:postgres@host.docker.internal:5432/ai_market_intelligence
```

### Superset opens but there are no datasets

Datasets are not created automatically. Add them manually from **Data > Datasets > + Dataset** and choose the views listed in this guide.

### Superset cannot see the `v_*` views

Refresh the views from this project:

```powershell
cd C:\Projects\ai-market-intelligence
$env:DATABASE_URL = ((Get-Content .env | Where-Object { $_ -match '^DATABASE_URL=' }) -replace '^DATABASE_URL=', '')
python scripts/refresh_views.py
psql $env:DATABASE_URL -c "\dv v_*"
```

### Charts are empty

Check whether the source tables have data:

```powershell
psql $env:DATABASE_URL -c "SELECT COUNT(*) FROM raw_pages;"
psql $env:DATABASE_URL -c "SELECT COUNT(*) FROM page_insights;"
psql $env:DATABASE_URL -c "SELECT COUNT(*) FROM topic_documents;"
```

If `page_insights` is empty, run extraction:

```powershell
python scripts/02_extract_insights.py --limit 10
python scripts/04_compute_kpis.py
python scripts/refresh_views.py
```

If `topic_documents` is empty, crawl enough pages and run topic modeling:

```powershell
python scripts/01_crawl.py --limit 30
python scripts/03_topic_modeling.py --limit 100 --force
python scripts/refresh_views.py
```

### Port `8088` is already in use

Another service is using Superset's default port. Stop the other service or change the Superset Docker Compose port configuration. For a simple local setup, closing the other service is usually faster.

### Docker is slow or stuck on first startup

The first Superset Docker startup downloads images and initializes its metadata database. Give it several minutes, then check logs:

```powershell
cd C:\Projects\superset
docker compose -f docker-compose-image-tag.yml logs --tail=100
```

## Optional: Local Superset Install

Docker is recommended on Windows. If you still want a local Superset install, use a separate virtual environment outside this project.

High-level commands:

```powershell
cd C:\Projects
python -m venv superset-venv
.\superset-venv\Scripts\Activate.ps1
pip install apache_superset
$env:SUPERSET_SECRET_KEY = "replace-this-with-a-long-random-secret"
$env:FLASK_APP = "superset"
superset db upgrade
superset fab create-admin
superset init
superset run -p 8088 --with-threads --reload --debugger
```

For local installs, follow the official Superset PyPI installation guide if any command changes:

```text
https://superset.apache.org/admin-docs/installation/pypi
```

