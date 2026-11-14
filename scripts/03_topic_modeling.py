"""Assign BERTopic topics to eligible crawled competitor pages."""

from __future__ import annotations

import argparse
import json
import math
import re
from collections.abc import Iterable
from dataclasses import dataclass
from numbers import Number
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml
from sqlalchemy import text

from db import get_engine


DEFAULT_MIN_WORDS = 150
MIN_DOCUMENTS = 5
UNKNOWN_CONTROLLED_TOPIC_ID = "unknown_other"
CONTROLLED_TOPIC_MIN_SEED_HITS = 2
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TOPIC_TAXONOMY_PATH = REPO_ROOT / "config" / "content_topics.yml"

PAGE_TYPE_STOPWORDS: frozenset[str] = frozenset({
    "homepage", "pricing", "blog", "docs", "product", "products",
    "case", "studies", "case studies", "reviews", "comparison",
    "newsroom", "faq", "documentation", "page", "content",
})

URL_STOPWORDS: frozenset[str] = frozenset({
    "www", "com", "org", "net", "io", "https", "http",
})

AUDITED_BRAND_ENTITY_TOPIC_TERMS: frozenset[str] = frozenset({
    "barry",
    "bounce",
    "demo aurora",
    "demo boreale",
    "factory",
    "macros",
    "queue",
    "track",
})


@dataclass(frozen=True)
class RawPage:
    id: int
    competitor_id: int
    url: str
    title: str | None
    word_count: int
    markdown: str
    source_type: str = "other"
    has_existing_topic: bool = False


@dataclass(frozen=True)
class TopicAssignment:
    raw_page_id: int
    competitor_id: int
    topic_id: int
    topic_label: str
    topic_probability: float | None
    funnel_stage: str = "unknown"


@dataclass(frozen=True)
class ControlledTopicAssignment:
    raw_page_id: int
    competitor_id: int
    topic_id: str
    topic_label: str
    topic_confidence: str
    assignment_reason: str
    matched_terms: tuple[str, ...] = ()
    funnel_stage: str = "unknown"


@dataclass(frozen=True)
class TopicSummary:
    eligible_documents: int
    inserted_documents: int
    skipped_documents: int
    refreshed_documents: int = 0


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def _extract_url_brand_tokens(url: str) -> set[str]:
    """Return brand tokens extracted from a competitor URL's hostname."""
    if not url:
        return set()
    try:
        hostname = (urlparse(url).hostname or "").lower()
    except Exception:
        return set()
    hostname = re.sub(r"^www\.", "", hostname)
    hostname_no_tld = re.sub(r"\.[a-z]{2,}$", "", hostname)
    parts = re.split(r"[.\-_]+", hostname_no_tld)
    tokens = {p for p in parts if len(p) > 1}
    tokens.add(hostname_no_tld)
    return tokens


def build_label_stopwords(
    competitor_names: Iterable[str] = (),
    competitor_urls: Iterable[str] = (),
) -> frozenset[str]:
    """Build the full label stopword set from constants plus live competitor data."""
    tokens: set[str] = set()
    tokens.update(PAGE_TYPE_STOPWORDS)
    tokens.update(URL_STOPWORDS)
    tokens.update(AUDITED_BRAND_ENTITY_TOPIC_TERMS)
    tokens.update({"pro", "tools", "pro tools", "avid"})
    for name in competitor_names:
        name_lower = name.lower().strip()
        tokens.add(name_lower)
        for part in re.split(r"[\W_]+", name_lower):
            if len(part) > 1:
                tokens.add(part)
    for url in competitor_urls:
        tokens.update(_extract_url_brand_tokens(url))
    return frozenset(t for t in tokens if t)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Fit BERTopic topics on eligible crawled pages. This works best after "
            "you have at least five substantial crawled documents."
        )
    )
    parser.add_argument(
        "--min-words",
        type=positive_int,
        default=DEFAULT_MIN_WORDS,
        help="Minimum raw page word_count required for topic modeling. Default: 150.",
    )
    parser.add_argument("--limit", type=positive_int, help="Maximum pages to model.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Refresh pages that already have topic_documents rows.",
    )
    return parser.parse_args(argv)


