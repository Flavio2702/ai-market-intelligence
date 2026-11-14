"""Crawl active source URLs with Crawl4AI and store raw Markdown pages."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

from sqlalchemy import text

from db import get_engine


REPO_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class SourceUrl:
    id: int
    competitor_id: int
    competitor_name: str
    url: str
    source_type: str


@dataclass(frozen=True)
class PageContent:
    markdown: str
    word_count: int
    content_hash: str


@dataclass(frozen=True)
class ParsedPageSignals:
    title: str | None
    asset_type: str
    language: str | None
    status_code: int | None
    canonical_url: str | None
    meta_description: str | None
    h1: str | None
    h2_list: list[str]
    h3_list: list[str]
    published_date: date | None
    modified_date: date | None
    internal_links_count: int
    external_links_count: int
    faq_count: int
    table_count: int
    conversion_links: list[str]
    content_depth_score: int
    metadata_completeness_score: int
    freshness_bucket: str


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Crawl the active URLs listed in data/urls.csv after they are loaded "
            "into PostgreSQL, then append raw Markdown records to raw_pages."
        )
    )
    parser.add_argument(
        "--limit",
        type=positive_int,
        help="Maximum URLs to crawl. Use 15 for the recommended first experiment.",
    )
    parser.add_argument("--competitor", help="Only crawl URLs for this exact competitor name.")
    parser.add_argument(
        "--source-type",
        help="Only crawl URLs with this source_type, such as pricing or product.",
    )
    return parser.parse_args(argv)


def build_source_url_query(args: argparse.Namespace) -> tuple[Any, dict[str, Any]]:
    conditions = ["su.active = TRUE"]
    params: dict[str, Any] = {}

    if args.competitor:
        conditions.append("c.name = :competitor")
        params["competitor"] = args.competitor

    if args.source_type:
        conditions.append("su.source_type = :source_type")
        params["source_type"] = args.source_type

    sql = f"""
        SELECT
            su.id AS source_url_id,
            su.competitor_id,
            c.name AS competitor_name,
            su.url,
            su.source_type
        FROM source_urls su
        JOIN competitors c ON c.id = su.competitor_id
        WHERE {" AND ".join(conditions)}
        ORDER BY c.name, su.id
    """

    if args.limit:
        sql += "\n        LIMIT :limit"
        params["limit"] = args.limit

    return text(sql), params


def fetch_source_urls(connection, args: argparse.Namespace) -> list[SourceUrl]:
    statement, params = build_source_url_query(args)
    rows = connection.execute(statement, params)

    return [
        SourceUrl(
            id=row._mapping["source_url_id"],
            competitor_id=row._mapping["competitor_id"],
            competitor_name=row._mapping["competitor_name"],
            url=row._mapping["url"],
            source_type=row._mapping["source_type"],
        )
        for row in rows
    ]


def extract_markdown(result: Any) -> str:
    markdown = getattr(result, "markdown", "")
    raw_markdown = getattr(markdown, "raw_markdown", None)

    if raw_markdown is not None:
        return str(raw_markdown).strip()

    return str(markdown or "").strip()


def extract_title(result: Any) -> str | None:
    title = getattr(result, "title", None)
    if title:
        return str(title).strip()

    metadata = getattr(result, "metadata", None)
    if isinstance(metadata, dict) and metadata.get("title"):
        return str(metadata["title"]).strip()

    return None


def extract_metadata(result: Any) -> dict[str, Any]:
    metadata = getattr(result, "metadata", None)
    return metadata if isinstance(metadata, dict) else {}


def extract_html(result: Any) -> str:
    for attribute in ("cleaned_html", "html", "fit_html"):
        value = getattr(result, attribute, None)
        if value:
            return str(value)
    return ""


def first_metadata_value(metadata: dict[str, Any], keys: list[str]) -> str | None:
    for key in keys:
        value = metadata.get(key)
        if value:
            return str(value).strip()
    return None


def parse_date(value: str | None) -> date | None:
    if not value:
        return None
    match = re.search(r"(20\d{2}|19\d{2})[-/](\d{1,2})[-/](\d{1,2})", value)
    if not match:
        return None
    year, month, day = (int(part) for part in match.groups())
    try:
        return date(year, month, day)
    except ValueError:
        return None


def extract_headings(markdown: str, level: int) -> list[str]:
    prefix = "#" * level
    pattern = rf"^{re.escape(prefix)}\s+(.+?)\s*$"
    return [
        normalize_inline_text(match.group(1))
        for match in re.finditer(pattern, markdown, flags=re.MULTILINE)
        if normalize_inline_text(match.group(1))
    ]


def normalize_inline_text(value: str) -> str:
    value = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", value)
    value = re.sub(r"[*_`#>]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def classify_asset_type(url: str, source_type: str | None) -> str:
    normalized_source = (source_type or "").strip().lower()
    if normalized_source:
        return normalized_source

    parsed = urlparse(url)
    path = parsed.path.lower().strip("/")
    if not path:
        return "homepage"

    patterns = [
        ("pricing", ("pricing", "plans")),
        ("blog", ("blog", "articles", "news")),
        ("docs", ("docs", "documentation", "guide", "help", "support")),
        ("faq", ("faq", "questions")),
        ("case_studies", ("case", "customer", "story", "stories")),
        ("comparison", ("compare", "comparison", "versus", "vs")),
        ("product", ("product", "features", "apps", "technology", "demo")),
        ("reviews", ("review", "reviews", "testimonials")),
    ]
    for asset_type, tokens in patterns:
        if any(token in path for token in tokens):
            return asset_type
    return "other"


def extract_markdown_links(markdown: str, base_url: str) -> tuple[int, int, list[str]]:
    parsed_base = urlparse(base_url)
    internal = 0
    external = 0
    conversion_links: list[str] = []
    conversion_tokens = (
        "pricing",
        "demo",
        "contact",
        "signup",
        "sign-up",
        "trial",
        "case",
        "customers",
        "comparison",
        "quote",
    )
    seen_conversion: set[str] = set()

    for match in re.finditer(r"\[[^\]]+\]\(([^)]+)\)", markdown):
        href = match.group(1).split()[0].strip("<>")
        if not href or href.startswith(("mailto:", "tel:", "#")):
            continue
        absolute = urljoin(base_url, href)
        parsed_href = urlparse(absolute)
        if parsed_href.netloc and parsed_href.netloc != parsed_base.netloc:
            external += 1
        else:
            internal += 1
            lowered = absolute.lower()
            if any(token in lowered for token in conversion_tokens):
                if absolute not in seen_conversion:
                    conversion_links.append(absolute)
                    seen_conversion.add(absolute)

    return internal, external, conversion_links[:20]


def count_faqs(markdown: str) -> int:
    return len(re.findall(r"\b(faq|frequently asked|question:|\bq:)", markdown, re.I))


def count_tables(markdown: str, html: str) -> int:
    markdown_tables = len(re.findall(r"^\s*\|.+\|\s*$", markdown, re.MULTILINE))
    html_tables = len(re.findall(r"<table\b", html, re.I))
    return max(html_tables, 1 if markdown_tables >= 2 else 0)


def score_content_depth(word_count: int, h2_count: int, h3_count: int, faq_count: int, table_count: int) -> int:
    score = 0
    score += min(40, word_count // 30)
    score += min(25, h2_count * 5)
    score += min(15, h3_count * 3)
    score += 10 if faq_count else 0
    score += 10 if table_count else 0
    return min(100, score)


def score_metadata_completeness(
    *,
    title: str | None,
    meta_description: str | None,
    h1: str | None,
    h2_list: list[str],
    canonical_url: str | None,
    status_code: int | None,
) -> int:
    score = 0
    score += 20 if title else 0
    score += 20 if meta_description else 0
    score += 20 if h1 else 0
    score += 15 if h2_list else 0
    score += 15 if canonical_url else 0
    score += 10 if status_code is None or 200 <= status_code < 400 else 0
    return min(100, score)


def freshness_bucket(published_date: date | None, modified_date: date | None) -> str:
    reference = modified_date or published_date
    if reference is None:
        return "unknown"
    age_days = (date.today() - reference).days
    if age_days <= 90:
        return "fresh"
    if age_days <= 365:
        return "recent"
    return "old"


def parse_page_signals(result: Any, source: SourceUrl, markdown: str) -> ParsedPageSignals:
    metadata = extract_metadata(result)
    html = extract_html(result)
    title = extract_title(result)
    meta_description = first_metadata_value(
        metadata,
        ["description", "meta_description", "og:description", "twitter:description"],
    )
    canonical_url = first_metadata_value(metadata, ["canonical", "canonical_url"])
    language = first_metadata_value(metadata, ["language", "lang"])
    status_code = getattr(result, "status_code", None) or metadata.get("status_code")
    status_code = int(status_code) if str(status_code or "").isdigit() else None
    h1_list = extract_headings(markdown, 1)
    h2_list = extract_headings(markdown, 2)
    h3_list = extract_headings(markdown, 3)
    published = parse_date(
        first_metadata_value(metadata, ["datePublished", "published_time", "published"])
        or source.url
        or markdown[:2000]
    )
    modified = parse_date(
        first_metadata_value(metadata, ["dateModified", "modified_time", "modified"])
    )
    internal_links, external_links, conversion_links = extract_markdown_links(
        markdown,
        source.url,
    )
    faq_count = count_faqs(markdown)
    table_count = count_tables(markdown, html)
    word_count = len(markdown.strip().split())
    depth_score = score_content_depth(
        word_count,
        len(h2_list),
        len(h3_list),
        faq_count,
        table_count,
    )
    metadata_score = score_metadata_completeness(
        title=title,
        meta_description=meta_description,
        h1=h1_list[0] if h1_list else None,
        h2_list=h2_list,
        canonical_url=canonical_url,
        status_code=status_code,
    )

    return ParsedPageSignals(
        title=title,
        asset_type=classify_asset_type(source.url, source.source_type),
        language=language,
        status_code=status_code,
        canonical_url=canonical_url,
        meta_description=meta_description,
        h1=h1_list[0] if h1_list else None,
        h2_list=h2_list[:50],
        h3_list=h3_list[:100],
        published_date=published,
        modified_date=modified,
        internal_links_count=internal_links,
        external_links_count=external_links,
        faq_count=faq_count,
        table_count=table_count,
        conversion_links=conversion_links,
        content_depth_score=depth_score,
        metadata_completeness_score=metadata_score,
        freshness_bucket=freshness_bucket(published, modified),
    )


def prepare_page_content(markdown: str) -> PageContent:
    normalized = markdown.strip()
    return PageContent(
        markdown=normalized,
        word_count=len(normalized.split()),
        content_hash=hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
    )


def ensure_crawl4ai_base_directory() -> Path:
    base_directory = Path(
        os.getenv("CRAWL4_AI_BASE_DIRECTORY", str(REPO_ROOT))
    ).resolve()
    os.environ.setdefault("CRAWL4_AI_BASE_DIRECTORY", str(base_directory))
    (base_directory / ".crawl4ai").mkdir(parents=True, exist_ok=True)
    return base_directory


def save_raw_page(
    connection,
    source: SourceUrl,
    *,
    markdown: str = "",
    signals: ParsedPageSignals | None = None,
    title: str | None = None,
    success: bool,
    error_message: str | None = None,
) -> bool:
    if success and not markdown.strip():
        return False

    content = prepare_page_content(markdown) if markdown.strip() else None
    if content and raw_page_exists(connection, source.id, content.content_hash):
        return False

    result = connection.execute(
        text(
            """
            INSERT INTO raw_pages (
                source_url_id,
                competitor_id,
                url,
                markdown,
                title,
                asset_type,
                language,
                status_code,
                canonical_url,
                meta_description,
                h1,
                h2_list,
                h3_list,
                published_date,
                modified_date,
                word_count,
                internal_links_count,
                external_links_count,
                faq_count,
                table_count,
                conversion_links,
                content_depth_score,
                metadata_completeness_score,
                freshness_bucket,
                content_hash,
                success,
                error_message
            )
            VALUES (
                :source_url_id,
                :competitor_id,
                :url,
                :markdown,
                :title,
                :asset_type,
                :language,
                :status_code,
                :canonical_url,
                :meta_description,
                :h1,
                CAST(:h2_list AS JSONB),
                CAST(:h3_list AS JSONB),
                :published_date,
                :modified_date,
                :word_count,
                :internal_links_count,
                :external_links_count,
                :faq_count,
                :table_count,
                CAST(:conversion_links AS JSONB),
                :content_depth_score,
                :metadata_completeness_score,
                :freshness_bucket,
                :content_hash,
                :success,
                :error_message
            )
            """
        ),
        {
            "source_url_id": source.id,
            "competitor_id": source.competitor_id,
            "url": source.url,
            "markdown": content.markdown if content else None,
            "title": signals.title if signals else title,
            "asset_type": signals.asset_type if signals else classify_asset_type(source.url, source.source_type),
            "language": signals.language if signals else None,
            "status_code": signals.status_code if signals else None,
            "canonical_url": signals.canonical_url if signals else None,
            "meta_description": signals.meta_description if signals else None,
            "h1": signals.h1 if signals else None,
            "h2_list": json.dumps(signals.h2_list if signals else []),
            "h3_list": json.dumps(signals.h3_list if signals else []),
            "published_date": signals.published_date if signals else None,
            "modified_date": signals.modified_date if signals else None,
            "word_count": content.word_count if content else 0,
            "internal_links_count": signals.internal_links_count if signals else 0,
            "external_links_count": signals.external_links_count if signals else 0,
            "faq_count": signals.faq_count if signals else 0,
            "table_count": signals.table_count if signals else 0,
            "conversion_links": json.dumps(signals.conversion_links if signals else []),
            "content_depth_score": signals.content_depth_score if signals else 0,
            "metadata_completeness_score": signals.metadata_completeness_score if signals else 0,
            "freshness_bucket": signals.freshness_bucket if signals else "unknown",
            "content_hash": content.content_hash if content else None,
            "success": success,
            "error_message": error_message,
        },
    )
    return result.rowcount == 1


def raw_page_exists(connection, source_url_id: int, content_hash: str) -> bool:
    result = connection.execute(
        text(
            """
            SELECT 1
            FROM raw_pages
            WHERE source_url_id = :source_url_id
              AND content_hash = :content_hash
              AND success = TRUE
            LIMIT 1
            """
        ),
        {"source_url_id": source_url_id, "content_hash": content_hash},
    )
    return next(iter(result), None) is not None


async def crawl_one(crawler, run_config, engine, source: SourceUrl) -> str:
    try:
        result = await crawler.arun(url=source.url, config=run_config)
    except Exception as exc:  # Crawl/network failures should not stop the batch.
        with engine.begin() as connection:
            save_raw_page(
                connection,
                source,
                success=False,
                error_message=f"{type(exc).__name__}: {exc}",
            )
        return "failed"

    if not getattr(result, "success", False):
        error_message = getattr(result, "error_message", None) or "Crawl failed"
        with engine.begin() as connection:
            save_raw_page(
                connection,
                source,
                success=False,
                error_message=str(error_message),
            )
        return "failed"

    markdown = extract_markdown(result)
    if not markdown.strip():
        return "skipped_empty"

    with engine.begin() as connection:
        signals = parse_page_signals(result, source, markdown)
        saved = save_raw_page(
            connection,
            source,
            markdown=markdown,
            signals=signals,
            success=True,
        )
    return "saved" if saved else "skipped_duplicate"


async def crawl_sources(engine, sources: list[SourceUrl]) -> dict[str, int]:
    ensure_crawl4ai_base_directory()
    from crawl4ai import AsyncWebCrawler, CrawlerRunConfig

    run_config = CrawlerRunConfig(check_robots_txt=True)
    counts = {"saved": 0, "failed": 0, "skipped_empty": 0, "skipped_duplicate": 0}

    async with AsyncWebCrawler() as crawler:
        for index, source in enumerate(sources, start=1):
            print(
                f"[{index}/{len(sources)}] crawling {source.competitor_name} "
                f"({source.source_type}): {source.url}"
            )
            status = await crawl_one(crawler, run_config, engine, source)
            counts[status] += 1
            print(f"  {status}")

    return counts


async def run(args: argparse.Namespace) -> dict[str, int]:
    engine = get_engine()
    with engine.connect() as connection:
        sources = fetch_source_urls(connection, args)

    if not sources:
        print("No active source URLs matched the requested filters.")
        return {"saved": 0, "failed": 0, "skipped_empty": 0, "skipped_duplicate": 0}

    print(f"Found {len(sources)} active source URL(s).")
    return await crawl_sources(engine, sources)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)

    try:
        counts = asyncio.run(run(args))
    except ImportError as exc:
        print("Crawl failed: Crawl4AI is not installed or cannot be imported.")
        print("  fix: install requirements and verify Crawl4AI browser/runtime setup.")
        print(f"  details: {exc}")
        raise SystemExit(1) from exc

    print(
        "Crawl summary: "
        f"saved={counts['saved']}, "
        f"failed={counts['failed']}, "
        f"skipped_empty={counts['skipped_empty']}, "
        f"skipped_duplicate={counts.get('skipped_duplicate', 0)}"
    )


if __name__ == "__main__":
    main()
