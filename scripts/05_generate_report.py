"""Generate a Markdown market intelligence report from PostgreSQL data."""

from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from sqlalchemy import text

from db import get_engine


DEFAULT_OUTPUT_DIR = Path("outputs/reports")
DEFAULT_MODEL = "gpt-4o-mini"
NOT_ENOUGH_DATA = "Not enough data is available for this section yet."
MOJIBAKE_MARKERS = ("\u00c3", "\u00c2", "\u00e2")
MAX_MOJIBAKE_REPAIR_PASSES = 3
PRESENTATION_TRANSLATION = str.maketrans(
    {
        "\u00a0": " ",
        "\u2010": "-",
        "\u2011": "-",
        "\u2012": "-",
        "\u2013": "-",
        "\u2014": "-",
        "\u2015": "-",
        "\u2212": "-",
        "\u2018": "'",
        "\u2019": "'",
        "\u201a": "'",
        "\u201b": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u201e": '"',
        "\u201f": '"',
    }
)
AUDITED_LOW_CONFIDENCE_TOPIC_LABELS = frozenset(
    {
        "bounce / factory / demo aurora",
        "queue / demo boreale / bounce",
        "track / macros / barry",
    }
)


@dataclass(frozen=True)
class KpiSelection:
    requested_date: date
    selected_date: date | None
    used_fallback: bool = False


@dataclass(frozen=True)
class ReportData:
    generated_date: date
    kpi_selection: KpiSelection
    dataset_scope: list[dict[str, Any]] = field(default_factory=list)
    source_type_coverage: list[dict[str, Any]] = field(default_factory=list)
    competitor_overview: list[dict[str, Any]] = field(default_factory=list)
    share_of_voice: list[dict[str, Any]] = field(default_factory=list)
    content_inventory: list[dict[str, Any]] = field(default_factory=list)
    asset_type_mix: list[dict[str, Any]] = field(default_factory=list)
    topic_coverage: list[dict[str, Any]] = field(default_factory=list)
    topic_gaps: list[dict[str, Any]] = field(default_factory=list)
    topic_diagnostics: list[dict[str, Any]] = field(default_factory=list)
    topic_gap_diagnostics: list[dict[str, Any]] = field(default_factory=list)
    messaging_matrix: list[dict[str, Any]] = field(default_factory=list)
    pain_point_evidence_mix: list[dict[str, Any]] = field(default_factory=list)
    proof_type_mix: list[dict[str, Any]] = field(default_factory=list)
    funnel_mix: list[dict[str, Any]] = field(default_factory=list)
    cta_coverage: list[dict[str, Any]] = field(default_factory=list)
    cta_type_mix: list[dict[str, Any]] = field(default_factory=list)
    content_quality: list[dict[str, Any]] = field(default_factory=list)
    competitor_scorecards: list[dict[str, Any]] = field(default_factory=list)
    opportunity_backlog: list[dict[str, Any]] = field(default_factory=list)
    data_quality_issues: list[dict[str, Any]] = field(default_factory=list)
    data_quality: dict[str, Any] = field(default_factory=dict)


def parse_report_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("date must use YYYY-MM-DD format") from exc


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Generate a Markdown market intelligence report from PostgreSQL data. "
            "The report uses local proxy metrics and does not perform web research."
        )
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory where the Markdown report should be written. Default: outputs/reports.",
    )
    parser.add_argument(
        "--use-llm-summary",
        action="store_true",
        help="Use OpenAI to polish the executive summary from database facts only.",
    )
    parser.add_argument(
        "--date",
        type=parse_report_date,
        default=date.today(),
        help="Report date in YYYY-MM-DD format. Defaults to today.",
    )
    return parser.parse_args(argv)


def clean_value(value: Any) -> str:
    if value is None:
        return ""
    text_value = normalize_report_text(repair_mojibake(str(value).strip()))
    if not text_value or text_value.lower() == "not_found":
        return ""
    return text_value


def repair_mojibake(value: str) -> str:
    """Repair common UTF-8 text that was decoded as Windows-1252."""
    if not value or not any(marker in value for marker in MOJIBAKE_MARKERS):
        return value

    repaired = value
    for _ in range(MAX_MOJIBAKE_REPAIR_PASSES):
        next_value = repair_mojibake_once(repaired)
        if next_value is None or next_value == repaired:
            break
        repaired = next_value
    return repaired


def repair_mojibake_once(value: str) -> str | None:
    encoded = encode_mojibake_as_cp1252_bytes(value)
    if encoded is None:
        return None

    try:
        repaired = encoded.decode("utf-8")
    except UnicodeError:
        return None

    if repaired.count("\ufffd") > value.count("\ufffd"):
        return None
    return repaired


def encode_mojibake_as_cp1252_bytes(value: str) -> bytes | None:
    encoded = bytearray()
    for character in value:
        codepoint = ord(character)
        if 0x80 <= codepoint <= 0x9F:
            encoded.append(codepoint)
            continue

        try:
            encoded.extend(character.encode("cp1252"))
        except UnicodeEncodeError:
            return None
    return bytes(encoded)


def normalize_report_text(value: str) -> str:
    """Normalize rendered report text without changing stored database values."""
    if not value:
        return value
    return value.translate(PRESENTATION_TRANSLATION)


def topic_label_confidence(value: Any) -> str:
    label = clean_value(value).lower()
    if not label:
        return "low"
    if "[low confidence]" in label:
        return "low"
    if label in AUDITED_LOW_CONFIDENCE_TOPIC_LABELS:
        return "low"
    return "normal"


def format_topic_label(value: Any) -> str:
    label = clean_value(value)
    if not label:
        return NOT_ENOUGH_DATA
    if topic_label_confidence(label) == "low" and "[low confidence]" not in label.lower():
        return f"{label} [low confidence]"
    return label


def is_present(value: Any) -> bool:
    return bool(clean_value(value))


def normalize_json_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            parsed = [value]
    else:
        parsed = value

    if not isinstance(parsed, list):
        return []

    return [clean_value(extract_json_display_value(item)) for item in parsed if is_present(extract_json_display_value(item))]


def extract_json_display_value(value: Any) -> Any:
    if not isinstance(value, dict):
        return value

    for key in [
        "pain_point_text",
        "text",
        "source_text",
        "proof_text",
        "claim",
    ]:
        if is_present(value.get(key)):
            return value.get(key)

    return value


def has_source_urls(value: Any) -> bool:
    return bool(normalize_json_list(value))


def is_valid_report_asset(row: dict[str, Any]) -> bool:
    """Defensively ignore stale strategic rows already flagged as invalid."""
    if row.get("is_valid_content_asset") is False:
        return False
    if clean_value(row.get("asset_validity_status")).lower() == "invalid":
        return False
    return True


def is_external_competitor_row(row: dict[str, Any]) -> bool:
    """Return True for competitor rows that are not the configured owned domain."""
    return row.get("is_owned_domain") is not True


def is_strategic_topic_row(row: dict[str, Any]) -> bool:
    """Return True only for topic rows that are safe to promote from diagnostics."""
    if clean_value(row.get("recommended_action_type")) != "fill_owned_topic_gap":
        return True
    if topic_label_confidence(row.get("related_topic")) != "normal":
        return False
    if clean_value(row.get("topic_saturation")).lower() in {"low", "insufficient data"}:
        return False
    return True