def load_topic_taxonomy(path: Path | None = None) -> list[dict[str, Any]]:
    """Load the controlled strategic topic taxonomy from YAML config."""
    taxonomy_path = path or DEFAULT_TOPIC_TAXONOMY_PATH
    with taxonomy_path.open("r", encoding="utf-8") as handle:
        raw_config = yaml.safe_load(handle) or {}

    topics = raw_config.get("topics") if isinstance(raw_config, dict) else raw_config
    if not isinstance(topics, list):
        raise ValueError("content topic taxonomy must be a list or contain a topics list")

    required_fields = {
        "id",
        "label",
        "description",
        "seed_terms",
        "positive_examples",
        "negative_examples",
    }
    normalized: list[dict[str, Any]] = []
    for topic in topics:
        if not isinstance(topic, dict):
            raise ValueError("each content topic must be a mapping")
        missing = sorted(field for field in required_fields if not topic.get(field))
        if missing:
            topic_id = topic.get("id") or "<unknown>"
            raise ValueError(f"content topic {topic_id} missing fields: {', '.join(missing)}")
        normalized_topic = dict(topic)
        for list_field in ["seed_terms", "positive_examples", "negative_examples"]:
            values = normalized_topic[list_field]
            if not isinstance(values, list) or not all(str(item).strip() for item in values):
                raise ValueError(f"{normalized_topic['id']} {list_field} must be a non-empty list")
            normalized_topic[list_field] = [str(item).strip() for item in values]
        normalized.append(normalized_topic)

    strategic_topic_count = sum(
        1 for topic in normalized if topic["id"] != UNKNOWN_CONTROLLED_TOPIC_ID
    )
    if strategic_topic_count > 5:
        raise ValueError("controlled topic taxonomy can contain at most 5 strategic topics")
    if UNKNOWN_CONTROLLED_TOPIC_ID not in {topic["id"] for topic in normalized}:
        raise ValueError("controlled topic taxonomy must include unknown_other")
    return normalized


def build_raw_page_query(args: argparse.Namespace) -> tuple[Any, dict[str, Any]]:
    conditions = [
        "cav.is_valid_content_asset = TRUE",
        "rp.success = TRUE",
        "rp.markdown IS NOT NULL",
        "btrim(rp.markdown) <> ''",
        "rp.word_count >= :min_words",
    ]
    params: dict[str, Any] = {"min_words": args.min_words}

    if not args.force:
        conditions.append(
            "NOT EXISTS ("
            "SELECT 1 FROM topic_documents td "
            "WHERE td.raw_page_id = rp.id"
            ")"
        )

    sql = f"""
        SELECT
            rp.id AS raw_page_id,
            rp.competitor_id,
            rp.url,
            rp.title,
            COALESCE(rp.asset_type, su.source_type, 'other') AS source_type,
            rp.word_count,
            rp.markdown,
            EXISTS (
                SELECT 1
                FROM topic_documents td
                WHERE td.raw_page_id = rp.id
            ) AS has_existing_topic
        FROM raw_pages rp
        JOIN v_content_asset_validity cav ON cav.raw_page_id = rp.id
        LEFT JOIN source_urls su ON su.id = rp.source_url_id
        WHERE {" AND ".join(conditions)}
        ORDER BY rp.fetched_at, rp.id
    """

    if args.limit:
        sql += "\n        LIMIT :limit"
        params["limit"] = args.limit

    return text(sql), params


def fetch_raw_pages(connection, args: argparse.Namespace) -> list[RawPage]:
    statement, params = build_raw_page_query(args)
    rows = connection.execute(statement, params)

    return [
        RawPage(
            id=row._mapping["raw_page_id"],
            competitor_id=row._mapping["competitor_id"],
            url=row._mapping["url"],
            title=row._mapping["title"],
            word_count=row._mapping["word_count"],
            markdown=row._mapping["markdown"],
            source_type=row._mapping.get("source_type", "other"),
            has_existing_topic=bool(row._mapping["has_existing_topic"]),
        )
        for row in rows
    ]


def fetch_competitor_info(connection) -> tuple[list[str], list[str]]:
    """Return (names, urls) for all competitors."""
    rows = connection.execute(
        text("SELECT name, COALESCE(website, '') AS website FROM competitors")
    )
    names: list[str] = []
    urls: list[str] = []
    for row in rows:
        names.append(row._mapping["name"])
        urls.append(row._mapping["website"])
    return names, urls


def create_topic_model(document_count: int):
    """Create BERTopic lazily so tests can import this module cheaply."""
    from bertopic import BERTopic
    from hdbscan import HDBSCAN
    from sklearn.feature_extraction.text import CountVectorizer
    from umap import UMAP

    n_neighbors = max(2, min(10, document_count - 1))
    n_components = max(2, min(5, document_count - 2))
    umap_model = UMAP(
        n_neighbors=n_neighbors,
        n_components=n_components,
        min_dist=0.0,
        metric="cosine",
        random_state=42,
    )
    hdbscan_model = HDBSCAN(
        min_cluster_size=2,
        min_samples=1,
        metric="euclidean",
        prediction_data=True,
    )
    vectorizer_model = CountVectorizer(
        stop_words="english",
        ngram_range=(1, 2),
        min_df=1,
    )
    return BERTopic(
        language="multilingual",
        calculate_probabilities=True,
        min_topic_size=2,
        umap_model=umap_model,
        hdbscan_model=hdbscan_model,
        vectorizer_model=vectorizer_model,
    )


def normalize_document_text(page: RawPage) -> str:
    title = f"{page.title}\n\n" if page.title else ""
    markdown = page.markdown
    markdown = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", markdown)
    markdown = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", markdown)
    markdown = re.sub(r"https?://\S+", " ", markdown)
    markdown = re.sub(
        r"We value your privacy.*?(Reject non\S*essential|Accept all)",
        " ",
        markdown,
        flags=re.IGNORECASE,
    )
    markdown = re.sub(r"\s+", " ", markdown)
    return f"{title}{markdown}".strip()


def normalize_match_text(value: str) -> str:
    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def term_matches(text: str, term: str) -> bool:
    normalized_term = normalize_match_text(term)
    if not normalized_term:
        return False
    return re.search(rf"(?<!\w){re.escape(normalized_term)}(?!\w)", text) is not None


def classify_controlled_topics(
    page: RawPage,
    taxonomy: list[dict[str, Any]],
) -> list[ControlledTopicAssignment]:
    """Assign controlled strategic topics from taxonomy-backed evidence."""
    text_value = normalize_match_text(normalize_document_text(page))
    assignments: list[ControlledTopicAssignment] = []
    unknown_topic = next(
        (topic for topic in taxonomy if topic["id"] == UNKNOWN_CONTROLLED_TOPIC_ID),
        {
            "id": UNKNOWN_CONTROLLED_TOPIC_ID,
            "label": "Unknown / Other",
        },
    )

    for topic in taxonomy:
        topic_id = str(topic["id"])
        if topic_id == UNKNOWN_CONTROLLED_TOPIC_ID:
            continue

        seed_terms = [str(term) for term in topic.get("seed_terms", [])]
        positive_examples = [str(example) for example in topic.get("positive_examples", [])]
        matched_terms = tuple(
            term for term in seed_terms if term_matches(text_value, term)
        )
        matched_examples = tuple(
            example
            for example in positive_examples
            if normalize_match_text(example) and normalize_match_text(example) in text_value
        )

        if len(set(matched_terms)) < CONTROLLED_TOPIC_MIN_SEED_HITS and not matched_examples:
            continue

        if matched_examples and len(set(matched_terms)) >= 2:
            confidence = "high"
        elif len(set(matched_terms)) >= 4:
            confidence = "high"
        else:
            confidence = "medium"

        evidence_parts: list[str] = []
        if matched_terms:
            evidence_parts.append("matched seed terms: " + ", ".join(matched_terms[:6]))
        if matched_examples:
            evidence_parts.append("matched positive example")

        assignments.append(
            ControlledTopicAssignment(
                raw_page_id=page.id,
                competitor_id=page.competitor_id,
                topic_id=topic_id,
                topic_label=str(topic["label"]),
                topic_confidence=confidence,
                assignment_reason="; ".join(evidence_parts),
                matched_terms=matched_terms,
                funnel_stage=infer_funnel_stage(page.source_type),
            )
        )

    if assignments:
        return assignments

    return [
        ControlledTopicAssignment(
            raw_page_id=page.id,
            competitor_id=page.competitor_id,
            topic_id=UNKNOWN_CONTROLLED_TOPIC_ID,
            topic_label=str(unknown_topic.get("label", "Unknown / Other")),
            topic_confidence="low",
            assignment_reason="insufficient evidence for controlled topic assignment",
            matched_terms=(),
            funnel_stage=infer_funnel_stage(page.source_type),
        )
    ]