def fetch_all(connection, statement: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    rows = connection.execute(text(statement), params or {})
    return [dict(row._mapping) for row in rows]


def fetch_one_value(connection, statement: str, params: dict[str, Any] | None = None) -> Any:
    return connection.execute(text(statement), params or {}).scalar_one_or_none()


def fetch_kpi_selection(connection, requested_date: date) -> KpiSelection:
    exact_date = fetch_one_value(
        connection,
        """
        SELECT date
        FROM kpi_competitor_daily
        WHERE date = :requested_date
        LIMIT 1
        """,
        {"requested_date": requested_date},
    )
    if exact_date:
        return KpiSelection(requested_date=requested_date, selected_date=exact_date)

    latest_date = fetch_one_value(
        connection,
        "SELECT MAX(date) FROM kpi_competitor_daily",
    )
    return KpiSelection(
        requested_date=requested_date,
        selected_date=latest_date,
        used_fallback=latest_date is not None,
    )


def fetch_report_data(connection, generated_date: date) -> ReportData:
    kpi_selection = fetch_kpi_selection(connection, generated_date)

    dataset_scope = fetch_all(
        connection,
        """
        WITH source_counts AS (
            SELECT
                competitor_id,
                COUNT(*) AS configured_urls
            FROM source_urls
            GROUP BY competitor_id
        ),
        raw_counts AS (
            SELECT
                competitor_id,
                COUNT(*) AS pages_crawled,
                COUNT(*) FILTER (WHERE success = TRUE) AS crawled_ok
            FROM raw_pages
            GROUP BY competitor_id
        ),
        validity_counts AS (
            SELECT
                competitor_id,
                COUNT(*) FILTER (WHERE is_valid_content_asset = TRUE) AS valid_assets,
                COUNT(*) FILTER (WHERE is_valid_content_asset = FALSE) AS invalid_or_non_evaluable
            FROM v_content_asset_validity
            GROUP BY competitor_id
        ),
        insight_counts AS (
            SELECT
                pi.competitor_id,
                COUNT(*) AS insights_extracted,
                COUNT(*) FILTER (WHERE cav.is_valid_content_asset = TRUE) AS valid_insights,
                COUNT(*) FILTER (WHERE cav.is_valid_content_asset = FALSE) AS invalid_insights
            FROM page_insights pi
            LEFT JOIN v_content_asset_validity cav ON cav.raw_page_id = pi.raw_page_id
            GROUP BY pi.competitor_id
        )
        SELECT
            c.name AS competitor,
            c.website,
            COALESCE(c.category, '') AS category,
            COALESCE(c.country, '') AS country,
            c.is_owned_domain,
            COALESCE(sc.configured_urls, 0) AS configured_urls,
            COALESCE(rc.pages_crawled, 0) AS pages_crawled,
            COALESCE(rc.crawled_ok, 0) AS crawled_ok,
            COALESCE(vc.valid_assets, 0) AS valid_assets,
            COALESCE(vc.invalid_or_non_evaluable, 0) AS invalid_or_non_evaluable,
            COALESCE(ic.insights_extracted, 0) AS insights_extracted,
            COALESCE(ic.valid_insights, 0) AS valid_insights,
            COALESCE(ic.invalid_insights, 0) AS invalid_insights
        FROM competitors c
        LEFT JOIN source_counts sc ON sc.competitor_id = c.id
        LEFT JOIN raw_counts rc ON rc.competitor_id = c.id
        LEFT JOIN validity_counts vc ON vc.competitor_id = c.id
        LEFT JOIN insight_counts ic ON ic.competitor_id = c.id
        ORDER BY c.name
        """,
    )

    source_type_coverage = fetch_all(
        connection,
        """
        SELECT
            COALESCE(su.source_type, cav.source_type, pi.source_type, 'not_found') AS source_type,
            COUNT(DISTINCT rp.id) AS pages_crawled,
            COUNT(DISTINCT rp.id) FILTER (WHERE rp.success = TRUE) AS crawled_ok,
            COUNT(DISTINCT cav.raw_page_id) FILTER (
                WHERE cav.is_valid_content_asset = TRUE
            ) AS valid_assets,
            COUNT(DISTINCT cav.raw_page_id) FILTER (
                WHERE cav.is_valid_content_asset = FALSE
            ) AS invalid_or_non_evaluable,
            COUNT(DISTINCT pi.id) AS insights_extracted,
            COUNT(DISTINCT pi.id) FILTER (
                WHERE cav.is_valid_content_asset = TRUE
            ) AS valid_insights,
            COUNT(DISTINCT pi.id) FILTER (
                WHERE cav.is_valid_content_asset = FALSE
            ) AS invalid_insights
        FROM raw_pages rp
        LEFT JOIN source_urls su ON su.id = rp.source_url_id
        LEFT JOIN v_content_asset_validity cav ON cav.raw_page_id = rp.id
        LEFT JOIN page_insights pi ON pi.raw_page_id = rp.id
        GROUP BY COALESCE(su.source_type, cav.source_type, pi.source_type, 'not_found')
        ORDER BY pages_crawled DESC, source_type
        """,
    )

    kpi_date_join = (
        "AND k.date = :kpi_date" if kpi_selection.selected_date else "AND 1 = 0"
    )
    kpi_params = {"kpi_date": kpi_selection.selected_date}
    competitor_overview = fetch_all(
        connection,
        f"""
        SELECT
            c.name AS competitor,
            COALESCE(k.pages_analyzed, 0) AS pages_analyzed,
            COALESCE(k.total_words, 0) AS total_words,
            COALESCE(k.share_of_voice, 0) AS share_of_voice,
            COALESCE(sov.valid_assets, 0) AS valid_assets,
            COALESCE(sov.valid_asset_words, 0) AS valid_asset_words,
            COALESCE(k.sentiment_positive_share, 0) AS sentiment_positive_share,
            COALESCE(k.sentiment_negative_share, 0) AS sentiment_negative_share,
            COALESCE(k.pricing_mentions, 0) AS pricing_mentions,
            COALESCE(k.feature_mentions, 0) AS feature_mentions
        FROM competitors c
        LEFT JOIN kpi_competitor_daily k
            ON k.competitor_id = c.id
           {kpi_date_join}
        LEFT JOIN v_competitor_share_of_voice sov
            ON sov.competitor_id = c.id
        ORDER BY COALESCE(k.share_of_voice, 0) DESC, c.name
        """,
        kpi_params,
    )

    share_of_voice = fetch_all(
        connection,
        f"""
        SELECT
            c.name AS competitor,
            COALESCE(k.pages_analyzed, 0) AS pages_analyzed,
            COALESCE(k.total_words, 0) AS total_words,
            COALESCE(k.share_of_voice, 0) AS share_of_voice,
            COALESCE(sov.valid_assets, 0) AS valid_assets,
            COALESCE(sov.valid_asset_words, 0) AS valid_asset_words
        FROM competitors c
        LEFT JOIN kpi_competitor_daily k
            ON k.competitor_id = c.id
           {kpi_date_join}
        LEFT JOIN v_competitor_share_of_voice sov
            ON sov.competitor_id = c.id
        ORDER BY COALESCE(k.share_of_voice, 0) DESC, c.name
        """,
        kpi_params,
    )

    content_inventory = fetch_all(
        connection,
        """
        SELECT
            competitor_name,
            url,
            asset_type,
            title,
            word_count,
            freshness_bucket,
            content_depth_score,
            metadata_completeness_score
        FROM v_content_inventory
        ORDER BY competitor_name, asset_type, word_count DESC
        LIMIT 50
        """,
    )

    asset_type_mix = fetch_all(
        connection,
        """
        SELECT
            competitor_name,
            asset_type,
            assets_of_type,
            total_assets,
            asset_type_share
        FROM v_asset_type_mix
        ORDER BY competitor_name, assets_of_type DESC, asset_type
        """,
    )

    topic_coverage = fetch_all(
        connection,
        """
        SELECT
            competitor_name,
            controlled_topic_id,
            controlled_topic_label,
            controlled_topic_confidence,
            controlled_topic_assignment_reason,
            document_count,
            total_assets_on_topic,
            controlled_topic_share,
            topic_saturation,
            label_confidence,
            funnel_stage,
            source_urls
        FROM v_controlled_topic_coverage
        ORDER BY
            CASE WHEN controlled_topic_id = 'unknown_other' THEN 2 ELSE 1 END,
            document_count DESC,
            competitor_name,
            controlled_topic_label
        LIMIT 30
        """,
    )

    topic_diagnostics = fetch_all(
        connection,
        """
        SELECT
            competitor_name,
            topic_label,
            document_count,
            avg_probability,
            funnel_stage,
            source_urls
        FROM v_topic_coverage
        ORDER BY document_count DESC, competitor_name, topic_label
        LIMIT 30
        """,
    )

    topic_gaps = fetch_all(
        connection,
        """
        SELECT
            controlled_topic_id,
            controlled_topic_label,
            controlled_topic_confidence,
            topic_saturation,
            competitor_assets_on_topic,
            owned_assets_on_topic,
            is_gap_vs_own_site,
            gap_reason,
            gap_analysis_status,
            gap_analysis_reason
        FROM v_controlled_topic_gap
        WHERE gap_reason = 'missing_on_owned_site'
        ORDER BY
            CASE gap_reason
                WHEN 'missing_on_owned_site' THEN 1
                ELSE 3
            END,
            competitor_assets_on_topic DESC,
            controlled_topic_label
        LIMIT 20
        """,
    )

    topic_gap_diagnostics = fetch_all(
        connection,
        """
        SELECT
            topic_label,
            topic_saturation,
            competitor_assets_on_topic,
            is_gap_vs_own_site,
            gap_reason,
            gap_analysis_status,
            gap_analysis_reason
        FROM v_topic_gap
        WHERE gap_reason = 'missing_on_owned_site'
        ORDER BY competitor_assets_on_topic DESC, topic_label
        LIMIT 20
        """,
    )

    messaging_matrix = fetch_all(
        connection,
        """
        SELECT
            competitor_name,
            insight_pages,
            messaging_pillars,
            value_proposition_themes,
            pain_points,
            pain_point_details,
            proof_elements,
            differentiation_score,
            benefit_vs_feature_ratio,
            example_tone_label
        FROM v_messaging_matrix
        ORDER BY insight_pages DESC, competitor_name
        """,
    )

    pain_point_evidence_mix = fetch_all(
        connection,
        """
        SELECT
            competitor_name,
            pain_point_category,
            pain_point_evidence_type,
            pain_point_count,
            pain_points,
            source_urls
        FROM v_pain_point_evidence_mix_by_competitor
        WHERE pain_point_count > 0
        ORDER BY competitor_name, pain_point_category, pain_point_evidence_type
        """,
    )

    proof_type_mix = fetch_all(
        connection,
        """
        SELECT
            competitor_name,
            extracted_proof_type,
            normalized_proof_type,
            extracted_proof_strength,
            normalized_proof_strength,
            proof_normalization_reason,
            proof_elements_count,
            proof_type_share
        FROM v_proof_type_mix_by_competitor
        WHERE proof_elements_count > 0
        ORDER BY
            competitor_name,
            CASE normalized_proof_strength
                WHEN 'high' THEN 1
                WHEN 'medium' THEN 2
                WHEN 'low' THEN 3
                ELSE 4
            END,
            proof_elements_count DESC,
            normalized_proof_type,
            extracted_proof_type
        """,
    )

    funnel_mix = fetch_all(
        connection,
        """
        SELECT
            competitor_name,
            funnel_stage,
            assets_in_stage,
            total_assets,
            funnel_stage_share
        FROM v_funnel_mix
        ORDER BY competitor_name, funnel_stage
        """,
    )

    cta_coverage = fetch_all(
        connection,
        """
        SELECT
            competitor_name,
            total_insight_pages,
            pages_with_any_cta,
            any_cta_coverage,
            pages_with_conversion_cta,
            conversion_cta_coverage,
            pages_with_secondary_cta,
            secondary_cta_coverage,
            sample_confidence
        FROM v_cta_coverage_by_competitor
        ORDER BY conversion_cta_coverage DESC, any_cta_coverage DESC, competitor_name
        """,
    )

    cta_type_mix = fetch_all(
        connection,
        """
        SELECT
            competitor_name,
            cta_type,
            cta_type_count,
            cta_type_share
        FROM v_cta_type_mix_by_competitor
        ORDER BY competitor_name, cta_type_count DESC, cta_type
        """,
    )

    content_quality = fetch_all(
        connection,
        """
        SELECT
            competitor_name,
            is_owned_domain,
            url,
            title,
            asset_type,
            depth_score,
            proof_score,
            freshness_score,
            freshness_confidence,
            structure_score,
            clarity_score,
            cta_alignment_score,
            content_quality_score,
            quality_score,
            score_confidence,
            quality_confidence,
            quality_bucket,
            quality_evidence_strength,
            quality_reason,
            quality_warnings
        FROM v_content_quality
        ORDER BY content_quality_score DESC, competitor_name
        LIMIT 50
        """,
    )

    competitor_scorecards = fetch_all(
        connection,
        """
        SELECT
            competitor_name,
            valid_assets,
            insight_pages,
            insight_coverage,
            avg_content_quality_score,
            avg_content_depth_score,
            avg_metadata_completeness_score,
            avg_bofu_strength_score,
            high_asset_score_confidence_assets,
            medium_asset_score_confidence_assets,
            low_asset_score_confidence_assets,
            proof_elements_count,
            strong_proof_elements_count,
            weighted_proof_points,
            proof_elements_per_valid_asset,
            strong_proof_elements_per_valid_asset,
            weighted_proof_points_per_valid_asset,
            weighted_proof_points_validation_status,
            weighted_proof_points_validation_reason,
            weighted_proof_points_max_plausible,
            score_confidence,
            confidence_reason
        FROM v_competitor_scorecards
        ORDER BY
            CASE score_confidence
                WHEN 'high' THEN 1
                WHEN 'medium' THEN 2
                ELSE 3
            END,
            avg_content_quality_score DESC,
            valid_assets DESC,
            competitor_name
        """,
    )

    opportunity_backlog = fetch_all(
        connection,
        """
        SELECT
            priority,
            related_topic,
            gap_reason,
            competitor_evidence,
            suggested_asset_type,
            suggested_funnel_stage,
            suggested_cta,
            source_urls,
            evidence_strength,
            evidence_mix,
            weighted_evidence_score,
            dominant_evidence_type,
            fallback_share,
            source_count,
            confidence,
            why_now,
            blocked_by,
            competitor_prevalence,
            funnel_importance,
            owned_gap_status,
            gap_analysis_status,
            gap_analysis_reason,
            sample_confidence,
            recommended_action_type
        FROM v_opportunity_backlog
        ORDER BY
            CASE priority
                WHEN 'high' THEN 1
                WHEN 'medium' THEN 2
                WHEN 'low' THEN 3
                ELSE 4
            END,
            related_topic
        LIMIT 10
        """,
    )

    data_quality_issues = fetch_all(
        connection,
        """
        SELECT
            competitor_name,
            source_type,
            url,
            title,
            word_count,
            has_insight,
            asset_validity_status,
            validity_reason,
            recommended_action
        FROM v_data_quality_issues
        ORDER BY competitor_name, url
        LIMIT 50
        """,
    )

    data_quality = {
        "competitors": fetch_one_value(connection, "SELECT COUNT(*) FROM competitors") or 0,
        "owned_domain_configured": bool(
            fetch_one_value(
                connection,
                "SELECT EXISTS (SELECT 1 FROM competitors WHERE is_owned_domain = TRUE)",
            )
        ),
        "raw_pages": fetch_one_value(connection, "SELECT COUNT(*) FROM raw_pages") or 0,
        "crawled_ok_pages": fetch_one_value(
            connection, "SELECT COUNT(*) FROM raw_pages WHERE success = TRUE"
        )
        or 0,
        "failed_pages": fetch_one_value(
            connection, "SELECT COUNT(*) FROM raw_pages WHERE success = FALSE"
        )
        or 0,
        "insights": fetch_one_value(connection, "SELECT COUNT(*) FROM page_insights") or 0,
        "valid_insights": fetch_one_value(
            connection,
            """
            SELECT COUNT(*)
            FROM page_insights pi
            JOIN v_content_asset_validity cav ON cav.raw_page_id = pi.raw_page_id
            WHERE cav.is_valid_content_asset = TRUE
            """,
        )
        or 0,
        "invalid_insights": fetch_one_value(
            connection,
            """
            SELECT COUNT(*)
            FROM page_insights pi
            JOIN v_content_asset_validity cav ON cav.raw_page_id = pi.raw_page_id
            WHERE cav.is_valid_content_asset = FALSE
            """,
        )
        or 0,
        "topics": fetch_one_value(connection, "SELECT COUNT(*) FROM topic_documents") or 0,
        "controlled_topics": fetch_one_value(
            connection, "SELECT COUNT(*) FROM controlled_topic_documents"
        )
        or 0,
        "kpi_rows": fetch_one_value(connection, "SELECT COUNT(*) FROM kpi_competitor_daily")
        or 0,
    }

    return ReportData(
        generated_date=generated_date,
        kpi_selection=kpi_selection,
        dataset_scope=dataset_scope,
        source_type_coverage=source_type_coverage,
        competitor_overview=competitor_overview,
        share_of_voice=share_of_voice,
        content_inventory=content_inventory,
        asset_type_mix=asset_type_mix,
        topic_coverage=topic_coverage,
        topic_gaps=topic_gaps,
        topic_diagnostics=topic_diagnostics,
        topic_gap_diagnostics=topic_gap_diagnostics,
        messaging_matrix=messaging_matrix,
        pain_point_evidence_mix=pain_point_evidence_mix,
        proof_type_mix=proof_type_mix,
        funnel_mix=funnel_mix,
        cta_coverage=cta_coverage,
        cta_type_mix=cta_type_mix,
        content_quality=content_quality,
        competitor_scorecards=competitor_scorecards,
        opportunity_backlog=opportunity_backlog,
        data_quality_issues=data_quality_issues,
        data_quality=data_quality,
    )


def format_percent(value: Any) -> str:
    try:
        return f"{float(value) * 100:.1f}%"
    except (TypeError, ValueError):
        return "0.0%"


def format_int(value: Any) -> str:
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return "0"


def truncate_text(value: Any, max_length: int = 180) -> str:
    text_value = clean_value(value)
    if len(text_value) <= max_length:
        return text_value
    return text_value[: max_length - 1].rstrip() + "..."


def format_json_list(value: Any, max_items: int = 5) -> str:
    items = normalize_json_list(value)
    if not items:
        return ""
    return ", ".join(items[:max_items])


def format_data_quality_issue(value: Any) -> str:
    issue = clean_value(value).lower()
    return {
        "crawl_failed": "crawl failed",
        "empty_markdown": "empty or incomplete crawl",
        "low_word_count": "too little crawled content",
        "missing_insight": "missing extracted insight",
        "template_or_placeholder": "template or placeholder page",
    }.get(issue, issue.replace("_", " ") if issue else "crawl/input quality issue")


def format_data_quality_action(value: Any) -> str:
    action = clean_value(value).lower()
    return {
        "refresh_crawl": "recrawl or replace URL",
        "review_crawl_output": "recrawl or replace URL",
        "review_page_or_crawl": "review page selection",
        "rerun_extraction_or_review_page": "rerun extraction or review page",
        "review_url_or_rendering": "recrawl or replace URL",
        "review": "review page selection",
    }.get(action, action.replace("_", " ") if action else "review page selection")


def format_score(value: Any) -> str:
    try:
        return f"{float(value):.1f}"
    except (TypeError, ValueError):
        return "0.0"


def is_unavailable_confidence(value: Any) -> bool:
    return confidence_label(value) == "unavailable"


def format_metric_by_confidence(value: Any, confidence: Any) -> str:
    if is_unavailable_confidence(confidence):
        return "N/A"
    return format_score(value)


def sanitize_market_language(value: Any) -> str:
    """Soften unsupported market claims in rendered report evidence."""
    text_value = clean_value(value)
    if not text_value:
        return ""

    sanitized = re.sub(
        r"\b([A-Z][A-Za-z0-9& .'-]{1,80}?)\s+has\s+[\d.]+%?\s+market share\b",
        r"\1 has the largest crawled word share in the selected URL dataset",
        text_value,
        flags=re.IGNORECASE,
    )
    sanitized = re.sub(
        r"\b[\d.]+%?\s+market share\b",
        "the largest crawled word share in the selected URL dataset",
        sanitized,
        flags=re.IGNORECASE,
    )
    sanitized = re.sub(
        r"\b([A-Z][A-Za-z0-9& .'-]{1,80}?)\s+is\s+the\s+market leader\b",
        r"\1 appears most visible in this dataset",
        sanitized,
        flags=re.IGNORECASE,
    )
    sanitized = re.sub(
        r"\bthe\s+market leader\b",
        "most visible in this dataset",
        sanitized,
        flags=re.IGNORECASE,
    )
    sanitized = re.sub(
        r"\bpositions itself as a leader\b",
        "positions itself as highly visible in the crawled dataset",
        sanitized,
        flags=re.IGNORECASE,
    )
    sanitized = re.sub(
        r"\bpositioned as a leading\b",
        "positioned as a visible",
        sanitized,
        flags=re.IGNORECASE,
    )
    sanitized = re.sub(
        r"\b(?:the\s+)?market is growing at\b[^.]*\.?",
        "growth rate was not measured in this MVP.",
        sanitized,
        flags=re.IGNORECASE,
    )
    sanitized = re.sub(
        r"\bgrowth rate\b[^.]*\.?",
        "growth rate was not measured in this MVP.",
        sanitized,
        flags=re.IGNORECASE,
    )
    return sanitized


def sanitize_llm_executive_summary(value: Any, data: ReportData | None = None) -> str:
    """Remove risky LLM phrasing from the optional executive summary."""
    sanitized = sanitize_market_language(value)
    if not sanitized:
        return ""

    sanitized = re.sub(
        r"\bshare of voice\b",
        "crawled word share proxy",
        sanitized,
        flags=re.IGNORECASE,
    )
    sanitized = re.sub(r"\bBounFactory\b", "demo-aurora", sanitized)
    sanitized = re.sub(
        r"\bmarket presence\b|\bpresence in the market\b",
        "content presence in the selected URL dataset",
        sanitized,
        flags=re.IGNORECASE,
    )
    sanitized = re.sub(
        r"\bdominates\s+the\s+crawled\s+word\s+share\s+proxy\b",
        "has the largest crawled word share proxy in the selected URL dataset",
        sanitized,
        flags=re.IGNORECASE,
    )
    sanitized = re.sub(
        r"\ball crawled pages validated successfully\b",
        "All configured pages crawled successfully, while invalid or non-evaluable pages are listed as data quality issues",
        sanitized,
        flags=re.IGNORECASE,
    )
    sanitized = re.sub(
        r"\bdataset(?:'s)?\s+integrity\s+is\s+affirmed\b",
        "dataset reliability is summarized in the data quality sections",
        sanitized,
        flags=re.IGNORECASE,
    )
    sanitized = re.sub(
        r"\bcontent engagement\b",
        "crawled content volume",
        sanitized,
        flags=re.IGNORECASE,
    )
    sanitized = re.sub(
        r"\bcompetitive standing\b",
        "content planning",
        sanitized,
        flags=re.IGNORECASE,
    )
    if data is not None:
        raw_pages = format_int(data.data_quality.get("raw_pages"))
        insights = format_int(data.data_quality.get("insights"))
        sanitized = re.sub(
            r"\binsights extracted from a total of\s+\d+\s+raw pages\b",
            f"{insights} extracted insight records from {raw_pages} raw pages",
            sanitized,
            flags=re.IGNORECASE,
        )
    return sanitized


def escape_markdown_cell(value: Any) -> str:
    text_value = clean_value(value) or "not enough data"
    return (
        text_value.replace("\\", "\\\\")
        .replace("|", "\\|")
        .replace("\r", " ")
        .replace("\n", " ")
    )


def render_markdown_table(headers: list[str], rows: list[list[Any]]) -> str:
    if not rows:
        return render_not_enough_data()

    header_line = "| " + " | ".join(escape_markdown_cell(header) for header in headers) + " |"
    separator = "| " + " | ".join("---" for _ in headers) + " |"
    body = [
        "| " + " | ".join(escape_markdown_cell(cell) for cell in row) + " |"
        for row in rows
    ]
    return "\n".join([header_line, separator, *body])


def render_not_enough_data(detail: str | None = None) -> str:
    if detail:
        return f"{NOT_ENOUGH_DATA} {detail}"
    return NOT_ENOUGH_DATA


def confidence_label(value: Any) -> str:
    return clean_value(value).lower()


def is_low_confidence(value: Any) -> bool:
    return confidence_label(value) == "low"


def is_directional_status(value: Any) -> bool:
    return confidence_label(value) in {"directional_only", "directional only"}


def is_not_evaluated_status(value: Any) -> bool:
    return confidence_label(value) in {
        "not_evaluated_without_owned_gap",
        "not evaluated without owned gap",
        "not_evaluated",
        "not evaluated",
    }


def is_meaningful_blocker(value: Any) -> bool:
    label = confidence_label(value)
    return bool(label) and label not in {"none", "not enough data"}


def format_section_status(status: str, reason: str | None = None) -> str:
    cleaned_reason = clean_value(reason)
    if cleaned_reason:
        return f"Section status: {status}\nReason: {cleaned_reason}"
    return f"Section status: {status}"


def first_clean_reason(*values: Any, default: str) -> str:
    for value in values:
        cleaned = clean_value(value)
        if cleaned and cleaned.lower() not in {"none", "not enough data"}:
            return cleaned
    return default


def format_sample_confidence(value: Any) -> str:
    label = clean_value(value)
    if is_low_confidence(label):
        return "low / directional only"
    return label or NOT_ENOUGH_DATA


def format_asset_score_confidence(value: Any) -> str:
    label = clean_value(value)
    if is_low_confidence(label):
        return "low confidence"
    return label or NOT_ENOUGH_DATA


def format_gap_status(value: Any) -> str:
    label = clean_value(value)
    if is_directional_status(label):
        return "directional only"
    return label or NOT_ENOUGH_DATA


def report_competitor_scorecard_by_name(data: ReportData) -> dict[str, dict[str, Any]]:
    return {
        clean_value(row.get("competitor_name")).lower(): row
        for row in data.competitor_scorecards
        if clean_value(row.get("competitor_name"))
    }


def cap_directional_opportunity_value(row: dict[str, Any], field_name: str) -> str:
    value = clean_value(row.get(field_name))
    if is_directional_status(row.get("gap_analysis_status")) and value == "high":
        return "medium"
    return value or NOT_ENOUGH_DATA


def opportunity_row_is_relevant(row: dict[str, Any]) -> bool:
    return (
        clean_value(row.get("gap_reason")) != "not_configured"
        and is_valid_report_asset(row)
        and is_strategic_topic_row(row)
    )


def opportunity_row_is_renderable(row: dict[str, Any]) -> bool:
    return (
        opportunity_row_is_relevant(row)
        and clean_value(row.get("priority")) != "not_evaluable"
        and has_source_urls(row.get("source_urls"))
    )


def opportunity_row_directional_reason(row: dict[str, Any]) -> str | None:
    if is_not_evaluated_status(row.get("owned_gap_status")):
        return first_clean_reason(
            row.get("gap_analysis_reason"),
            default="owned-domain gap is not evaluated for at least one opportunity row",
        )
    if is_not_evaluated_status(row.get("gap_analysis_status")):
        return first_clean_reason(
            row.get("gap_analysis_reason"),
            default="gap analysis is not evaluated for at least one opportunity row",
        )
    if is_directional_status(row.get("owned_gap_status")) or is_directional_status(
        row.get("gap_analysis_status")
    ):
        return first_clean_reason(
            row.get("gap_analysis_reason"),
            row.get("blocked_by"),
            default="at least one opportunity row is directional only",
        )
    if is_low_confidence(row.get("sample_confidence")):
        return first_clean_reason(
            row.get("blocked_by"),
            row.get("gap_analysis_reason"),
            default="sample confidence is low for at least one opportunity row",
        )
    if is_low_confidence(row.get("confidence")):
        return first_clean_reason(
            row.get("blocked_by"),
            row.get("gap_analysis_reason"),
            default="confidence is low for at least one opportunity row",
        )
    if is_meaningful_blocker(row.get("blocked_by")):
        return clean_value(row.get("blocked_by"))
    return None


def derive_opportunity_section_status(rows: list[dict[str, Any]]) -> tuple[str, str]:
    relevant_rows = [row for row in rows if opportunity_row_is_relevant(row)]
    renderable_rows = [row for row in relevant_rows if opportunity_row_is_renderable(row)]
    if not renderable_rows:
        reason_row = relevant_rows[0] if relevant_rows else {}
        return (
            "not evaluable",
            first_clean_reason(
                reason_row.get("gap_analysis_reason"),
                reason_row.get("blocked_by"),
                default="not enough data: no relevant opportunity row has usable source evidence",
            ),
        )

    for row in renderable_rows:
        reason = opportunity_row_directional_reason(row)
        if reason:
            return "directional only", reason

    return (
        "fully comparable",
        "all rendered opportunity rows have evaluated gaps, usable confidence, "
        "source evidence, and no comparability blockers",
    )


def topic_gap_row_directional_reason(row: dict[str, Any]) -> str | None:
    if is_not_evaluated_status(row.get("gap_analysis_status")):
        return first_clean_reason(
            row.get("gap_analysis_reason"),
            default="gap analysis is not evaluated for at least one topic row",
        )
    if is_directional_status(row.get("gap_analysis_status")):
        return first_clean_reason(
            row.get("gap_analysis_reason"),
            default="at least one topic gap row is directional only",
        )
    if is_low_confidence(row.get("controlled_topic_confidence")):
        return first_clean_reason(
            row.get("gap_analysis_reason"),
            default="controlled topic confidence is low for at least one gap row",
        )
    return None


def derive_topic_gap_section_status(
    rows: list[dict[str, Any]], owned_low_sample_reason: str | None
) -> tuple[str, str]:
    usable_rows = [
        row
        for row in rows
        if clean_value(row.get("gap_reason")) != "not_configured"
        and is_valid_report_asset(row)
    ]
    if not usable_rows:
        if owned_low_sample_reason and "0 valid assets" not in owned_low_sample_reason:
            return "directional only", owned_low_sample_reason
        return "not evaluable", "not enough data: no controlled topic gap row is available"

    for row in usable_rows:
        reason = topic_gap_row_directional_reason(row)
        if reason:
            return "directional only", reason

    if owned_low_sample_reason:
        return "directional only", owned_low_sample_reason

    return (
        "fully comparable",
        "all controlled topic gap rows have evaluated gaps, usable confidence, "
        "and no comparability blockers",
    )


def build_executive_summary(data: ReportData) -> str:
    quality = data.data_quality
    if not quality.get("competitors"):
        return (
            "No competitors are available in PostgreSQL yet, so this report cannot "
            "summarize market patterns. Load competitors, crawl pages, extract "
            "insights, and rerun the report."
        )

    top_sov = next(
        (row for row in data.share_of_voice if float(row.get("share_of_voice") or 0) > 0),
        None,
    )
    scorecards_by_name = report_competitor_scorecard_by_name(data)
    summary_parts = [
        f"This report summarizes {format_int(quality.get('competitors'))} competitor(s), "
        f"{format_int(quality.get('crawled_ok_pages'))} crawled OK page(s), "
        f"and {format_int(quality.get('insights'))} extracted content intelligence record(s) from PostgreSQL."
    ]
    if top_sov:
        top_competitor = clean_value(top_sov.get("competitor"))
        top_scorecard = scorecards_by_name.get(top_competitor.lower(), {})
        if is_low_confidence(top_scorecard.get("score_confidence")):
            summary_parts.append(
                f"{top_competitor} has the largest crawled word share in the "
                f"selected URL dataset at {format_percent(top_sov.get('share_of_voice'))}, "
                "but its sample confidence is low / directional only; do not treat "
                "this as a leader or fully comparable ranking."
            )
        else:
            summary_parts.append(
                f"{top_competitor} has the largest crawled "
                f"word share in the selected URL dataset at "
                f"{format_percent(top_sov.get('share_of_voice'))}; this reflects "
                "technically successful crawled word volume only, not market position or brand demand."
            )
    else:
        summary_parts.append(
            "No crawled word share proxy is available yet because no KPI snapshot "
            "with technically successful crawled words was found."
        )

    if quality.get("topics"):
        summary_parts.append(
            f"Topic modeling has produced {format_int(quality.get('topics'))} document-topic assignment(s)."
        )
    else:
        summary_parts.append("Topic analysis is not yet available.")

    return "\n\n".join(summary_parts)


def build_llm_summary_messages(data: ReportData) -> list[dict[str, str]]:
    allowed_competitor_names = sorted(
        {
            clean_value(row.get("competitor"))
            for row in data.dataset_scope
            if clean_value(row.get("competitor"))
        }
    )
    invalid_or_non_evaluable_total = sum(
        int(row.get("invalid_or_non_evaluable") or 0)
        for row in data.dataset_scope
    )
    facts = {
        "generated_date": str(data.generated_date),
        "kpi_date": str(data.kpi_selection.selected_date or "not_available"),
        "allowed_competitor_names": allowed_competitor_names,
        "invalid_or_non_evaluable_total": invalid_or_non_evaluable_total,
        "data_quality": data.data_quality,
        "crawled_word_share_proxy_diagnostics": data.share_of_voice[:5],
        "dataset_scope": data.dataset_scope[:5],
        "core_competitor_scorecards": data.competitor_scorecards[:5],
        "core_opportunity_backlog": data.opportunity_backlog[:5],
        "topic_output_status": (
            "diagnostic_only; topic labels must not be treated as operational "
            "opportunity sources unless promoted by quality gates"
        ),
        "topic_diagnostics": data.topic_coverage[:5],
    }
    system_prompt = """
You are a market intelligence editor polishing an executive summary.
Use only the provided PostgreSQL-derived facts.
Do not perform web research.
Do not invent market share.
Do not invent competitor facts.
Clearly distinguish proxy metrics from true market share.
Do not declare a competitor winner from crawled word share alone.
Do not use the phrase "share of voice"; use "crawled word share proxy" instead.
Do not say a competitor dominates, leads the market, or has market presence from proxy metrics.
If invalid_or_non_evaluable_total is greater than 0, do not say all crawled pages validated successfully.
Do not say insights were extracted from all raw pages unless data_quality.insights equals data_quality.raw_pages.
Use data_quality.insights for extracted insight count and data_quality.raw_pages for raw page count.
Use data_quality.valid_insights for analytically valid insight count.
If data_quality.invalid_insights is greater than 0, explicitly keep those records diagnostic-only.
Do not use vague strategic phrases such as content engagement, dataset integrity is affirmed, or competitive standing.
Use competitor names exactly as listed in allowed_competitor_names.
Do not rename, abbreviate, title-case, or autocorrect competitor names.
If evidence is missing, say that there is not enough data.
Return concise Markdown paragraphs only.
""".strip()
    user_prompt = f"Database-derived report facts:\n{json.dumps(facts, default=str, indent=2)}"
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def generate_llm_executive_summary(data: ReportData) -> str:
    load_dotenv()
    if not os.getenv("OPENAI_API_KEY", "").strip():
        raise RuntimeError(
            "OPENAI_API_KEY is required when --use-llm-summary is provided."
        )

    from openai import OpenAI

    client = OpenAI()
    model = os.getenv("OPENAI_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL
    response = client.responses.create(
        model=model,
        input=build_llm_summary_messages(data),
    )
    summary = getattr(response, "output_text", "").strip()
    if not summary:
        raise RuntimeError("OpenAI response did not include executive summary text.")
    return sanitize_llm_executive_summary(summary, data)


def render_dataset_scope(data: ReportData) -> str:
    rows = [
        [
            row.get("competitor"),
            row.get("website"),
            row.get("category"),
            row.get("country"),
            format_int(row.get("configured_urls")),
            format_int(row.get("pages_crawled")),
            format_int(row.get("crawled_ok")),
            format_int(row.get("valid_assets")),
            format_int(row.get("invalid_or_non_evaluable")),
            format_int(row.get("insights_extracted")),
            format_int(row.get("valid_insights")),
            format_int(row.get("invalid_insights")),
        ]
        for row in data.dataset_scope
    ]
    scope_table = render_markdown_table(
        [
            "Competitor",
            "Website",
            "Category",
            "Country",
            "Configured URLs",
            "Pages Crawled",
            "Crawled OK",
            "Valid Assets",
            "Invalid / Non-Evaluable",
            "Raw Insights",
            "Valid Insights",
            "Invalid Insights",
        ],
        rows,
    )
    source_rows = [
        [
            row.get("source_type"),
            format_int(row.get("pages_crawled")),
            format_int(row.get("crawled_ok")),
            format_int(row.get("valid_assets")),
            format_int(row.get("invalid_or_non_evaluable")),
            format_int(row.get("insights_extracted")),
            format_int(row.get("valid_insights")),
            format_int(row.get("invalid_insights")),
        ]
        for row in data.source_type_coverage
    ]
    return "\n\n".join(
        [
            f"Date generated: {data.generated_date.isoformat()}",
            "Competitors analyzed:",
            scope_table,
            "Source type coverage:",
            render_markdown_table(
                [
                    "Source Type",
                    "Pages Crawled",
                    "Crawled OK",
                    "Valid Assets",
                    "Invalid / Non-Evaluable",
                    "Raw Insights",
                    "Valid Insights",
                    "Invalid Insights",
                ],
                source_rows,
            ),
        ]
    )


def render_competitor_overview(data: ReportData) -> str:
    rows = [
        [
            row.get("competitor"),
            format_int(row.get("pages_analyzed")),
            format_int(row.get("total_words")),
            format_int(row.get("valid_assets")),
            format_int(row.get("valid_asset_words")),
            format_percent(row.get("share_of_voice")),
            format_int(row.get("pricing_mentions")),
            format_int(row.get("feature_mentions")),
        ]
        for row in data.competitor_overview
    ]
    return render_markdown_table(
        [
            "Competitor",
            "Crawled OK",
            "Crawled Words",
            "Valid Assets",
            "Valid Asset Words",
            "Crawled Word Share Proxy",
            "Pricing Mentions",
            "Feature Mentions",
        ],
        rows,
    )


def render_share_of_voice(data: ReportData) -> str:
    note = (
        "Crawled Word Share Proxy is calculated from crawled word counts. "
        "This is the share of technically successful crawled words in the selected URL "
        "dataset, not market share or brand demand."
    )
    if data.kpi_selection.used_fallback:
        note += (
            f"\n\nRequested KPI date {data.kpi_selection.requested_date.isoformat()} "
            f"was not available; using latest KPI date {data.kpi_selection.selected_date}."
        )
    elif data.kpi_selection.selected_date:
        note += f"\n\nKPI date: {data.kpi_selection.selected_date}."
    else:
        note += "\n\nNo KPI snapshot is available yet."

    rows = [
        [
            row.get("competitor"),
            format_int(row.get("pages_analyzed")),
            format_int(row.get("total_words")),
            format_int(row.get("valid_assets")),
            format_int(row.get("valid_asset_words")),
            format_percent(row.get("share_of_voice")),
        ]
        for row in data.share_of_voice
        if float(row.get("share_of_voice") or 0) > 0
    ]
    return note + "\n\n" + render_markdown_table(
        [
            "Competitor",
            "Crawled OK",
            "Crawled Words",
            "Valid Assets",
            "Valid Asset Words",
            "Crawled Word Share Proxy",
        ],
        rows,
    )


def render_content_inventory(data: ReportData) -> str:
    mix_rows = [
        [
            row.get("competitor_name"),
            row.get("asset_type"),
            format_int(row.get("assets_of_type")),
            format_percent(row.get("asset_type_share")),
        ]
        for row in data.asset_type_mix
    ]
    asset_rows = [
        [
            row.get("competitor_name"),
            row.get("asset_type"),
            row.get("url"),
            truncate_text(row.get("title"), 80),
            format_int(row.get("word_count")),
            row.get("freshness_bucket"),
            format_score(row.get("content_depth_score")),
            format_score(row.get("metadata_completeness_score")),
        ]
        for row in data.content_inventory[:20]
    ]
    return "\n\n".join(
        [
            "Dataset diagnostics:",
            "Corpus balance:",
            render_share_of_voice(data),
            "Competitor crawl summary:",
            render_competitor_overview(data),
            "Asset type mix:",
            render_markdown_table(
                ["Competitor", "Asset Type", "Assets", "Share"],
                mix_rows,
            ),
            "Representative content assets:",
            render_markdown_table(
                [
                    "Competitor",
                    "Type",
                    "URL",
                    "Title",
                    "Words",
                    "Freshness",
                    "Depth",
                    "Metadata",
                ],
                asset_rows,
            ),
        ]
    )


def render_data_quality_issues(data: ReportData) -> str:
    note = (
        "These are crawl/input quality issues. They are not competitor weaknesses "
        "and are excluded from scoring where validity is required."
    )
    if not data.data_quality_issues:
        return note + "\n\nNo data quality issues detected."

    rows = [
        [
            row.get("competitor_name"),
            row.get("source_type"),
            row.get("url"),
            truncate_text(row.get("title"), 80),
            format_int(row.get("word_count")),
            format_data_quality_issue(row.get("validity_reason")),
            format_data_quality_action(row.get("recommended_action")),
        ]
        for row in data.data_quality_issues
    ]
    return note + "\n\n" + render_markdown_table(
        ["Competitor", "Source Type", "URL", "Title", "Words", "Issue", "Action"],
        rows,
    )


def render_topic_coverage_and_gaps(data: ReportData) -> str:
    owned_domain_configured = bool(data.data_quality.get("owned_domain_configured"))
    owned_scope_row = next(
        (row for row in data.dataset_scope if row.get("is_owned_domain") is True),
        None,
    )
    owned_valid_assets = int(owned_scope_row.get("valid_assets") or 0) if owned_scope_row else 0
    owned_low_sample_reason = (
        f"owned domain has low sample confidence: {owned_valid_assets} valid assets"
        if owned_domain_configured and owned_valid_assets < 3
        else ""
    )
    controlled_rows = [
        row for row in data.topic_coverage if row.get("controlled_topic_id")
    ]
    strategic_controlled_rows = [
        row
        for row in controlled_rows
        if clean_value(row.get("controlled_topic_id")) != "unknown_other"
        and is_valid_report_asset(row)
    ]
    unknown_rows = [
        row
        for row in controlled_rows
        if clean_value(row.get("controlled_topic_id")) == "unknown_other"
    ]
    strategic_rows = [
        [
            row.get("competitor_name"),
            row.get("controlled_topic_label"),
            row.get("controlled_topic_confidence"),
            row.get("controlled_topic_assignment_reason"),
            format_int(row.get("document_count")),
            row.get("topic_saturation"),
            row.get("funnel_stage"),
        ]
        for row in strategic_controlled_rows
    ]
    distinct_strategic_topics = {
        clean_value(row.get("controlled_topic_id"))
        for row in strategic_controlled_rows
        if clean_value(row.get("controlled_topic_id"))
    }
    if len(distinct_strategic_topics) < 3:
        corpus_support_note = (
            "Controlled topic diagnostics: corpus does not currently support at "
            "least 3 distinct strategic topics. Add or refresh valid assets before "
            "treating topic granularity as stable."
        )
    else:
        corpus_support_note = (
            "Controlled topic diagnostics: corpus supports at least 3 distinct "
            "strategic controlled topics."
        )
    topic_saturation_note = (
        "Topic saturation requires a minimum distribution of at least 3 documents. "
        "Topics below that sample are marked insufficient data and are not used as "
        "high-confidence strategic opportunity sources."
    )
    unknown_count = sum(int(row.get("document_count") or 0) for row in unknown_rows)
    unknown_reason = (
        clean_value(unknown_rows[0].get("controlled_topic_assignment_reason"))
        if unknown_rows
        else "No unknown_other controlled assignments in the current coverage."
    )
    unknown_output = (
        f"unknown_other assignments: {format_int(unknown_count)}"
        f"\nLow confidence reason: {unknown_reason}"
    )

    diagnostic_source_rows = data.topic_diagnostics or data.topic_coverage
    coverage_rows = [
        [
            row.get("competitor_name"),
            format_topic_label(row.get("topic_label")),
            format_int(row.get("document_count")),
            row.get("funnel_stage"),
            row.get("avg_probability"),
        ]
        for row in diagnostic_source_rows
        if is_valid_report_asset(row)
    ]
    operational_gap_rows = [
        row
        for row in data.topic_gaps
        if clean_value(row.get("gap_reason")) != "not_configured"
    ]
    has_controlled_gap_fields = any(
        row.get("controlled_topic_id") or row.get("controlled_topic_label")
        for row in operational_gap_rows
    )
    if has_controlled_gap_fields:
        gap_headers = [
            "Topic",
            "Saturation",
            "Competitor Assets",
            "Owned Assets",
            "Gap Reason",
            "Gap Analysis Status",
            "Gap Analysis Reason",
        ]
        gap_rows = [
            [
                row.get("controlled_topic_label")
                or format_topic_label(row.get("topic_label")),
                row.get("topic_saturation"),
                format_int(row.get("competitor_assets_on_topic")),
                format_int(row.get("owned_assets_on_topic")),
                row.get("gap_reason"),
                format_gap_status(row.get("gap_analysis_status")),
                row.get("gap_analysis_reason"),
            ]
            for row in operational_gap_rows
        ]
    else:
        gap_headers = [
            "Topic",
            "Saturation",
            "Competitor Assets",
            "Gap Reason",
            "Gap Analysis Status",
            "Gap Analysis Reason",
        ]
        gap_rows = [
            [
                format_topic_label(row.get("topic_label")),
                row.get("topic_saturation"),
                format_int(row.get("competitor_assets_on_topic")),
                row.get("gap_reason"),
                format_gap_status(row.get("gap_analysis_status")),
                row.get("gap_analysis_reason"),
            ]
            for row in operational_gap_rows
        ]
    if not owned_domain_configured:
        gap_output = "Owned domain not configured; topic gap analysis is unavailable."
    else:
        status, reason = derive_topic_gap_section_status(
            operational_gap_rows, owned_low_sample_reason
        )
        status_header = format_section_status(status, reason)
        gap_output = status_header + "\n\n" + render_markdown_table(gap_headers, gap_rows)
    return "\n\n".join(
        [
            "Strategic controlled topic coverage:",
            render_markdown_table(
                [
                    "Competitor",
                    "Controlled Topic",
                    "Confidence",
                    "Assignment Reason",
                    "Documents",
                    "Saturation",
                    "Funnel Stage",
                ],
                strategic_rows,
            ),
            unknown_output,
            corpus_support_note,
            topic_saturation_note,
            "Corpus topic coverage diagnostics:",
            "Topic model diagnostics:",
            (
                "Current BERTopic labels are retained for exploratory corpus "
                "review only. They are not used as strategic opportunity sources."
            ),
            render_markdown_table(
                ["Competitor", "Topic", "Documents", "Funnel Stage", "Avg Probability"],
                coverage_rows,
            ),
            "Controlled topic gap analysis:",
            gap_output,
        ]
    )


def render_content_messaging(data: ReportData) -> str:
    messaging_rows = [
        [
            row.get("competitor_name"),
            format_int(row.get("insight_pages")),
            format_json_list(row.get("messaging_pillars")),
            format_json_list(row.get("value_proposition_themes")),
            format_json_list(row.get("pain_points")),
            format_json_list(row.get("proof_elements")),
            format_score(row.get("differentiation_score")),
            row.get("benefit_vs_feature_ratio"),
        ]
        for row in data.messaging_matrix
        if int(row.get("insight_pages") or 0) > 0
    ]
    proof_rows = [
        [
            row.get("competitor_name"),
            row.get("extracted_proof_type"),
            row.get("normalized_proof_type"),
            row.get("extracted_proof_strength"),
            row.get("normalized_proof_strength"),
            row.get("proof_normalization_reason"),
            format_int(row.get("proof_elements_count")),
            format_percent(row.get("proof_type_share")),
        ]
        for row in data.proof_type_mix
    ]
    pain_evidence_rows = [
        [
            row.get("competitor_name"),
            row.get("pain_point_category"),
            row.get("pain_point_evidence_type"),
            format_int(row.get("pain_point_count")),
            format_json_list(row.get("pain_points")),
            format_json_list(row.get("source_urls"), 3),
        ]
        for row in data.pain_point_evidence_mix
    ]
    return "\n\n".join(
        [
            "Messaging matrix:",
            render_markdown_table(
                [
                    "Competitor",
                    "Insight Pages",
                    "Pillars",
                    "Value Themes",
                    "Pain Points",
                    "Proof",
                    "Differentiation",
                    "Benefit/Feature",
                ],
                messaging_rows,
            ),
            "Pain point evidence breakdown:",
            render_markdown_table(
                [
                    "Competitor",
                    "Category",
                    "Evidence Type",
                    "Mentions",
                    "Pain Points",
                    "Source URLs",
                ],
                pain_evidence_rows,
            ),
            "Proof type breakdown:",
            render_markdown_table(
                [
                    "Competitor",
                    "Extracted Type",
                    "Normalized Type",
                    "Extracted Strength",
                    "Normalized Strength",
                    "Reason",
                    "Mentions",
                    "Share",
                ],
                proof_rows,
            ),
        ]
    )


def render_funnel_and_cta(data: ReportData) -> str:
    funnel_rows = [
        [
            row.get("competitor_name"),
            row.get("funnel_stage"),
            format_int(row.get("assets_in_stage")),
            format_percent(row.get("funnel_stage_share")),
        ]
        for row in data.funnel_mix
    ]
    cta_type_rows = [
        [
            row.get("competitor_name"),
            row.get("cta_type"),
            format_int(row.get("cta_type_count")),
            format_percent(row.get("cta_type_share")),
        ]
        for row in data.cta_type_mix
    ]
    return "\n\n".join(
        [
            "Funnel stage mix:",
            render_markdown_table(
                ["Competitor", "Funnel Stage", "Assets", "Share"],
                funnel_rows,
            ),
            "CTA class mix diagnostics:",
            render_markdown_table(
                ["Competitor", "CTA Class", "CTA Count", "CTA Class Share"],
                cta_type_rows,
            ),
        ]
    )


def render_content_quality(data: ReportData) -> str:
    rows = [
        [
            row.get("competitor_name"),
            row.get("asset_type"),
            row.get("url"),
            format_score(row.get("content_quality_score"))
            if row.get("content_quality_score") is not None
            else "unavailable",
            row.get("quality_bucket"),
            format_asset_score_confidence(
                row.get("quality_confidence") or row.get("score_confidence")
            ),
            row.get("quality_evidence_strength"),
            row.get("quality_reason"),
            format_score(row.get("depth_score")),
            format_score(row.get("proof_score")),
            format_metric_by_confidence(
                row.get("freshness_score"), row.get("freshness_confidence")
            ),
            row.get("freshness_confidence"),
            format_score(row.get("structure_score")),
            format_score(row.get("clarity_score")),
            format_score(row.get("cta_alignment_score")),
            format_json_list(row.get("quality_warnings"), 3),
        ]
        for row in data.content_quality[:20]
    ]
    note = (
        "Content quality score is a comparative indicator for the crawled corpus, "
        "not an absolute quality measurement. Freshness is excluded from "
        "Quality Score when unavailable. Rows with Asset Score Confidence = low "
        "are low confidence and directional only; they can show scores, but must "
        "not be treated as uncaveated top-ranked assets."
    )
    return note + "\n\n" + render_markdown_table(
        [
            "Competitor",
            "Type",
            "URL",
            "Quality",
            "Quality Bucket",
            "Asset Score Confidence",
            "Evidence Strength",
            "Asset Confidence Reason",
            "Depth",
            "Proof",
            "Freshness",
            "Freshness Confidence",
            "Structure",
            "Clarity",
            "CTA Alignment",
            "Warnings",
        ],
        rows,
    )


def render_competitor_scorecards(data: ReportData) -> str:
    confidence_order = {"high": 0, "medium": 1, "low": 2}

    def format_weighted_proof_value(row: dict[str, Any]) -> str:
        status = clean_value(row.get("weighted_proof_points_validation_status")).lower()
        raw_value = format_score(row.get("weighted_proof_points_per_valid_asset"))
        if status in {"unreliable", "out_of_scale"}:
            max_plausible = format_score(row.get("weighted_proof_points_max_plausible"))
            return f"unreliable (raw: {raw_value}; max plausible: {max_plausible})"
        return raw_value

    def scorecard_sort_key(row: dict[str, Any]) -> tuple[int, float, int, str]:
        try:
            avg_quality = float(row.get("avg_content_quality_score") or 0)
        except (TypeError, ValueError):
            avg_quality = 0
        try:
            valid_assets = int(row.get("valid_assets") or 0)
        except (TypeError, ValueError):
            valid_assets = 0
        confidence = clean_value(row.get("score_confidence")).lower()
        return (
            confidence_order.get(confidence, 3),
            -avg_quality,
            -valid_assets,
            clean_value(row.get("competitor_name")).lower(),
        )

    rows = [
        [
            row.get("competitor_name"),
            format_int(row.get("valid_assets")),
            format_percent(row.get("insight_coverage")),
            format_sample_confidence(row.get("score_confidence")),
            row.get("confidence_reason"),
            format_score(row.get("avg_content_quality_score")),
            format_score(row.get("avg_content_depth_score")),
            format_score(row.get("avg_metadata_completeness_score")),
            format_score(row.get("avg_bofu_strength_score")),
            format_int(row.get("high_asset_score_confidence_assets")),
            format_int(row.get("medium_asset_score_confidence_assets")),
            format_int(row.get("low_asset_score_confidence_assets")),
            format_score(row.get("proof_elements_per_valid_asset")),
            format_score(row.get("strong_proof_elements_per_valid_asset")),
            format_weighted_proof_value(row),
            clean_value(row.get("weighted_proof_points_validation_status")) or "not_available",
            clean_value(row.get("weighted_proof_points_validation_reason")) or NOT_ENOUGH_DATA,
        ]
        for row in sorted(data.competitor_scorecards, key=scorecard_sort_key)
    ]
    note = (
        "Sample confidence is separate from asset score confidence: sample confidence "
        "summarizes valid asset count and extraction coverage, while asset score "
        "confidence reflects per-asset scoring uncertainty. Low sample confidence "
        "is displayed as directional only and is not a fully comparable principal "
        "ranking signal. Unreliable weighted proof values are shown only as "
        "diagnostics and are not comparable ranking values."
    )
    return note + "\n\n" + render_markdown_table(
        [
            "Competitor",
            "Valid Assets",
            "Insight Coverage",
            "Sample Confidence",
            "Sample Confidence Reason",
            "Avg Quality",
            "Avg Depth",
            "Avg Metadata",
            "BOFU Strength",
            "High Asset Score Confidence Assets",
            "Medium Asset Score Confidence Assets",
            "Low Asset Score Confidence Assets",
            "Proof Elements per Valid Asset",
            "Strong Proof per Valid Asset",
            "Weighted Proof Points per Valid Asset",
            "Weighted Proof Validation",
            "Weighted Proof Validation Reason",
        ],
        rows,
    )


def render_opportunity_backlog(data: ReportData) -> str:
    renderable_rows = [
        row for row in data.opportunity_backlog if opportunity_row_is_renderable(row)
    ]
    rows = [
        [
            cap_directional_opportunity_value(row, "priority"),
            cap_directional_opportunity_value(
                row,
                "sample_confidence" if row.get("sample_confidence") is not None else "confidence",
            ),
            row.get("evidence_strength"),
            row.get("evidence_mix"),
            (
                format_score(row.get("weighted_evidence_score"))
                if row.get("weighted_evidence_score") is not None
                else None
            ),
            row.get("dominant_evidence_type"),
            (
                format_percent(row.get("fallback_share"))
                if row.get("fallback_share") is not None
                else None
            ),
            format_int(row.get("source_count")),
            format_int(row.get("competitor_prevalence")),
            row.get("funnel_importance"),
            format_gap_status(row.get("owned_gap_status")),
            row.get("related_topic"),
            row.get("gap_reason"),
            row.get("recommended_action_type"),
            row.get("suggested_asset_type"),
            row.get("suggested_funnel_stage"),
            row.get("suggested_cta"),
            row.get("why_now"),
            row.get("blocked_by"),
            format_json_list(row.get("source_urls"), 3),
        ]
        for row in renderable_rows
    ]
    status, reason = derive_opportunity_section_status(data.opportunity_backlog)
    status_header = format_section_status(status, reason)
    return status_header + "\n\n" + render_markdown_table(
        [
            "Priority",
            "Confidence",
            "Evidence Strength",
            "Evidence Mix",
            "Weighted Evidence",
            "Dominant Evidence",
            "Fallback Share",
            "Source Count",
            "Competitor Prevalence",
            "Funnel Importance",
            "Owned Gap Status",
            "Topic/Area",
            "Reason",
            "Action Type",
            "Asset Type",
            "Funnel Stage",
            "CTA",
            "Why Now",
            "Blocked By",
            "Source URLs",
        ],
        rows,
    )


def render_competitive_observations(data: ReportData) -> str:
    weak_page_rows = [
        [
            "weak competitor page",
            row.get("competitor_name"),
            row.get("asset_type"),
            "1",
            "quality",
            row.get("quality_confidence") or row.get("score_confidence"),
            format_score(row.get("content_quality_score")),
            row.get("url"),
        ]
        for row in data.content_quality
        if clean_value(row.get("quality_bucket")) == "weak"
        and is_present(row.get("url"))
        and is_valid_report_asset(row)
        and is_external_competitor_row(row)
    ]
    return render_markdown_table(
        [
            "Observation Type",
            "Competitor",
            "Observation",
            "Sources",
            "Signal",
            "Confidence",
            "Value",
            "Source URLs",
        ],
        weak_page_rows,
    )


def render_unavailable_analyses(data: ReportData) -> str:
    rows: list[list[Any]] = []
    if not data.data_quality.get("owned_domain_configured"):
        rows.append(
            [
                "topic gap analysis",
                "not_evaluable",
                "missing owned-domain context",
                "Configure one competitor as the owned domain before treating topic gaps as operational opportunities.",
            ]
        )

    for row in data.opportunity_backlog:
        if not has_source_urls(row.get("source_urls")) or clean_value(row.get("priority")) == "not_evaluable":
            rows.append(
                [
                    row.get("related_topic"),
                    "not_evaluable",
                    row.get("blocked_by") or "missing source evidence",
                    row.get("why_now") or "No operational recommendation is shown until source evidence is available.",
                ]
            )

    if not rows:
        return "No unavailable analyses detected."

    return render_markdown_table(
        ["Analysis", "Status", "Blocked By", "Resolution"],
        rows,
    )


def render_risks(data: ReportData) -> str:
    quality = data.data_quality
    risks = [
        "The report summarizes only pages stored in PostgreSQL and does not perform uncontrolled web research.",
        "True market share is not calculated unless external market data is provided.",
    ]
    if not quality.get("crawled_ok_pages"):
        risks.append("No technically successful crawls are available, so content-based analysis is limited.")
    if not quality.get("insights"):
        risks.append("No extracted page insights are available, so messaging, pricing, and feature analysis are limited.")
    if not data.kpi_selection.selected_date:
        risks.append("No KPI snapshot is available yet; run scripts/04_compute_kpis.py before relying on proxy metrics.")
    if not quality.get("topics"):
        risks.append("No topic documents are available; run scripts/03_topic_modeling.py when enough crawled pages exist.")
    if quality.get("failed_pages"):
        risks.append(f"{format_int(quality.get('failed_pages'))} crawl failure(s) are present in raw_pages.")
    return "\n".join(f"- {item}" for item in risks)


def render_next_actions(data: ReportData) -> str:
    actions = [
        "Add or refresh competitor URLs for missing source types, especially pricing, product, case studies, and comparison pages.",
        "Rerun crawling and extraction for newly added URLs, then recompute KPI snapshots.",
        "Validate proxy findings with external market data before making market share claims.",
    ]
    if not data.data_quality.get("topics"):
        actions.append("Run topic modeling after at least five eligible crawled documents are available.")
    return "\n".join(f"- {item}" for item in actions)


def render_report(data: ReportData, executive_summary: str | None = None) -> str:
    summary = executive_summary or build_executive_summary(data)
    methodology_note = (
        "This report is based on crawled public content. It does not estimate true "
        "market share. Crawled word share proxy and content share are corpus-based proxy metrics."
    )
    metric_legend = (
        "Metric legend: measured values are numeric only when the metric is available. "
        "N/A means the metric is not measurable or not available in the current "
        "corpus and is not comparable as a numeric value. Unreliable values are "
        "visibly flagged rather than silently trusted. Directional values are "
        "caveated signals, not fully comparable rankings."
    )
    sections = [
        ("1. Executive Summary", summary + "\n\n" + methodology_note + "\n\n" + metric_legend),
        ("2. Dataset Scope", render_dataset_scope(data)),
        ("3. Data Quality Issues", render_data_quality_issues(data)),
        ("4. Content Inventory", render_content_inventory(data)),
        ("5. Topic Diagnostics & Gaps", render_topic_coverage_and_gaps(data)),
        ("6. Messaging & Positioning", render_content_messaging(data)),
        ("7. Funnel & CTA Intelligence", render_funnel_and_cta(data)),
        ("8. Content Quality Analysis", render_content_quality(data)),
        ("9. Competitor Scorecards", render_competitor_scorecards(data)),
        ("10. Opportunity Backlog", render_opportunity_backlog(data)),
        ("11. Competitive Observations", render_competitive_observations(data)),
        ("12. Unavailable Analyses", render_unavailable_analyses(data)),
        ("13. Data Quality Notes", render_risks(data)),
        ("14. Recommended Next Actions", render_next_actions(data)),
    ]
    content = [
        f"# Competitor Content Intelligence Report\n\nGenerated: {data.generated_date.isoformat()}"
    ]
    for heading, body in sections:
        content.append(f"## {heading}\n\n{body.strip()}")
    return "\n\n".join(content).rstrip() + "\n"


def write_report(markdown: str, output_dir: Path, report_date: date) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"market_report_{report_date.isoformat()}.md"
    path.write_text(markdown, encoding="utf-8")
    return path


def run(args: argparse.Namespace) -> Path:
    engine = get_engine()
    with engine.connect() as connection:
        data = fetch_report_data(connection, args.date)

    executive_summary = None
    if args.use_llm_summary:
        executive_summary = generate_llm_executive_summary(data)

    markdown = render_report(data, executive_summary=executive_summary)
    return write_report(markdown, args.output_dir, args.date)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    try:
        path = run(args)
    except RuntimeError as exc:
        print("Report generation failed:")
        print(f"  errors: {exc}")
        raise SystemExit(1) from exc

    print(f"Report written: {path}")


if __name__ == "__main__":
    main()