def build_topic_label(
    topic_model,
    topic_id: int,
    page: RawPage | None = None,
    *,
    max_terms: int = 3,
    label_stopwords: frozenset[str] = frozenset(),
) -> str:
    if topic_id == -1:
        return "Outlier"

    terms = topic_model.get_topic(topic_id) or []
    seen: set[str] = set()
    label_terms: list[str] = []
    for term, _score in terms:
        t = str(term).strip().lower()
        if t and t not in label_stopwords and t not in seen:
            seen.add(t)
            label_terms.append(t)
        if len(label_terms) >= max_terms:
            break

    if page and len(label_terms) < 2:
        source_term = (page.source_type or "content").replace("_", " ").lower()
        raw_title_tokens = [
            tok.strip(" -|:").lower()
            for tok in re.split(r"[\s/|:,-]+", page.title or "")
            if len(tok.strip(" -|:")) > 3
        ]
        filtered_title = [t for t in raw_title_tokens if t not in label_stopwords][:2]
        fallback: list[str] = []
        fallback_seen: set[str] = set()
        if source_term and source_term not in label_stopwords:
            fallback.append(source_term)
            fallback_seen.add(source_term)
        for t in filtered_title:
            if t not in fallback_seen:
                fallback.append(t)
                fallback_seen.add(t)
        if len(fallback) > len(label_terms):
            label_terms = fallback[:max_terms]

    if not label_terms:
        return f"Topic {topic_id} [low confidence]"

    return " / ".join(label_terms)


def to_probability(value: Any) -> float | None:
    if value is None:
        return None

    if isinstance(value, Number):
        parsed = float(value)
        return parsed if math.isfinite(parsed) else None

    if hasattr(value, "tolist"):
        return to_probability(value.tolist())

    if isinstance(value, Iterable) and not isinstance(value, (str, bytes, dict)):
        parsed_values = [to_probability(item) for item in value]
        finite_values = [item for item in parsed_values if item is not None]
        return max(finite_values) if finite_values else None

    return None


def extract_topic_probability(
    probabilities: Any,
    document_index: int,
    topic_id: int,
) -> float | None:
    if probabilities is None:
        return None

    if isinstance(probabilities, Number):
        return to_probability(probabilities)

    if hasattr(probabilities, "tolist"):
        probabilities = probabilities.tolist()

    if isinstance(probabilities, Iterable) and not isinstance(
        probabilities, (str, bytes, dict)
    ):
        values = list(probabilities)
        if not values:
            return None

        if document_index < len(values):
            return to_probability(values[document_index])

    return None


def build_topic_assignments(
    pages: list[RawPage],
    topics: list[int],
    probabilities: Any,
    topic_model,
    label_stopwords: frozenset[str] = frozenset(),
) -> list[TopicAssignment]:
    assignments: list[TopicAssignment] = []
    for index, (page, topic_id) in enumerate(zip(pages, topics, strict=True)):
        assignments.append(
            TopicAssignment(
                raw_page_id=page.id,
                competitor_id=page.competitor_id,
                topic_id=int(topic_id),
                topic_label=build_topic_label(
                    topic_model,
                    int(topic_id),
                    page,
                    label_stopwords=label_stopwords,
                ),
                topic_probability=extract_topic_probability(
                    probabilities,
                    index,
                    int(topic_id),
                ),
                funnel_stage=infer_funnel_stage(page.source_type),
            )
        )

    return assignments


def infer_funnel_stage(source_type: str) -> str:
    return {
        "blog": "TOFU",
        "newsroom": "TOFU",
        "docs": "retention/support",
        "faq": "retention/support",
        "pricing": "BOFU",
        "case_studies": "BOFU",
        "comparison": "BOFU",
        "reviews": "BOFU",
        "product": "MOFU",
        "homepage": "MOFU",
    }.get(source_type, "unknown")


def fit_topics(
    pages: list[RawPage],
    label_stopwords: frozenset[str] = frozenset(),
) -> list[TopicAssignment]:
    documents = [normalize_document_text(page) for page in pages]
    topic_model = create_topic_model(len(documents))
    topics, probabilities = topic_model.fit_transform(documents)

    return build_topic_assignments(
        pages,
        [int(topic_id) for topic_id in topics],
        probabilities,
        topic_model,
        label_stopwords,
    )


def save_topic_documents(
    connection,
    assignments: list[TopicAssignment],
    *,
    force: bool = False,
) -> None:
    for assignment in assignments:
        if force:
            connection.execute(
                text("DELETE FROM topic_documents WHERE raw_page_id = :raw_page_id"),
                {"raw_page_id": assignment.raw_page_id},
            )

        params = {
            "raw_page_id": assignment.raw_page_id,
            "competitor_id": assignment.competitor_id,
            "topic_id": assignment.topic_id,
            "topic_label": assignment.topic_label,
            "topic_probability": assignment.topic_probability,
            "funnel_stage": assignment.funnel_stage,
        }
        connection.execute(
            text(
                """
                INSERT INTO topic_documents (
                    raw_page_id,
                    competitor_id,
                    topic_id,
                    topic_label,
                    topic_probability,
                    funnel_stage
                )
                VALUES (
                    :raw_page_id,
                    :competitor_id,
                    :topic_id,
                    :topic_label,
                    :topic_probability,
                    :funnel_stage
                )
                ON CONFLICT (raw_page_id) DO NOTHING
                """
            ),
            params,
        )


def save_controlled_topic_documents(
    connection,
    assignments: list[ControlledTopicAssignment],
    *,
    force: bool = False,
) -> None:
    deleted_raw_page_ids: set[int] = set()
    for assignment in assignments:
        if force and assignment.raw_page_id not in deleted_raw_page_ids:
            connection.execute(
                text(
                    "DELETE FROM controlled_topic_documents "
                    "WHERE raw_page_id = :raw_page_id"
                ),
                {"raw_page_id": assignment.raw_page_id},
            )
            deleted_raw_page_ids.add(assignment.raw_page_id)

        params = {
            "raw_page_id": assignment.raw_page_id,
            "competitor_id": assignment.competitor_id,
            "controlled_topic_id": assignment.topic_id,
            "controlled_topic_label": assignment.topic_label,
            "controlled_topic_confidence": assignment.topic_confidence,
            "controlled_topic_assignment_reason": assignment.assignment_reason,
            "matched_terms": json.dumps(list(assignment.matched_terms)),
            "funnel_stage": assignment.funnel_stage,
        }
        connection.execute(
            text(
                """
                INSERT INTO controlled_topic_documents (
                    raw_page_id,
                    competitor_id,
                    controlled_topic_id,
                    controlled_topic_label,
                    controlled_topic_confidence,
                    controlled_topic_assignment_reason,
                    matched_terms,
                    funnel_stage
                )
                VALUES (
                    :raw_page_id,
                    :competitor_id,
                    :controlled_topic_id,
                    :controlled_topic_label,
                    :controlled_topic_confidence,
                    :controlled_topic_assignment_reason,
                    CAST(:matched_terms AS jsonb),
                    :funnel_stage
                )
                ON CONFLICT (raw_page_id, controlled_topic_id) DO NOTHING
                """
            ),
            params,
        )


def run(args: argparse.Namespace) -> TopicSummary:
    engine = get_engine()

    with engine.connect() as connection:
        pages = fetch_raw_pages(connection, args)
        competitor_names, competitor_urls = fetch_competitor_info(connection)

    label_stopwords = build_label_stopwords(competitor_names, competitor_urls)

    if len(pages) < MIN_DOCUMENTS:
        print(
            "Topic modeling skipped: "
            f"found {len(pages)} eligible document(s), "
            f"but at least {MIN_DOCUMENTS} are required. Crawl more pages or "
            f"lower --min-words from {args.min_words} only for exploratory runs."
        )
        return TopicSummary(
            eligible_documents=len(pages),
            inserted_documents=0,
            skipped_documents=len(pages),
        )

    print(f"Found {len(pages)} eligible document(s). Fitting BERTopic model...")
    taxonomy = load_topic_taxonomy()
    assignments = fit_topics(pages, label_stopwords=label_stopwords)
    controlled_assignments = [
        assignment
        for page in pages
        for assignment in classify_controlled_topics(page, taxonomy)
    ]

    with engine.begin() as connection:
        save_topic_documents(connection, assignments, force=args.force)
        save_controlled_topic_documents(
            connection,
            controlled_assignments,
            force=args.force,
        )

    refreshed = sum(1 for page in pages if page.has_existing_topic) if args.force else 0
    inserted = len(assignments) - refreshed
    print(
        "Topic modeling stored: "
        f"inserted={inserted}, refreshed={refreshed}, total={len(assignments)}, "
        f"controlled_topic_assignments={len(controlled_assignments)}"
    )
    return TopicSummary(
        eligible_documents=len(pages),
        inserted_documents=inserted,
        skipped_documents=0,
        refreshed_documents=refreshed,
    )


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)

    try:
        summary = run(args)
    except ImportError as exc:
        print("Topic modeling failed: BERTopic or its dependencies are not installed.")
        print(f"  details: {exc}")
        raise SystemExit(1) from exc
    except RuntimeError as exc:
        print("Topic modeling failed:")
        print(f"  errors: {exc}")
        raise SystemExit(1) from exc

    print(
        "Topic modeling summary: "
        f"eligible={summary.eligible_documents}, "
        f"inserted={summary.inserted_documents}, "
        f"refreshed={summary.refreshed_documents}, "
        f"skipped={summary.skipped_documents}"
    )


if __name__ == "__main__":
    main()
