import importlib.util
import copy
import json
import sys
from dataclasses import fields
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "05_generate_report.py"
AUDITED_MOJIBAKE_TITLE = (
    "Page not found \u00c3\u00a2\u00e2\u201a\u00ac\u00e2\u20ac\u009d "
    "fMusic Docs | demo_owned AI"
)
DOUBLE_ENCODED_MOJIBAKE_TITLE = (
    "Page not found "
    "\u00c3\u0192\u00c2\u00a2\u00c3\u00a2\u00e2\u20ac\u0161\u00c2\u00ac"
    "\u00c3\u00a2\u00e2\u201a\u00ac\u00c2\u009d "
    "fMusic Docs | demo_owned AI"
)
NORMALIZED_AUDITED_TITLE = "Page not found - fMusic Docs | demo_owned AI"
INVALID_SENTINEL_URL = "https://invalid.example.com/template-404"
INVALID_SENTINEL_TITLE = "Placeholder Template 404"

sys.path.insert(0, str(REPO_ROOT / "scripts"))
spec = importlib.util.spec_from_file_location("generate_report", SCRIPT_PATH)
generate_report = importlib.util.module_from_spec(spec)
sys.modules["generate_report"] = generate_report
spec.loader.exec_module(generate_report)


def sample_report_data():
    report_date = date(2026, 4, 27)
    return generate_report.ReportData(
        generated_date=report_date,
        kpi_selection=generate_report.KpiSelection(
            requested_date=report_date,
            selected_date=report_date,
        ),
        dataset_scope=[
            {
                "competitor": "Acme Analytics",
                "website": "https://example.com",
                "category": "Analytics",
                "country": "US",
                "configured_urls": 2,
                "pages_crawled": 2,
                "crawled_ok": 2,
                "valid_assets": 1,
                "invalid_or_non_evaluable": 1,
                "insights_extracted": 1,
                "valid_insights": 1,
                "invalid_insights": 0,
            },
            {
                "competitor": "demo_owned",
                "website": "https://www.demo_owned.com/",
                "category": "Audio AI",
                "country": "Italy",
                "configured_urls": 6,
                "pages_crawled": 6,
                "crawled_ok": 6,
                "valid_assets": 2,
                "invalid_or_non_evaluable": 4,
                "insights_extracted": 2,
                "valid_insights": 2,
                "invalid_insights": 0,
            }
        ],
        source_type_coverage=[
            {
                "source_type": "pricing",
                "pages_crawled": 1,
                "crawled_ok": 1,
                "valid_assets": 1,
                "invalid_or_non_evaluable": 0,
                "insights_extracted": 1,
                "valid_insights": 1,
                "invalid_insights": 0,
            },
            {
                "source_type": "docs",
                "pages_crawled": 4,
                "crawled_ok": 4,
                "valid_assets": 0,
                "invalid_or_non_evaluable": 4,
                "insights_extracted": 0,
                "valid_insights": 0,
                "invalid_insights": 0,
            }
        ],
        competitor_overview=[
            {
                "competitor": "Acme Analytics",
                "pages_analyzed": 2,
                "total_words": 1200,
                "share_of_voice": 1.0,
                "valid_assets": 1,
                "valid_asset_words": 800,
                "sentiment_positive_share": 0.5,
                "sentiment_negative_share": 0.0,
                "pricing_mentions": 1,
                "feature_mentions": 3,
            }
        ],
        share_of_voice=[
            {
                "competitor": "Acme Analytics",
                "pages_analyzed": 2,
                "total_words": 1200,
                "share_of_voice": 1.0,
                "valid_assets": 1,
                "valid_asset_words": 800,
            }
        ],
        content_inventory=[
            {
                "competitor_name": "Acme Analytics",
                "url": "https://example.com/pricing",
                "asset_type": "pricing",
                "title": "Pricing",
                "word_count": 800,
                "freshness_bucket": "unknown",
                "content_depth_score": 70,
                "metadata_completeness_score": 80,
            }
        ],
        asset_type_mix=[
            {
                "competitor_name": "Acme Analytics",
                "asset_type": "pricing",
                "assets_of_type": 1,
                "total_assets": 2,
                "asset_type_share": 0.5,
            }
        ],
        topic_coverage=[
            {
                "competitor_name": "Acme Analytics",
                "topic_label": "pricing / analytics",
                "document_count": 1,
                "avg_probability": "0.8",
                "funnel_stage": "BOFU",
                "source_urls": ["https://example.com/pricing"],
            }
        ],
        topic_gaps=[
            {
                "topic_label": "pricing / analytics",
                "topic_saturation": "low",
                "competitor_assets_on_topic": 1,
                "gap_reason": "not_configured",
            }
        ],
        messaging_matrix=[
            {
                "competitor_name": "Acme Analytics",
                "insight_pages": 1,
                "messaging_pillars": ["speed"],
                "value_proposition_themes": ["fast analytics"],
                "pain_points": [
                    "slow reporting",
                    {
                        "pain_point_text": "manual exports",
                        "pain_point_category": "manual work",
                        "pain_point_evidence_type": "keyword_fallback",
                        "source_text": "Automate manual exports.",
                    },
                ],
                "pain_point_details": [
                    {
                        "pain_point_text": "manual exports",
                        "pain_point_category": "manual work",
                        "pain_point_evidence_type": "keyword_fallback",
                        "source_text": "Automate manual exports.",
                    }
                ],
                "proof_elements": ["setup in minutes"],
                "differentiation_score": 75,
                "benefit_vs_feature_ratio": 1.0,
                "example_tone_label": "practical",
            }
        ],
        pain_point_evidence_mix=[
            {
                "competitor_name": "Acme Analytics",
                "pain_point_category": "manual work",
                "pain_point_evidence_type": "keyword_fallback",
                "pain_point_count": 1,
                "pain_points": ["manual exports"],
                "source_urls": ["https://example.com/home"],
            },
            {
                "competitor_name": "Acme Analytics",
                "pain_point_category": "time cost",
                "pain_point_evidence_type": "inferred_from_benefit",
                "pain_point_count": 1,
                "pain_points": ["slow reporting"],
                "source_urls": ["https://example.com/pricing"],
            },
        ],
        proof_type_mix=[
            {
                "competitor_name": "Acme Analytics",
                "extracted_proof_type": "generic_claim",
                "normalized_proof_type": "generic_claim",
                "extracted_proof_strength": "high",
                "normalized_proof_strength": "low",
                "proof_normalization_reason": "downgraded commercial or generic proof from extracted high strength",
                "proof_elements_count": 1,
                "proof_type_share": 0.5,
            },
            {
                "competitor_name": "Acme Analytics",
                "extracted_proof_type": "statistic",
                "normalized_proof_type": "metric",
                "extracted_proof_strength": "high",
                "normalized_proof_strength": "high",
                "proof_normalization_reason": "mapped extracted proof type to controlled taxonomy",
                "proof_elements_count": 1,
                "proof_type_share": 0.5,
            },
        ],
        funnel_mix=[
            {
                "competitor_name": "Acme Analytics",
                "funnel_stage": "BOFU",
                "assets_in_stage": 1,
                "total_assets": 1,
                "funnel_stage_share": 1.0,
            }
        ],
        cta_coverage=[
            {
                "competitor_name": "Acme Analytics",
                "total_insight_pages": 2,
                "pages_with_any_cta": 2,
                "any_cta_coverage": 1.0,
                "pages_with_conversion_cta": 1,
                "conversion_cta_coverage": 0.5,
                "pages_with_secondary_cta": 1,
                "secondary_cta_coverage": 0.5,
                "sample_confidence": "low",
            }
        ],
        cta_type_mix=[
            {
                "competitor_name": "Acme Analytics",
                "cta_type": "primary",
                "cta_type_count": 1,
                "cta_type_share": 1.0,
            }
        ],
        content_quality=[
            {
                "competitor_name": "Acme Analytics",
                "url": "https://example.com/pricing",
                "title": "Pricing",
                "asset_type": "pricing",
                "depth_score": 70,
                "proof_score": 60,
                "freshness_score": 20,
                "freshness_confidence": "unavailable",
                "structure_score": 80,
                "clarity_score": 85,
                "cta_alignment_score": 100,
                "content_quality_score": 76,
                "quality_score": 76,
                "score_confidence": "medium",
                "quality_confidence": "medium",
                "quality_bucket": "strong",
                "quality_evidence_strength": "medium",
                "quality_reason": "balanced active quality signals",
                "quality_warnings": ["undated_content"],
            },
            {
                "competitor_name": "Acme Analytics",
                "url": "https://example.com/learn-more",
                "title": "Learn More",
                "asset_type": "product",
                "depth_score": 24,
                "proof_score": 10,
                "freshness_score": 20,
                "freshness_confidence": "unavailable",
                "structure_score": 65,
                "clarity_score": 70,
                "cta_alignment_score": 45,
                "content_quality_score": 43,
                "quality_score": 43,
                "score_confidence": "low",
                "quality_confidence": "low",
                "quality_bucket": "weak",
                "quality_evidence_strength": "low",
                "quality_reason": (
                    "proof contribution capped: normalized evidence is only low or generic; "
                    "CTA contribution capped: only secondary CTAs were found; "
                    "low depth limits asset score without high normalized evidence"
                ),
                "quality_warnings": ["undated_content", "low_depth", "proof_capped", "cta_capped"],
            }
        ],
        competitor_scorecards=[
            {
                "competitor_name": "Acme Analytics",
                "valid_assets": 2,
                "insight_pages": 2,
                "insight_coverage": 1.0,
                "avg_content_quality_score": 74,
                "avg_content_depth_score": 70,
                "avg_metadata_completeness_score": 80,
                "avg_bofu_strength_score": 90,
                "proof_elements_count": 2,
                "strong_proof_elements_count": 1,
                "weighted_proof_points": 27,
                "proof_elements_per_valid_asset": 0.5,
                "strong_proof_elements_per_valid_asset": 0.25,
                "weighted_proof_points_per_valid_asset": 13.5,
                "score_confidence": "low",
                "confidence_reason": (
                    "sample confidence low: fewer than 3 valid assets, "
                    "even if extraction coverage is complete"
                ),
            }
        ],
        opportunity_backlog=[
            {
                "priority": "medium",
                "confidence": "medium",
                "evidence_strength": "repeated_competitor_weakness",
                "source_count": 2,
                "related_topic": "pricing",
                "gap_reason": "repeated_weak_content_quality",
                "competitor_evidence": "Acme Analytics",
                "suggested_asset_type": "pricing",
                "suggested_funnel_stage": "BOFU",
                "suggested_cta": "start trial",
                "why_now": "Repeated weak competitor pages point to a strategic content gap.",
                "blocked_by": "none",
                "source_urls": ["https://example.com/pricing"],
                "competitor_prevalence": 2,
                "funnel_importance": "high",
                "owned_gap_status": "not_evaluated_without_owned_gap",
                "sample_confidence": "medium",
                "recommended_action_type": "exploit_repeated_competitor_weakness",
            },
            {
                "priority": "not_evaluable",
                "confidence": "low",
                "evidence_strength": "missing_source",
                "source_count": 0,
                "related_topic": "pricing",
                "gap_reason": "not_configured",
                "competitor_evidence": "Acme Analytics",
                "suggested_asset_type": "pricing",
                "suggested_funnel_stage": "BOFU",
                "suggested_cta": "start trial",
                "why_now": "Owned-domain context is missing.",
                "blocked_by": "missing owned-domain context",
                "source_urls": [],
                "competitor_prevalence": 0,
                "funnel_importance": "unknown",
                "owned_gap_status": "blocked",
                "sample_confidence": "low",
                "recommended_action_type": "blocked_analysis",
            }
        ],
        data_quality_issues=[
            {
                "competitor_name": "demo_owned",
                "source_type": "case_studies",
                "url": "https://www.demo_owned.com/user-stories",
                "title": "Workhorse - Webflow HTML Website Template",
                "word_count": 25,
                "has_insight": False,
                "asset_validity_status": "invalid",
                "validity_reason": "low_word_count",
                "recommended_action": "review_page_or_crawl",
            }
        ],
        data_quality={
            "competitors": 1,
            "owned_domain_configured": False,
            "raw_pages": 2,
            "crawled_ok_pages": 2,
            "failed_pages": 0,
            "insights": 1,
            "valid_insights": 1,
            "invalid_insights": 0,
            "topics": 1,
            "kpi_rows": 1,
        },
    )


def report_data_with_invalid_sentinel_in_strategic_inputs():
    data = copy.deepcopy(sample_report_data())

    data.data_quality_issues.append(
        {
            "competitor_name": "InvalidCo",
            "source_type": "docs",
            "url": INVALID_SENTINEL_URL,
            "title": INVALID_SENTINEL_TITLE,
            "word_count": 12,
            "has_insight": False,
            "asset_validity_status": "invalid",
            "validity_reason": "template_or_placeholder",
            "recommended_action": "review_page_or_crawl",
        }
    )
    data.topic_coverage.append(
        {
            "competitor_name": "InvalidCo",
            "topic_label": "placeholder / template",
            "document_count": 1,
            "avg_probability": "0.9",
            "funnel_stage": "MOFU",
            "source_urls": [INVALID_SENTINEL_URL],
            "is_valid_content_asset": False,
            "validity_reason": "template_or_placeholder",
        }
    )
    data.content_quality.append(
        {
            "competitor_name": "InvalidCo",
            "url": INVALID_SENTINEL_URL,
            "title": INVALID_SENTINEL_TITLE,
            "asset_type": "docs",
            "depth_score": 5,
            "proof_score": 0,
            "freshness_score": 20,
            "freshness_confidence": "unavailable",
            "structure_score": 10,
            "clarity_score": 10,
            "cta_alignment_score": 0,
            "content_quality_score": 8,
            "quality_score": 8,
            "score_confidence": "low",
            "quality_confidence": "low",
            "quality_bucket": "weak",
            "quality_evidence_strength": "none",
            "quality_reason": "invalid placeholder page must stay diagnostic only",
            "quality_warnings": ["invalid_content_asset"],
            "is_valid_content_asset": False,
            "validity_reason": "template_or_placeholder",
        }
    )
    data.opportunity_backlog.insert(
        0,
        {
            "priority": "high",
            "confidence": "high",
            "evidence_strength": "repeated_competitor_weakness",
            "source_count": 1,
            "related_topic": "placeholder template",
            "gap_reason": "repeated_weak_content_quality",
            "competitor_evidence": "InvalidCo placeholder page",
            "suggested_asset_type": "docs",
            "suggested_funnel_stage": "MOFU",
            "suggested_cta": "download guide",
            "why_now": "Invalid placeholder page should not become strategy.",
            "blocked_by": "none",
            "source_urls": [INVALID_SENTINEL_URL],
            "competitor_prevalence": 1,
            "funnel_importance": "medium",
            "owned_gap_status": "not_evaluated_without_owned_gap",
            "sample_confidence": "low",
            "recommended_action_type": "exploit_repeated_competitor_weakness",
            "is_valid_content_asset": False,
            "validity_reason": "template_or_placeholder",
        },
    )
    return data


def report_data_with_low_sample_display_gating_risks():
    data = copy.deepcopy(sample_report_data())
    scorecards = [
        {
            **data.competitor_scorecards[0],
            "competitor_name": "One Page Winner",
            "valid_assets": 1,
            "insight_pages": 1,
            "insight_coverage": 1.0,
            "avg_content_quality_score": 98,
            "avg_content_depth_score": 95,
            "avg_metadata_completeness_score": 90,
            "avg_bofu_strength_score": 95,
            "high_asset_score_confidence_assets": 0,
            "medium_asset_score_confidence_assets": 0,
            "low_asset_score_confidence_assets": 1,
            "proof_elements_count": 4,
            "strong_proof_elements_count": 1,
            "weighted_proof_points": 25,
            "proof_elements_per_valid_asset": 4,
            "strong_proof_elements_per_valid_asset": 1,
            "weighted_proof_points_per_valid_asset": 25,
            "score_confidence": "low",
            "confidence_reason": (
                "sample confidence low: fewer than 3 valid assets, "
                "even if extraction coverage is complete"
            ),
        },
        {
            **data.competitor_scorecards[0],
            "competitor_name": "Reliable Competitor",
            "valid_assets": 6,
            "insight_pages": 6,
            "insight_coverage": 1.0,
            "avg_content_quality_score": 72,
            "avg_content_depth_score": 70,
            "avg_metadata_completeness_score": 80,
            "avg_bofu_strength_score": 70,
            "high_asset_score_confidence_assets": 5,
            "medium_asset_score_confidence_assets": 1,
            "low_asset_score_confidence_assets": 0,
            "proof_elements_count": 9,
            "strong_proof_elements_count": 6,
            "weighted_proof_points": 168,
            "proof_elements_per_valid_asset": 1.5,
            "strong_proof_elements_per_valid_asset": 1,
            "weighted_proof_points_per_valid_asset": 28,
            "score_confidence": "high",
            "confidence_reason": (
                "sample confidence high: 5+ valid assets with 90 percent+ "
                "extraction coverage"
            ),
        },
    ]
    content_quality = [
        {
            **data.content_quality[0],
            "competitor_name": "One Page Winner",
            "url": "https://one-page.example.com/home",
            "title": "One Page Winner Home",
            "asset_type": "homepage",
            "content_quality_score": 99,
            "quality_score": 99,
            "quality_bucket": "strong",
            "score_confidence": "low",
            "quality_confidence": "low",
            "quality_evidence_strength": "low",
            "quality_reason": (
                "low depth limits asset score without high normalized evidence"
            ),
        },
        {
            **data.content_quality[0],
            "competitor_name": "Reliable Competitor",
            "url": "https://reliable.example.com/pricing",
            "title": "Reliable Pricing",
            "asset_type": "pricing",
            "content_quality_score": 72,
            "quality_score": 72,
            "quality_bucket": "strong",
            "score_confidence": "high",
            "quality_confidence": "high",
            "quality_evidence_strength": "high",
            "quality_reason": "balanced active quality signals",
        },
    ]
    return generate_report.ReportData(
        **{
            **data.__dict__,
            "share_of_voice": [
                {
                    "competitor": "One Page Winner",
                    "pages_analyzed": 1,
                    "total_words": 2000,
                    "share_of_voice": 0.7,
                    "valid_assets": 1,
                    "valid_asset_words": 2000,
                },
                {
                    "competitor": "Reliable Competitor",
                    "pages_analyzed": 6,
                    "total_words": 1200,
                    "share_of_voice": 0.3,
                    "valid_assets": 6,
                    "valid_asset_words": 1200,
                },
            ],
            "content_quality": content_quality,
            "competitor_scorecards": scorecards,
            "topic_gaps": [
                {
                    "topic_label": "pricing / analytics",
                    "topic_saturation": "medium",
                    "competitor_assets_on_topic": 3,
                    "gap_reason": "missing_on_owned_site",
                    "gap_analysis_status": "directional_only",
                    "gap_analysis_reason": (
                        "owned domain has low sample confidence: only 2 valid assets"
                    ),
                }
            ],
            "opportunity_backlog": [
                {
                    "priority": "high",
                    "confidence": "high",
                    "evidence_strength": "multiple_competitor_sources",
                    "source_count": 3,
                    "related_topic": "pricing / analytics",
                    "gap_reason": "missing_on_owned_site",
                    "suggested_asset_type": "comparison",
                    "suggested_funnel_stage": "BOFU",
                    "suggested_cta": "book demo",
                    "why_now": "Owned-domain gap is directional because owned sample is low.",
                    "blocked_by": "owned domain has low sample confidence",
                    "source_urls": ["https://competitor.example/pricing"],
                    "competitor_prevalence": 3,
                    "funnel_importance": "high",
                    "owned_gap_status": "directional_only",
                    "gap_analysis_status": "directional_only",
                    "gap_analysis_reason": (
                        "owned domain has low sample confidence: only 2 valid assets"
                    ),
                    "sample_confidence": "high",
                    "recommended_action_type": "fill_owned_topic_gap",
                    "topic_saturation": "medium",
                }
            ],
            "data_quality": {
                **data.data_quality,
                "owned_domain_configured": True,
            },
        }
    )


def report_data_with_pain_point_opportunity_evidence_mix():
    data = copy.deepcopy(sample_report_data())
    return generate_report.ReportData(
        **{
            **data.__dict__,
            "opportunity_backlog": [
                {
                    "priority": "high",
                    "confidence": "high",
                    "evidence_strength": "explicit_heavy_pain_point",
                    "evidence_mix": "explicit=3; inferred_from_benefit=1; keyword_fallback=0",
                    "weighted_evidence_score": 10,
                    "dominant_evidence_type": "explicit",
                    "fallback_share": 0.0,
                    "source_count": 4,
                    "related_topic": "manual exports",
                    "gap_reason": "repeated_pain_point",
                    "competitor_evidence": "3 competitors explicitly mention manual exports.",
                    "suggested_asset_type": "comparison",
                    "suggested_funnel_stage": "MOFU",
                    "suggested_cta": "book demo",
                    "why_now": "Repeated explicit pain-point evidence supports sharper positioning.",
                    "blocked_by": "none",
                    "source_urls": [
                        "https://example.com/home",
                        "https://competitor.example.com/pricing",
                    ],
                    "competitor_prevalence": 3,
                    "funnel_importance": "medium",
                    "owned_gap_status": "not_evaluated_without_owned_gap",
                    "sample_confidence": "high",
                    "recommended_action_type": "address_repeated_pain_point",
                },
                {
                    "priority": "low",
                    "confidence": "low",
                    "evidence_strength": "fallback_heavy_pain_point",
                    "evidence_mix": "explicit=0; inferred_from_benefit=1; keyword_fallback=5",
                    "weighted_evidence_score": 3,
                    "dominant_evidence_type": "keyword_fallback",
                    "fallback_share": 0.83,
                    "source_count": 6,
                    "related_topic": "export overhead",
                    "gap_reason": "repeated_pain_point",
                    "competitor_evidence": "Repeated pattern is mostly keyword fallback evidence.",
                    "suggested_asset_type": "comparison",
                    "suggested_funnel_stage": "MOFU",
                    "suggested_cta": "book demo",
                    "why_now": "Fallback-heavy pain-point evidence should remain weak.",
                    "blocked_by": "mostly fallback pain-point evidence",
                    "source_urls": ["https://fallback.example.com/docs"],
                    "competitor_prevalence": 4,
                    "funnel_importance": "medium",
                    "owned_gap_status": "not_evaluated_without_owned_gap",
                    "sample_confidence": "low",
                    "recommended_action_type": "address_repeated_pain_point",
                },
            ],
        }
    )


def report_data_with_saturated_cta_coverage():
    data = copy.deepcopy(sample_report_data())
    return generate_report.ReportData(
        **{
            **data.__dict__,
            "cta_coverage": [
                {
                    "competitor_name": "Acme Analytics",
                    "total_insight_pages": 10,
                    "pages_with_any_cta": 10,
                    "any_cta_coverage": 1.0,
                    "pages_with_conversion_cta": 10,
                    "conversion_cta_coverage": 1.0,
                    "pages_with_secondary_cta": 10,
                    "secondary_cta_coverage": 1.0,
                    "sample_confidence": "high",
                },
                {
                    "competitor_name": "Coverage Saturated Co",
                    "total_insight_pages": 8,
                    "pages_with_any_cta": 8,
                    "any_cta_coverage": 1.0,
                    "pages_with_conversion_cta": 8,
                    "conversion_cta_coverage": 1.0,
                    "pages_with_secondary_cta": 8,
                    "secondary_cta_coverage": 1.0,
                    "sample_confidence": "high",
                },
            ],
        }
    )


def report_data_with_low_quality_topic_strategy_rows():
    data = copy.deepcopy(sample_report_data())
    return generate_report.ReportData(
        **{
            **data.__dict__,
            "topic_coverage": [
                {
                    "competitor_name": "Acme Analytics",
                    "topic_label": "bounce / factory / demo aurora",
                    "document_count": 4,
                    "avg_probability": "0.821",
                    "funnel_stage": "MOFU",
                    "source_urls": ["https://example.com/topic-diagnostic"],
                },
                {
                    "competitor_name": "demo_owned",
                    "topic_label": "Topic 9 [low confidence]",
                    "document_count": 3,
                    "avg_probability": "0.512",
                    "funnel_stage": "TOFU",
                    "source_urls": ["https://demo_owned.example.com/blog"],
                },
            ],
            "topic_gaps": [
                {
                    "topic_label": "bounce / factory / demo aurora",
                    "topic_saturation": "low",
                    "competitor_assets_on_topic": 4,
                    "gap_reason": "missing_on_owned_site",
                },
                {
                    "topic_label": "Topic 9 [low confidence]",
                    "topic_saturation": "medium",
                    "competitor_assets_on_topic": 3,
                    "gap_reason": "missing_on_owned_site",
                },
            ],
            "opportunity_backlog": [
                {
                    "priority": "high",
                    "confidence": "high",
                    "evidence_strength": "multiple_competitor_sources",
                    "source_count": 3,
                    "related_topic": "bounce / factory / demo aurora",
                    "gap_reason": "missing_on_owned_site",
                    "competitor_evidence": "Competitors cover this noisy topic.",
                    "suggested_asset_type": "product",
                    "suggested_funnel_stage": "MOFU",
                    "suggested_cta": "view pricing",
                    "why_now": "Noisy topic labels should not create strategy.",
                    "blocked_by": "none",
                    "source_urls": ["https://example.com/topic-diagnostic"],
                    "competitor_prevalence": 3,
                    "funnel_importance": "medium",
                    "owned_gap_status": "missing_on_owned_site",
                    "sample_confidence": "high",
                    "recommended_action_type": "fill_owned_topic_gap",
                },
                {
                    "priority": "medium",
                    "confidence": "medium",
                    "evidence_strength": "multiple_competitor_sources",
                    "source_count": 2,
                    "related_topic": "Topic 9 [low confidence]",
                    "gap_reason": "missing_on_owned_site",
                    "competitor_evidence": "Competitors cover this low-confidence topic.",
                    "suggested_asset_type": "guide",
                    "suggested_funnel_stage": "TOFU",
                    "suggested_cta": "download guide",
                    "why_now": "Low-confidence topic labels should not create strategy.",
                    "blocked_by": "none",
                    "source_urls": ["https://demo_owned.example.com/blog"],
                    "competitor_prevalence": 2,
                    "funnel_importance": "low",
                    "owned_gap_status": "missing_on_owned_site",
                    "sample_confidence": "medium",
                    "recommended_action_type": "fill_owned_topic_gap",
                },
            ],
            "data_quality": {
                **data.data_quality,
                "owned_domain_configured": True,
            },
        }
    )


class FakeConnection:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False


class FakeEngine:
    def connect(self):
        return FakeConnection()


def test_parse_args_defaults_and_date_validation():
    args = generate_report.parse_args([])

    assert args.output_dir == generate_report.DEFAULT_OUTPUT_DIR
    assert args.use_llm_summary is False
    assert isinstance(args.date, date)

    assert generate_report.parse_args(["--date", "2026-04-27"]).date == date(2026, 4, 27)

    with pytest.raises(SystemExit):
        generate_report.parse_args(["--date", "04/27/2026"])


def test_render_markdown_table_escapes_pipes_and_newlines():
    markdown = generate_report.render_markdown_table(
        ["Name", "Value"],
        [["Acme|Beta", "Line one\nLine two"]],
    )

    assert "Acme\\|Beta" in markdown
    assert "Line one Line two" in markdown
    assert "| Name | Value |" in markdown


def test_clean_value_repairs_common_mojibake():
    assert (
        generate_report.clean_value("Monthly Access (\u00e2\u201a\u00ac18/month)")
        == "Monthly Access (\u20ac18/month)"
    )
    assert (
        generate_report.clean_value("Supportive \u00e2\u20ac\u201c practical")
        == "Supportive - practical"
    )


def test_clean_value_normalizes_report_punctuation_to_ascii():
    assert generate_report.clean_value(AUDITED_MOJIBAKE_TITLE) == NORMALIZED_AUDITED_TITLE
    assert (
        generate_report.clean_value(DOUBLE_ENCODED_MOJIBAKE_TITLE)
        == NORMALIZED_AUDITED_TITLE
    )
    assert (
        generate_report.clean_value("Smart \u201cquotes\u201d and\u00a0spacing")
        == 'Smart "quotes" and spacing'
    )


def test_render_markdown_table_cleans_audited_mojibake_title():
    markdown = generate_report.render_markdown_table(
        ["Title"],
        [[AUDITED_MOJIBAKE_TITLE]],
    )

    assert AUDITED_MOJIBAKE_TITLE not in markdown
    assert "Page not found - fMusic Docs \\| demo_owned AI" in markdown
    assert "\u00c3" not in markdown
    assert "\u00e2" not in markdown


def test_render_report_cleans_audited_mojibake_title():
    data = sample_report_data()
    data = generate_report.ReportData(
        **{
            **data.__dict__,
            "data_quality_issues": [
                {
                    **data.data_quality_issues[0],
                    "title": AUDITED_MOJIBAKE_TITLE,
                }
            ],
        }
    )

    markdown = generate_report.render_report(data)

    assert AUDITED_MOJIBAKE_TITLE not in markdown
    assert "Page not found - fMusic Docs \\| demo_owned AI" in markdown
    for marker in ["\u00c3", "\u00e2", "\ufffd"]:
        assert marker not in markdown


def test_sanitize_market_language_softens_unsupported_claims():
    assert (
        generate_report.sanitize_market_language("Acme has 40% market share.")
        == "Acme has the largest crawled word share in the selected URL dataset."
    )
    assert (
        generate_report.sanitize_market_language("Acme is the market leader.")
        == "Acme appears most visible in this dataset."
    )
    assert (
        generate_report.sanitize_market_language("The market is growing at 12% annually.")
        == "growth rate was not measured in this MVP."
    )
    assert (
        generate_report.sanitize_market_language("demo_owned AI positions itself as a leader in audio workflow automation.")
        == "demo_owned AI positions itself as highly visible in the crawled dataset in audio workflow automation."
    )


def test_sanitize_llm_executive_summary_removes_risky_proxy_language_and_typos():
    summary = (
        "BounFactory has strong share of voice and market presence. "
        "It dominates the crawled word share proxy and has presence in the market. "
        "It is the market leader. All crawled pages validated successfully. "
        "Insights extracted from a total of 2 raw pages. "
        "Dataset integrity is affirmed and content engagement shows competitive standing."
    )

    sanitized = generate_report.sanitize_llm_executive_summary(summary, sample_report_data())

    assert "BounFactory" not in sanitized
    assert "demo-aurora" in sanitized
    assert "share of voice" not in sanitized.lower()
    assert "crawled word share proxy" in sanitized.lower()
    assert "market presence" not in sanitized.lower()
    assert "presence in the market" not in sanitized.lower()
    assert "dominates" not in sanitized.lower()
    assert "market leader" not in sanitized.lower()
    assert "all crawled pages validated successfully" not in sanitized.lower()
    assert "invalid or non-evaluable pages are listed as data quality issues" in sanitized.lower()
    assert "insights extracted from a total of 2 raw pages" not in sanitized.lower()
    assert "1 extracted insight records from 2 raw pages" in sanitized
    assert "dataset integrity is affirmed" not in sanitized.lower()
    assert "content engagement" not in sanitized.lower()
    assert "competitive standing" not in sanitized.lower()
    assert "dataset reliability is summarized in the data quality sections" in sanitized.lower()
    assert "crawled content volume" in sanitized.lower()
    assert "content planning" in sanitized.lower()


def test_render_report_includes_required_sections_and_methodology_note():
    markdown = generate_report.render_report(sample_report_data())

    for heading in [
        "# Competitor Content Intelligence Report",
        "## 1. Executive Summary",
        "## 2. Dataset Scope",
        "## 3. Data Quality Issues",
        "## 4. Content Inventory",
        "## 5. Topic Diagnostics & Gaps",
        "## 6. Messaging & Positioning",
        "## 7. Funnel & CTA Intelligence",
        "## 8. Content Quality Analysis",
        "## 9. Competitor Scorecards",
        "## 10. Opportunity Backlog",
        "## 11. Competitive Observations",
        "## 12. Unavailable Analyses",
        "## 13. Data Quality Notes",
        "## 14. Recommended Next Actions",
    ]:
        assert heading in markdown

    assert "This report is based on crawled public content" in markdown
    assert "does not estimate true market share" in markdown
    assert "corpus-based proxy metrics" in markdown
    assert "Crawled Word Share Proxy" in markdown
    assert "Share of Voice Proxy" not in markdown
    assert (
        "This is the share of technically successful crawled words in the selected URL dataset, "
        "not market share or brand demand."
    ) in markdown
    assert "https://example.com/pricing" in markdown
    assert "| Competitor | Website | Category |" in markdown
    assert "Successful Pages" not in markdown
    assert "successful crawled page(s)" not in markdown


def test_render_dataset_scope_distinguishes_crawled_ok_from_valid_assets():
    section = generate_report.render_dataset_scope(sample_report_data())

    assert (
        "| Competitor | Website | Category | Country | Configured URLs | Pages Crawled | "
        "Crawled OK | Valid Assets | Invalid / Non-Evaluable | Raw Insights | "
        "Valid Insights | Invalid Insights |"
    ) in section
    assert (
        "| Source Type | Pages Crawled | Crawled OK | Valid Assets | "
        "Invalid / Non-Evaluable | Raw Insights | Valid Insights | Invalid Insights |"
    ) in section
    assert "| demo_owned | https://www.demo_owned.com/ | Audio AI | Italy | 6 | 6 | 6 | 2 | 4 | 2 | 2 | 0 |" in section
    assert "| docs | 4 | 4 | 0 | 4 | 0 | 0 | 0 |" in section
    assert "Successful Pages" not in section


def test_render_report_places_data_quality_issues_before_content_inventory():
    markdown = generate_report.render_report(sample_report_data())

    assert markdown.index("## 3. Data Quality Issues") < markdown.index(
        "## 4. Content Inventory"
    )
    assert "These are crawl/input quality issues" in markdown
    assert "They are not competitor weaknesses" in markdown
    assert "| Competitor | Source Type | URL | Title | Words | Issue | Action |" in markdown
    assert "https://www.demo_owned.com/user-stories" in markdown
    assert "Workhorse - Webflow HTML Website Template" in markdown
    assert "too little crawled content" in markdown
    assert "review page selection" in markdown


def test_invalid_pages_can_appear_in_data_quality_diagnostics():
    section = generate_report.render_data_quality_issues(
        report_data_with_invalid_sentinel_in_strategic_inputs()
    )

    assert INVALID_SENTINEL_URL in section
    assert INVALID_SENTINEL_TITLE in section
    assert "template or placeholder page" in section


def test_render_content_messaging_labels_insight_pages():
    section = generate_report.render_content_messaging(sample_report_data())

    assert "| Competitor | Insight Pages | Pillars |" in section
    assert "| Competitor | Pages | Pillars |" not in section


def test_main_report_messaging_matrix_does_not_render_tone_as_kpi():
    section = generate_report.render_content_messaging(sample_report_data())

    assert "Messaging matrix:" in section
    assert "Tone" not in section
    assert "practical" not in section


def test_main_report_competitor_summary_does_not_render_sentiment_share_kpis():
    section = generate_report.render_competitor_overview(sample_report_data())

    assert "Positive Share" not in section
    assert "Negative Share" not in section
    assert "| Acme Analytics | 2 | 1,200 | 1 | 800 | 100.0% | 1 | 3 |" in section


def test_main_report_does_not_render_cta_coverage_as_headline_kpi():
    section = generate_report.render_funnel_and_cta(sample_report_data())

    assert "Funnel stage mix:" in section
    assert "CTA coverage by competitor:" not in section
    assert "Any CTA Coverage" not in section
    assert "Conversion CTA Coverage" not in section
    assert "Pages With Any CTA" not in section
    assert "Pages With Conversion CTA" not in section


def test_main_report_keeps_cta_raw_details_out_of_headline_kpis():
    data = report_data_with_saturated_cta_coverage()
    markdown = generate_report.render_report(data)

    assert data.cta_coverage
    assert data.cta_coverage[0]["any_cta_coverage"] == 1.0
    assert data.cta_coverage[0]["conversion_cta_coverage"] == 1.0
    assert "## 7. Funnel & CTA Intelligence" in markdown
    assert "CTA class mix diagnostics:" in markdown
    assert "CTA coverage by competitor:" not in markdown
    assert "Any CTA Coverage" not in markdown
    assert "Conversion CTA Coverage" not in markdown
    assert "Coverage Saturated Co" not in markdown


def test_content_quality_does_not_depend_on_competitor_cta_coverage_percentage():
    baseline = generate_report.render_content_quality(sample_report_data())
    saturated = generate_report.render_content_quality(
        report_data_with_saturated_cta_coverage()
    )

    assert baseline == saturated
    assert "CTA Alignment" in saturated
    assert "CTA Coverage" not in saturated
    assert "Any CTA Coverage" not in saturated
    assert "Conversion CTA Coverage" not in saturated
    assert "CTA contribution capped: only secondary CTAs were found" in saturated


def test_crawled_word_share_is_labeled_as_diagnostics_not_competitive_strength():
    section = generate_report.render_content_inventory(sample_report_data())

    assert "Dataset diagnostics:" in section
    assert "Corpus balance:" in section
    assert "Crawled word share:" not in section
    assert "competitive strength" not in section.lower()


def test_topic_coverage_does_not_feed_strategic_opportunities_or_observations():
    markdown = generate_report.render_report(sample_report_data())

    assert "Topic coverage as competitive observation:" not in markdown
    assert "| topic coverage |" not in markdown
    assert "| weak competitor page | Acme Analytics | product | 1 | quality | low | 43.0 | https://example.com/learn-more |" in markdown


def test_invalid_topic_documents_do_not_render_in_main_topic_diagnostics():
    section = generate_report.render_topic_coverage_and_gaps(
        report_data_with_invalid_sentinel_in_strategic_inputs()
    )

    assert "Topic model diagnostics:" in section
    assert INVALID_SENTINEL_URL not in section, (
        "invalid topic document leaked into main report topic diagnostics"
    )
    assert "placeholder / template" not in section, (
        "invalid topic label leaked into main report topic diagnostics"
    )


def test_invalid_pages_do_not_render_as_strategic_opportunities():
    section = generate_report.render_opportunity_backlog(
        report_data_with_invalid_sentinel_in_strategic_inputs()
    )

    assert INVALID_SENTINEL_URL not in section, (
        "invalid asset source URL leaked into strategic opportunity backlog"
    )
    assert "InvalidCo placeholder page" not in section, (
        "invalid asset evidence leaked into strategic opportunity backlog"
    )
    assert "placeholder template" not in section, (
        "invalid asset topic leaked into strategic opportunity backlog"
    )


def test_invalid_pages_do_not_render_as_competitive_observation_signals():
    section = generate_report.render_competitive_observations(
        report_data_with_invalid_sentinel_in_strategic_inputs()
    )

    assert INVALID_SENTINEL_URL not in section, (
        "invalid page leaked into weak/best competitor page observations"
    )
    assert INVALID_SENTINEL_TITLE not in section, (
        "invalid page title leaked into weak/best competitor page observations"
    )


def test_render_topic_gaps_shows_unavailable_note_without_owned_domain():
    section = generate_report.render_topic_coverage_and_gaps(sample_report_data())

    assert "Topic model diagnostics:" in section
    assert "Corpus topic coverage diagnostics:" in section
    assert "strategic opportunity sources" in section
    assert "| Acme Analytics | pricing / analytics | 1 | BOFU | 0.8 |" in section
    assert "Owned domain not configured; topic gap analysis is unavailable." in section
    assert "not_configured" not in section
    assert "| pricing / analytics | low | 1 | not_configured |" not in section


def test_render_topic_saturation_explains_minimum_distribution_requirement():
    data = sample_report_data()
    data = generate_report.ReportData(
        **{
            **data.__dict__,
            "topic_coverage": [
                {
                    "competitor_name": "Acme Analytics",
                    "topic_label": "pricing / analytics",
                    "controlled_topic_id": "pricing_strategy",
                    "controlled_topic_label": "Pricing Strategy",
                    "controlled_topic_confidence": "medium",
                    "controlled_topic_assignment_reason": "matched pricing evidence",
                    "document_count": 2,
                    "topic_saturation": "insufficient data",
                    "funnel_stage": "BOFU",
                    "source_urls": ["https://example.com/pricing"],
                }
            ],
            "data_quality": {
                **data.data_quality,
                "owned_domain_configured": True,
            },
        }
    )

    section = generate_report.render_topic_coverage_and_gaps(data)
    lower_section = section.lower()

    assert "| Acme Analytics | Pricing Strategy | medium | matched pricing evidence | 2 | insufficient data | BOFU |" in section
    assert "topic saturation" in lower_section
    assert "at least 3 documents" in lower_section or "minimum distribution" in lower_section
    assert "insufficient data" in lower_section


def test_render_topic_coverage_marks_audited_noisy_labels_low_confidence():
    data = sample_report_data()
    data = generate_report.ReportData(
        **{
            **data.__dict__,
            "topic_coverage": [
                {
                    "competitor_name": "Acme Analytics",
                    "topic_label": "bounce / factory / demo aurora",
                    "document_count": 4,
                    "avg_probability": "0.821",
                    "funnel_stage": "MOFU",
                    "source_urls": ["https://example.com/pricing"],
                }
            ],
        }
    )

    section = generate_report.render_topic_coverage_and_gaps(data)

    assert "bounce / factory / demo aurora [low confidence]" in section


def test_low_quality_topics_remain_visible_in_topic_diagnostics():
    section = generate_report.render_topic_coverage_and_gaps(
        report_data_with_low_quality_topic_strategy_rows()
    )

    assert "Topic model diagnostics:" in section
    assert "Corpus topic coverage diagnostics:" in section
    assert "bounce / factory / demo aurora [low confidence]" in section
    assert "Topic 9 [low confidence]" in section


def test_low_quality_topics_do_not_render_as_strategic_opportunities():
    section = generate_report.render_opportunity_backlog(
        report_data_with_low_quality_topic_strategy_rows()
    )

    assert "fill_owned_topic_gap" not in section
    assert "bounce / factory / demo aurora" not in section
    assert "Topic 9 [low confidence]" not in section
    assert "Noisy topic labels should not create strategy." not in section
    assert "Low-confidence topic labels should not create strategy." not in section


def test_controlled_topics_render_as_strategic_topics_instead_of_noisy_bertopic_labels():
    data = sample_report_data()
    data = generate_report.ReportData(
        **{
            **data.__dict__,
            "topic_coverage": [
                {
                    "competitor_name": "Acme Analytics",
                    "topic_label": "download / audio / tracks",
                    "controlled_topic_id": "bounce_automation",
                    "controlled_topic_label": "Bounce Automation",
                    "controlled_topic_confidence": "medium",
                    "controlled_topic_assignment_reason": "matched bounce/export evidence",
                    "document_count": 4,
                    "avg_probability": "0.812",
                    "funnel_stage": "MOFU",
                    "source_urls": ["https://example.com/bounce"],
                }
            ],
            "data_quality": {
                **data.data_quality,
                "owned_domain_configured": True,
            },
        }
    )

    section = generate_report.render_topic_coverage_and_gaps(data)

    assert "Bounce Automation" in section
    strategic_section = section.split("Strategic controlled topic coverage:", 1)[1]
    strategic_section = strategic_section.split("Corpus topic coverage diagnostics:", 1)[0]
    assert "download / audio / tracks" not in strategic_section


def test_bertopic_noisy_labels_remain_visible_only_as_diagnostics():
    data = sample_report_data()
    data = generate_report.ReportData(
        **{
            **data.__dict__,
            "topic_coverage": [
                {
                    "competitor_name": "Acme Analytics",
                    "topic_label": "download / audio / tracks",
                    "controlled_topic_id": "bounce_automation",
                    "controlled_topic_label": "Bounce Automation",
                    "controlled_topic_confidence": "medium",
                    "controlled_topic_assignment_reason": "matched bounce/export evidence",
                    "document_count": 4,
                    "avg_probability": "0.812",
                    "funnel_stage": "MOFU",
                    "source_urls": ["https://example.com/bounce"],
                }
            ],
            "data_quality": {
                **data.data_quality,
                "owned_domain_configured": True,
            },
        }
    )

    section = generate_report.render_topic_coverage_and_gaps(data)

    assert "Topic model diagnostics:" in section
    diagnostics_section = section.split("Corpus topic coverage diagnostics:", 1)[1]
    assert "download / audio / tracks" in diagnostics_section


def test_controlled_topic_gap_renders_directional_when_demo_owned_owned_sample_is_low():
    data = sample_report_data()
    data = generate_report.ReportData(
        **{
            **data.__dict__,
            "topic_gaps": [
                {
                    "topic_label": "download / audio / tracks",
                    "controlled_topic_id": "bounce_automation",
                    "controlled_topic_label": "Bounce Automation",
                    "controlled_topic_confidence": "medium",
                    "topic_saturation": "medium",
                    "competitor_assets_on_topic": 3,
                    "gap_reason": "missing_on_owned_site",
                    "gap_analysis_status": "directional_only",
                    "gap_analysis_reason": (
                        "owned domain has low sample confidence: only 2 valid assets"
                    ),
                }
            ],
            "data_quality": {
                **data.data_quality,
                "owned_domain_configured": True,
            },
        }
    )

    section = generate_report.render_topic_coverage_and_gaps(data)

    assert "Bounce Automation" in section
    assert "directional only" in section
    assert "owned domain has low sample confidence" in section
    controlled_gap_section = section.split("Controlled topic gap analysis:", 1)[1]
    assert "download / audio / tracks" not in controlled_gap_section


def test_low_quality_topics_do_not_render_as_competitive_observations():
    markdown = generate_report.render_report(report_data_with_low_quality_topic_strategy_rows())

    observations = markdown.split("## 11. Competitive Observations", 1)[1]
    observations = observations.split("## 12. Unavailable Analyses", 1)[0]

    assert "| topic coverage |" not in observations
    assert "bounce / factory / demo aurora" not in observations
    assert "Topic 9 [low confidence]" not in observations


def test_render_topic_gaps_shows_operational_table_when_owned_domain_configured():
    data = sample_report_data()
    data = generate_report.ReportData(
        **{
            **data.__dict__,
            "topic_gaps": [
                {
                    "topic_label": "pricing / analytics",
                    "topic_saturation": "medium",
                    "competitor_assets_on_topic": 3,
                    "gap_reason": "missing_on_owned_site",
                }
            ],
            "data_quality": {
                **data.data_quality,
                "owned_domain_configured": True,
            },
        }
    )

    section = generate_report.render_topic_coverage_and_gaps(data)

    assert "Owned domain not configured; topic gap analysis is unavailable." not in section
    assert "| pricing / analytics | medium | 3 | missing_on_owned_site |" in section


def test_render_topic_gaps_shows_directional_status_for_low_sample_owned_domain():
    data = sample_report_data()
    data = generate_report.ReportData(
        **{
            **data.__dict__,
            "topic_gaps": [
                {
                    "topic_label": "pricing / analytics",
                    "topic_saturation": "medium",
                    "competitor_assets_on_topic": 3,
                    "gap_reason": "missing_on_owned_site",
                    "gap_analysis_status": "directional_only",
                    "gap_analysis_reason": (
                        "owned domain has low sample confidence: only 2 valid assets"
                    ),
                }
            ],
            "data_quality": {
                **data.data_quality,
                "owned_domain_configured": True,
            },
        }
    )

    section = generate_report.render_topic_coverage_and_gaps(data)

    assert "directional only" in section
    assert "owned domain has low sample confidence" in section


def test_owned_low_sample_gap_section_has_directional_status_header():
    section = generate_report.render_topic_coverage_and_gaps(
        report_data_with_low_sample_display_gating_risks()
    )

    assert "Section status: directional only" in section
    assert "Reason: owned domain has low sample confidence" in section


def test_owned_low_sample_gap_section_is_directional_even_without_gap_rows():
    data = sample_report_data()
    data = generate_report.ReportData(
        **{
            **data.__dict__,
            "dataset_scope": [
                {
                    "competitor": "demo_owned",
                    "is_owned_domain": True,
                    "valid_assets": 2,
                }
            ],
            "topic_gaps": [],
            "data_quality": {
                **data.data_quality,
                "owned_domain_configured": True,
            },
        }
    )

    section = generate_report.render_topic_coverage_and_gaps(data)

    assert "Section status: directional only" in section
    assert "Reason: owned domain has low sample confidence: 2 valid assets" in section
    assert "Section status: fully comparable" not in section


def test_owned_domain_gap_section_without_evaluable_rows_is_not_evaluable():
    data = sample_report_data()
    data = generate_report.ReportData(
        **{
            **data.__dict__,
            "topic_gaps": [],
            "data_quality": {
                **data.data_quality,
                "owned_domain_configured": True,
            },
        }
    )

    section = generate_report.render_topic_coverage_and_gaps(data)
    controlled_gap_section = section.split("Controlled topic gap analysis:", 1)[1]

    assert "Section status: not evaluable" in controlled_gap_section
    assert "Reason:" in controlled_gap_section
    assert "not enough data" in controlled_gap_section.lower()
    assert "Section status: fully comparable" not in controlled_gap_section


def test_render_opportunity_backlog_filters_not_configured_rows():
    section = generate_report.render_opportunity_backlog(sample_report_data())

    assert "not_configured" not in section
    assert "missing owned-domain context" not in section
    assert "https://example.com/pricing" in section
    assert (
        "| Priority | Confidence | Evidence Strength | Evidence Mix | "
        "Weighted Evidence | Dominant Evidence | Fallback Share | Source Count | "
        "Competitor Prevalence | Funnel Importance | Owned Gap Status |"
    ) in section
    assert "Action Type" in section
    assert "exploit_repeated_competitor_weakness" in section


def test_render_opportunity_backlog_shows_directional_owned_gap_confidence_cap():
    data = sample_report_data()
    data = generate_report.ReportData(
        **{
            **data.__dict__,
            "opportunity_backlog": [
                {
                    "priority": "medium",
                    "confidence": "medium",
                    "evidence_strength": "multiple_competitor_sources",
                    "source_count": 3,
                    "related_topic": "pricing / analytics",
                    "gap_reason": "missing_on_owned_site",
                    "suggested_asset_type": "comparison",
                    "suggested_funnel_stage": "BOFU",
                    "suggested_cta": "book demo",
                    "why_now": "Owned-domain gap is directional because owned sample is low.",
                    "blocked_by": "owned domain has low sample confidence",
                    "source_urls": ["https://competitor.example/pricing"],
                    "competitor_prevalence": 3,
                    "funnel_importance": "high",
                    "owned_gap_status": "directional_only",
                    "gap_analysis_status": "directional_only",
                    "sample_confidence": "medium",
                    "recommended_action_type": "fill_owned_topic_gap",
                    "topic_saturation": "medium",
                }
            ],
            "data_quality": {
                **data.data_quality,
                "owned_domain_configured": True,
            },
        }
    )

    section = generate_report.render_opportunity_backlog(data)

    assert "| medium | medium | multiple_competitor_sources |" in section
    assert "directional only" in section
    assert "| high | high | multiple_competitor_sources |" not in section


def test_opportunity_backlog_owned_gap_not_evaluated_prevents_fully_comparable_status():
    section = generate_report.render_opportunity_backlog(sample_report_data())
    status_block = section.split("| Priority |", 1)[0]

    assert "not evaluated" in section or "not_evaluated_without_owned_gap" in section
    assert "Section status: fully comparable" not in status_block
    assert "Section status: directional only" in status_block
    assert "Reason:" in status_block
    assert "owned" in status_block.lower()


def test_opportunity_backlog_low_confidence_row_makes_section_directional():
    data = sample_report_data()
    data = generate_report.ReportData(
        **{
            **data.__dict__,
            "opportunity_backlog": [
                {
                    "priority": "medium",
                    "confidence": "low",
                    "evidence_strength": "repeated_competitor_weakness",
                    "source_count": 2,
                    "related_topic": "pricing",
                    "gap_reason": "repeated_weak_content_quality",
                    "suggested_asset_type": "pricing",
                    "suggested_funnel_stage": "BOFU",
                    "suggested_cta": "start trial",
                    "why_now": "Repeated weak competitor pages point to a strategic content gap.",
                    "blocked_by": "weak sample: only two competitor sources",
                    "source_urls": ["https://example.com/pricing"],
                    "competitor_prevalence": 2,
                    "funnel_importance": "high",
                    "owned_gap_status": "not_evaluated_without_owned_gap",
                    "gap_analysis_status": "not_evaluated_without_owned_gap",
                    "gap_analysis_reason": "owned-domain comparison is not part of this evidence cluster",
                    "sample_confidence": "low",
                    "recommended_action_type": "exploit_repeated_competitor_weakness",
                }
            ],
        }
    )

    section = generate_report.render_opportunity_backlog(data)
    status_block = section.split("| Priority |", 1)[0]

    assert "Section status: directional only" in status_block
    assert "Reason:" in status_block
    assert (
        "weak sample" in status_block
        or "low" in status_block.lower()
        or "owned-domain comparison" in status_block
    )
    assert "Section status: fully comparable" not in status_block


def test_opportunity_backlog_without_evaluable_rows_has_not_evaluable_section_status():
    data = sample_report_data()
    data = generate_report.ReportData(
        **{
            **data.__dict__,
            "opportunity_backlog": [
                {
                    "priority": "not_evaluable",
                    "confidence": "low",
                    "evidence_strength": "missing_source",
                    "source_count": 0,
                    "related_topic": "Topic 9 [low confidence]",
                    "gap_reason": "missing_asset_type",
                    "suggested_asset_type": "pricing",
                    "suggested_funnel_stage": "BOFU",
                    "suggested_cta": "book demo",
                    "why_now": "No usable source evidence.",
                    "blocked_by": "missing source evidence",
                    "source_urls": [],
                    "competitor_prevalence": 0,
                    "funnel_importance": "unknown",
                    "owned_gap_status": "blocked",
                    "gap_analysis_status": "blocked",
                    "gap_analysis_reason": "no relevant row has enough usable data",
                    "sample_confidence": "low",
                    "recommended_action_type": "blocked_analysis",
                }
            ],
        }
    )

    section = generate_report.render_opportunity_backlog(data)
    status_block = section.split("| Priority |", 1)[0]

    assert "Section status: not evaluable" in status_block
    assert "Reason:" in status_block
    assert "not enough data" in status_block.lower() or "no relevant row" in status_block.lower()
    assert "Section status: fully comparable" not in status_block


def test_owned_low_sample_gap_recommendations_cannot_be_high_confidence():
    section = generate_report.render_opportunity_backlog(
        report_data_with_low_sample_display_gating_risks()
    )

    assert "| high | high | multiple_competitor_sources |" not in section
    assert (
        "| medium | medium | multiple_competitor_sources |" in section
        or "directional only" in section.lower()
        or "| low | low | multiple_competitor_sources |" in section
    )
    assert "owned domain has low sample confidence" in section


def test_owned_domain_does_not_render_as_external_competitive_observation():
    data = sample_report_data()
    data = generate_report.ReportData(
        **{
            **data.__dict__,
            "content_quality": [
                {
                    **data.content_quality[1],
                    "competitor_name": "Owned Domain",
                    "url": "https://owned.example/weak-page",
                    "is_owned_domain": True,
                }
            ],
            "data_quality": {
                **data.data_quality,
                "owned_domain_configured": True,
            },
        }
    )

    section = generate_report.render_competitive_observations(data)

    assert "Owned Domain" not in section
    assert "https://owned.example/weak-page" not in section


def test_render_opportunity_backlog_filters_rows_without_source_urls():
    data = sample_report_data()
    data = generate_report.ReportData(
        **{
            **data.__dict__,
            "opportunity_backlog": [
                {
                    "priority": "medium",
                    "confidence": "low",
                    "evidence_strength": "missing_source",
                    "source_count": 0,
                    "related_topic": "pricing",
                    "gap_reason": "missing_asset_type",
                    "suggested_asset_type": "pricing",
                    "suggested_funnel_stage": "BOFU",
                    "suggested_cta": "book demo",
                    "why_now": "Missing configured page type.",
                    "blocked_by": "missing source evidence",
                    "source_urls": [],
                    "competitor_prevalence": 0,
                    "funnel_importance": "unknown",
                    "owned_gap_status": "blocked",
                    "sample_confidence": "low",
                    "recommended_action_type": "blocked_analysis",
                }
            ],
        }
    )

    section = generate_report.render_opportunity_backlog(data)

    assert generate_report.NOT_ENOUGH_DATA in section
    assert "missing_asset_type" not in section


def test_render_opportunity_backlog_shows_pain_point_evidence_mix_and_strength():
    section = generate_report.render_opportunity_backlog(
        report_data_with_pain_point_opportunity_evidence_mix()
    )

    assert "Evidence Mix" in section
    assert "Weighted Evidence" in section
    assert "Dominant Evidence" in section
    assert "Fallback Share" in section
    assert "explicit=3; inferred_from_benefit=1; keyword_fallback=0" in section
    assert "explicit_heavy_pain_point" in section
    assert "fallback_heavy_pain_point" in section


def test_render_opportunity_backlog_keeps_source_urls_with_pain_point_evidence_mix():
    section = generate_report.render_opportunity_backlog(
        report_data_with_pain_point_opportunity_evidence_mix()
    )

    assert "https://example.com/home" in section
    assert "https://competitor.example.com/pricing" in section
    assert "https://fallback.example.com/docs" in section
    assert "explicit=0; inferred_from_benefit=1; keyword_fallback=5" in section


def test_render_opportunity_backlog_downgrades_fallback_heavy_pain_point_confidence():
    section = generate_report.render_opportunity_backlog(
        report_data_with_pain_point_opportunity_evidence_mix()
    )

    assert (
        "| low | low | fallback_heavy_pain_point | "
        "explicit=0; inferred_from_benefit=1; keyword_fallback=5 |"
    ) in section
    assert (
        "| high | high | explicit_heavy_pain_point | "
        "explicit=3; inferred_from_benefit=1; keyword_fallback=0 |"
    ) in section


def test_render_report_separates_observations_and_unavailable_analyses():
    markdown = generate_report.render_report(sample_report_data())

    assert "## 10. Opportunity Backlog" in markdown
    assert "## 11. Competitive Observations" in markdown
    assert "## 12. Unavailable Analyses" in markdown
    assert "| topic coverage |" not in markdown
    assert "| weak competitor page | Acme Analytics | product | 1 | quality | low | 43.0 | https://example.com/learn-more |" in markdown
    assert "| topic gap analysis | not_evaluable | missing owned-domain context |" in markdown
    assert "Owned-domain context is missing." in markdown


def test_render_content_messaging_shows_proof_type_breakdown():
    section = generate_report.render_content_messaging(sample_report_data())

    assert "Proof type breakdown:" in section
    assert (
        "| Competitor | Extracted Type | Normalized Type | Extracted Strength | "
        "Normalized Strength | Reason | Mentions | Share |"
    ) in section
    assert "| Acme Analytics | statistic | metric | high | high | mapped extracted proof type to controlled taxonomy | 1 | 50.0% |" in section
    assert "| Acme Analytics | generic_claim | generic_claim | high | low | downgraded commercial or generic proof from extracted high strength | 1 | 50.0% |" in section
    assert "| Acme Analytics | generic_claim | generic_claim | high | high |" not in section


def test_render_content_messaging_shows_pain_point_evidence_breakdown():
    section = generate_report.render_content_messaging(sample_report_data())

    assert "Pain point evidence breakdown:" in section
    assert "| Competitor | Category | Evidence Type | Mentions | Pain Points | Source URLs |" in section
    assert "| Acme Analytics | manual work | keyword_fallback | 1 | manual exports | https://example.com/home |" in section
    assert "| Acme Analytics | time cost | inferred_from_benefit | 1 | slow reporting | https://example.com/pricing |" in section


def test_render_content_messaging_keeps_legacy_and_structured_pain_points_readable():
    section = generate_report.render_content_messaging(sample_report_data())

    assert "slow reporting, manual exports" in section
    assert "pain_point_text" not in section


def test_render_content_messaging_keeps_legacy_proof_strings_readable():
    section = generate_report.render_content_messaging(sample_report_data())

    assert "setup in minutes" in section


def test_render_data_quality_issues_empty_state_is_concise():
    data = sample_report_data()
    data = generate_report.ReportData(
        **{
            **data.__dict__,
            "data_quality_issues": [],
        }
    )

    section = generate_report.render_data_quality_issues(data)

    assert "No data quality issues detected." in section
    assert "These are crawl/input quality issues" in section
    assert "| Competitor | Source Type |" not in section


def test_fetch_report_data_uses_preaggregated_dataset_scope_query():
    source = (REPO_ROOT / "scripts" / "05_generate_report.py").read_text(
        encoding="utf-8"
    )

    assert "WITH source_counts AS" in source
    assert "raw_counts AS" in source
    assert "insight_counts AS" in source
    assert "COUNT(DISTINCT su.id) AS configured_urls" not in source


def test_report_data_has_data_quality_issues_field():
    field_names = {field.name for field in fields(generate_report.ReportData)}

    assert "data_quality_issues" in field_names


def test_report_data_has_split_cta_fields():
    field_names = {field.name for field in fields(generate_report.ReportData)}

    assert "cta_coverage" in field_names
    assert "cta_type_mix" in field_names
    assert "cta_intelligence" not in field_names


def test_report_data_has_proof_type_mix_field():
    field_names = {field.name for field in fields(generate_report.ReportData)}

    assert "proof_type_mix" in field_names


def test_fetch_report_data_queries_data_quality_issues_view():
    source = (REPO_ROOT / "scripts" / "05_generate_report.py").read_text(
        encoding="utf-8"
    )

    assert "v_data_quality_issues" in source


def test_fetch_report_data_queries_split_cta_views():
    source = (REPO_ROOT / "scripts" / "05_generate_report.py").read_text(
        encoding="utf-8"
    )

    assert "v_cta_coverage_by_competitor" in source
    assert "v_cta_type_mix_by_competitor" in source
    assert "any_cta_coverage" in source
    assert "conversion_cta_coverage" in source
    assert "secondary_cta_coverage" in source
    assert "FROM v_cta_intelligence" not in source


def test_fetch_report_data_queries_competitor_scorecards_view():
    source = (REPO_ROOT / "scripts" / "05_generate_report.py").read_text(
        encoding="utf-8"
    )

    assert "FROM v_competitor_scorecards" in source
    assert "LEFT JOIN v_content_depth_by_competitor cd" not in source
    assert "LEFT JOIN v_proof_density proof" not in source


def test_fetch_report_data_queries_weighted_proof_validation_fields():
    source = (REPO_ROOT / "scripts" / "05_generate_report.py").read_text(
        encoding="utf-8"
    )
    scorecard_query = source[source.index("FROM v_competitor_scorecards") - 700 :]

    for field_name in [
        "weighted_proof_points_validation_status",
        "weighted_proof_points_validation_reason",
        "weighted_proof_points_max_plausible",
    ]:
        assert field_name in scorecard_query


def test_fetch_report_data_queries_quality_cap_explainability_fields():
    source = (REPO_ROOT / "scripts" / "05_generate_report.py").read_text(
        encoding="utf-8"
    )
    content_quality_query = source[source.index("FROM v_content_quality") - 450 :]

    for field_name in [
        "quality_score",
        "quality_confidence",
        "quality_evidence_strength",
        "quality_reason",
    ]:
        assert field_name in content_quality_query


def test_fetch_report_data_queries_proof_type_mix_view():
    source = (REPO_ROOT / "scripts" / "05_generate_report.py").read_text(
        encoding="utf-8"
    )

    assert "FROM v_proof_type_mix_by_competitor" in source
    assert "extracted_proof_type" in source
    assert "normalized_proof_type" in source
    assert "extracted_proof_strength" in source
    assert "normalized_proof_strength" in source
    assert "proof_normalization_reason" in source
    assert "CASE normalized_proof_strength" in source


def test_fetch_report_data_carries_owned_domain_configured_state():
    source = (REPO_ROOT / "scripts" / "05_generate_report.py").read_text(
        encoding="utf-8"
    )

    assert '"owned_domain_configured"' in source
    assert "SELECT EXISTS (SELECT 1 FROM competitors WHERE is_owned_domain = TRUE)" in source


def test_fetch_report_data_queries_opportunity_auditability_fields():
    source = (REPO_ROOT / "scripts" / "05_generate_report.py").read_text(
        encoding="utf-8"
    )

    opportunity_query = source[source.index("FROM v_opportunity_backlog") - 350 :]

    for field_name in [
        "evidence_strength",
        "competitor_prevalence",
        "funnel_importance",
        "owned_gap_status",
        "source_count",
        "confidence",
        "sample_confidence",
        "recommended_action_type",
        "why_now",
        "blocked_by",
    ]:
        assert field_name in opportunity_query


def test_fetch_report_data_queries_gap_analysis_status_fields():
    source = (REPO_ROOT / "scripts" / "05_generate_report.py").read_text(
        encoding="utf-8"
    )
    topic_gap_query = source[source.index("FROM v_topic_gap") - 300 :]
    opportunity_query = source[source.index("FROM v_opportunity_backlog") - 450 :]

    for field_name in [
        "gap_analysis_status",
        "gap_analysis_reason",
    ]:
        assert field_name in topic_gap_query
        assert field_name in opportunity_query


def test_fetch_report_data_queries_pain_point_opportunity_evidence_mix_fields():
    source = (REPO_ROOT / "scripts" / "05_generate_report.py").read_text(
        encoding="utf-8"
    )

    opportunity_query = source[source.index("FROM v_opportunity_backlog") - 500 :]

    for field_name in [
        "evidence_mix",
        "weighted_evidence_score",
        "dominant_evidence_type",
        "fallback_share",
    ]:
        assert field_name in opportunity_query, (
            "report fetch must carry pain point evidence mix fields so rendered "
            "opportunity rows do not hide fallback-heavy evidence"
        )


def test_render_funnel_and_cta_splits_coverage_from_type_mix():
    section = generate_report.render_funnel_and_cta(sample_report_data())

    assert "CTA coverage by competitor:" not in section
    assert "Any CTA Coverage" not in section
    assert "Conversion CTA Coverage" not in section
    assert "CTA class mix diagnostics:" in section
    assert "| Competitor | CTA Class | CTA Count | CTA Class Share |" in section
    assert "| Acme Analytics | primary | 1 | 100.0% |" in section
    assert "| Competitor | Pages With CTA | Pages | CTA Coverage | CTA Type | CTA Count |" not in section


def test_render_funnel_and_cta_allows_any_cta_saturation_without_conversion_saturation():
    section = generate_report.render_funnel_and_cta(sample_report_data())

    assert "Any CTA Coverage" not in section
    assert "Conversion CTA Coverage" not in section
    assert "| Acme Analytics | 2 | 2 | 100.0% | 1 | 50.0% |" not in section
    assert "Funnel stage mix:" in section


def test_render_content_quality_includes_explanations():
    section = generate_report.render_content_quality(sample_report_data())

    assert (
        "| Competitor | Type | URL | Quality | Quality Bucket | Asset Score Confidence | "
        "Evidence Strength | Asset Confidence Reason |"
    ) in section
    assert "Freshness is excluded from Quality Score when unavailable." in section
    assert "undated content and unavailable freshness" not in section
    assert "limiting asset score confidence" not in section
    assert "Asset Score Confidence" in section
    assert "Quality Confidence" not in section
    assert "| Acme Analytics | pricing | https://example.com/pricing | 76.0 | strong | medium | medium |" in section
    assert "| Acme Analytics | pricing | https://example.com/pricing | 74 |" not in section
    assert "unavailable |" in section


def test_render_content_quality_explains_low_proof_and_secondary_cta_caps():
    section = generate_report.render_content_quality(sample_report_data())

    assert "Evidence Strength" in section
    assert "proof contribution capped: normalized evidence is only low or generic" in section
    assert "CTA contribution capped: only secondary CTAs were found" in section
    assert "low depth limits asset score without high normalized evidence" in section
    assert "| Acme Analytics | product | https://example.com/learn-more | 43.0 | weak | low confidence | low |" in section
    assert "| Acme Analytics | product | https://example.com/learn-more | 43.0 | strong |" not in section


def test_render_content_quality_displays_null_quality_as_unavailable():
    data = sample_report_data()
    content_quality = [{**data.content_quality[0], "content_quality_score": None, "quality_bucket": "unavailable"}]
    data = generate_report.ReportData(
        **{
            **data.__dict__,
            "content_quality": content_quality,
        }
    )

    section = generate_report.render_content_quality(data)

    assert "| Acme Analytics | pricing | https://example.com/pricing | unavailable | unavailable |" in section
    assert "| Acme Analytics | pricing | https://example.com/pricing | 0 |" not in section


def test_render_content_quality_hides_unavailable_freshness_numeric_value():
    data = sample_report_data()
    content_quality = [
        {
            **data.content_quality[0],
            "asset_type": "homepage",
            "freshness_score": 45,
            "freshness_confidence": "unavailable",
            "content_quality_score": 72,
            "quality_bucket": "adequate",
            "quality_confidence": "medium",
            "score_confidence": "medium",
            "quality_reason": "freshness is diagnostic because date evidence is unavailable",
        }
    ]
    data = generate_report.ReportData(
        **{
            **data.__dict__,
            "content_quality": content_quality,
        }
    )

    section = generate_report.render_content_quality(data)

    assert "| Freshness | Freshness Confidence |" in section
    assert "unavailable" in section
    assert "N/A | unavailable" in section or "not available | unavailable" in section
    assert "45.0 | unavailable" not in section
    assert "| 45 | unavailable |" not in section


def test_render_report_unavailable_legend_distinguishes_metric_availability_states():
    markdown = generate_report.render_report(sample_report_data())
    lower_markdown = markdown.lower()

    assert "n/a" in lower_markdown
    assert "not measurable" in lower_markdown or "not available" in lower_markdown
    assert "measured" in lower_markdown
    assert "unavailable" in lower_markdown
    assert "not comparable" in lower_markdown
    assert "unreliable" in lower_markdown
    assert "directional" in lower_markdown


def test_low_confidence_top_asset_is_not_uncaveated_best_asset():
    section = generate_report.render_content_quality(
        report_data_with_low_sample_display_gating_risks()
    )
    lower_section = section.lower()

    assert "https://one-page.example.com/home" in section
    assert "low confidence" in lower_section
    assert "best asset" not in lower_section
    assert "top asset" not in lower_section


def test_render_competitor_scorecards_shows_confidence_and_valid_asset_denominator():
    section = generate_report.render_competitor_scorecards(sample_report_data())

    assert "| Competitor | Valid Assets | Insight Coverage | Sample Confidence | Sample Confidence Reason |" in section
    assert "| Competitor | Valid Assets | Insight Coverage | Score Confidence | Confidence Reason |" not in section
    assert "Proof Elements per Valid Asset" in section
    assert "Strong Proof per Valid Asset" in section
    assert "Weighted Proof Points per Valid Asset" in section
    assert "Proof Density" not in section
    assert (
        "| Acme Analytics | 2 | 100.0% | low / directional only | sample confidence low: "
        "fewer than 3 valid assets, even if extraction coverage is complete |"
    ) in section
    assert "| 0.5 | 0.2 | 13.5 |" in section


def test_render_competitor_scorecards_shows_weighted_proof_validation_status():
    data = sample_report_data()
    data = generate_report.ReportData(
        **{
            **data.__dict__,
            "competitor_scorecards": [
                {
                    **data.competitor_scorecards[0],
                    "weighted_proof_points_validation_status": "valid",
                    "weighted_proof_points_validation_reason": "within plausible range",
                    "weighted_proof_points_max_plausible": 54,
                }
            ],
        }
    )

    section = generate_report.render_competitor_scorecards(data)

    assert "Weighted Proof Validation" in section
    assert "Weighted Proof Validation Reason" in section
    assert "within plausible range" in section


def test_render_competitor_scorecards_flags_demo_owned_like_outlier_instead_of_normal_value():
    data = sample_report_data()
    data = generate_report.ReportData(
        **{
            **data.__dict__,
            "competitor_scorecards": [
                {
                    **data.competitor_scorecards[0],
                    "competitor_name": "demo_owned-like Outlier",
                    "valid_assets": 2,
                    "insight_pages": 2,
                    "insight_coverage": 1.0,
                    "proof_elements_count": 5,
                    "strong_proof_elements_count": 0,
                    "weighted_proof_points": 227,
                    "proof_elements_per_valid_asset": 2.5,
                    "strong_proof_elements_per_valid_asset": 0,
                    "weighted_proof_points_per_valid_asset": 113.5,
                    "weighted_proof_points_validation_status": "unreliable",
                    "weighted_proof_points_validation_reason": (
                        "out of range: weighted proof points per valid asset exceeds 100"
                    ),
                    "weighted_proof_points_max_plausible": 10,
                    "score_confidence": "low",
                    "confidence_reason": (
                        "sample confidence low: fewer than 3 valid assets, "
                        "even if extraction coverage is complete"
                    ),
                }
            ],
        }
    )

    section = generate_report.render_competitor_scorecards(data)

    assert "demo_owned-like Outlier" in section
    assert "unreliable" in section.lower()
    assert "out of range" in section.lower()
    assert "| 113.5 |" not in section


def test_render_competitor_scorecards_keeps_plausible_zero_strong_weighted_proof_visible():
    data = sample_report_data()
    data = generate_report.ReportData(
        **{
            **data.__dict__,
            "competitor_scorecards": [
                {
                    **data.competitor_scorecards[0],
                    "competitor_name": "Plausible Weak Proof",
                    "valid_assets": 3,
                    "insight_pages": 3,
                    "insight_coverage": 1.0,
                    "proof_elements_count": 3,
                    "strong_proof_elements_count": 0,
                    "weighted_proof_points": 6,
                    "proof_elements_per_valid_asset": 1,
                    "strong_proof_elements_per_valid_asset": 0,
                    "weighted_proof_points_per_valid_asset": 2,
                    "weighted_proof_points_validation_status": "valid",
                    "weighted_proof_points_validation_reason": (
                        "zero strong proof but weighted proof is plausible for weak evidence"
                    ),
                    "weighted_proof_points_max_plausible": 6,
                    "score_confidence": "medium",
                    "confidence_reason": (
                        "sample confidence medium: valid assets and extraction coverage are usable but limited"
                    ),
                }
            ],
        }
    )

    section = generate_report.render_competitor_scorecards(data)

    assert "Plausible Weak Proof" in section
    assert "zero strong proof but weighted proof is plausible" in section
    assert "| 1.0 | 0.0 | 2.0 |" in section


def test_render_competitor_scorecards_sorts_low_confidence_below_reliable_samples():
    data = sample_report_data()
    scorecards = [
        {
            "competitor_name": "One Page Winner",
            "valid_assets": 1,
            "insight_pages": 1,
            "insight_coverage": 1.0,
            "avg_content_quality_score": 98,
            "avg_content_depth_score": 90,
            "avg_metadata_completeness_score": 90,
            "avg_bofu_strength_score": 95,
            "proof_elements_count": 3,
            "strong_proof_elements_count": 0,
            "weighted_proof_points": 6,
            "proof_elements_per_valid_asset": 3,
            "strong_proof_elements_per_valid_asset": 0,
            "weighted_proof_points_per_valid_asset": 6,
            "score_confidence": "low",
            "confidence_reason": (
                "sample confidence low: fewer than 3 valid assets, "
                "even if extraction coverage is complete"
            ),
        },
        {
            "competitor_name": "Mature Sample",
            "valid_assets": 6,
            "insight_pages": 6,
            "insight_coverage": 1.0,
            "avg_content_quality_score": 72,
            "avg_content_depth_score": 70,
            "avg_metadata_completeness_score": 80,
            "avg_bofu_strength_score": 70,
            "proof_elements_count": 9,
            "strong_proof_elements_count": 6,
            "weighted_proof_points": 168,
            "proof_elements_per_valid_asset": 1.5,
            "strong_proof_elements_per_valid_asset": 1,
            "weighted_proof_points_per_valid_asset": 28,
            "score_confidence": "high",
            "confidence_reason": "sample confidence high: 5+ valid assets with 90 percent+ extraction coverage",
        },
    ]
    data = generate_report.ReportData(
        **{
            **data.__dict__,
            "competitor_scorecards": scorecards,
        }
    )

    section = generate_report.render_competitor_scorecards(data)

    assert section.index("Mature Sample") < section.index("One Page Winner")


def test_competitor_scorecards_label_low_sample_rows_directional_only():
    section = generate_report.render_competitor_scorecards(
        report_data_with_low_sample_display_gating_risks()
    )

    assert "One Page Winner" in section
    assert "directional only" in section.lower()
    assert (
        "| One Page Winner | 1 | 100.0% | low | sample confidence low:"
        not in section
    )


def test_executive_summary_does_not_name_low_sample_competitor_as_leader():
    summary = generate_report.build_executive_summary(
        report_data_with_low_sample_display_gating_risks()
    )
    lower_summary = summary.lower()

    assert "one page winner is the leader" not in lower_summary
    assert "one page winner is the winner" not in lower_summary
    assert "one page winner is the best" not in lower_summary
    if "One Page Winner" in summary:
        assert (
            "low sample confidence" in lower_summary
            or "directional only" in lower_summary
        )


def test_report_separates_sample_confidence_from_asset_score_confidence():
    data = sample_report_data()
    content_quality = [
        {
            **data.content_quality[0],
            "competitor_name": "Mature Sample",
            "url": "https://mature.example.com/blog/undated-release",
            "asset_type": "blog",
            "content_quality_score": 58,
            "quality_score": 58,
            "score_confidence": "medium",
            "quality_confidence": "medium",
            "quality_bucket": "adequate",
            "freshness_confidence": "unavailable",
            "quality_reason": "balanced active quality signals",
            "quality_warnings": ["undated_content"],
        }
    ]
    scorecards = [
        {
            **data.competitor_scorecards[0],
            "competitor_name": "Mature Sample",
            "valid_assets": 6,
            "insight_pages": 6,
            "insight_coverage": 1.0,
            "score_confidence": "high",
            "confidence_reason": (
                "sample confidence high: 5+ valid assets with 90 percent+ "
                "extraction coverage"
            ),
        }
    ]
    data = generate_report.ReportData(
        **{
            **data.__dict__,
            "content_quality": content_quality,
            "competitor_scorecards": scorecards,
        }
    )

    markdown = generate_report.render_report(data)
    lower_markdown = markdown.lower()

    assert "asset score confidence" in lower_markdown
    assert "sample confidence" in lower_markdown
    assert (
        "| Mature Sample | blog | https://mature.example.com/blog/undated-release | "
        "58.0 | adequate | medium |"
    ) in markdown
    assert (
        "| Mature Sample | 6 | 100.0% | high | sample confidence high: "
        "5+ valid assets with 90 percent+ extraction coverage |"
    ) in markdown
    assert "sample confidence is separate from asset score confidence" in lower_markdown
    assert "high sample confidence means high asset score confidence" not in lower_markdown
    assert "high sample confidence means high confidence in every asset score" not in lower_markdown


def test_render_report_does_not_claim_share_of_voice_is_true_market_share():
    markdown = generate_report.render_report(sample_report_data()).lower()

    assert "crawled word share proxy" in markdown
    assert "share of voice proxy" not in markdown
    assert "not market share" in markdown
    assert "not market share or brand demand" in markdown
    assert "true market share is not calculated" in markdown
    assert "100.0% market share" not in markdown
    assert "1.0 market share" not in markdown
    assert "winner" not in markdown


def test_empty_report_data_contains_not_enough_data_messages():
    report_date = date(2026, 4, 27)
    data = generate_report.ReportData(
        generated_date=report_date,
        kpi_selection=generate_report.KpiSelection(
            requested_date=report_date,
            selected_date=None,
        ),
        data_quality={
            "competitors": 0,
            "raw_pages": 0,
            "crawled_ok_pages": 0,
            "failed_pages": 0,
            "insights": 0,
            "topics": 0,
            "kpi_rows": 0,
        },
    )

    markdown = generate_report.render_report(data)

    assert "No competitors are available in PostgreSQL yet" in markdown
    assert generate_report.NOT_ENOUGH_DATA in markdown
    assert "No KPI snapshot is available yet" in markdown


def test_llm_summary_is_not_called_unless_flag_is_set(monkeypatch):
    called = {}

    def fail_llm_summary(data):
        called["llm"] = True
        raise AssertionError("LLM summary should not be called")

    monkeypatch.setattr(generate_report, "get_engine", lambda: FakeEngine())
    monkeypatch.setattr(generate_report, "fetch_report_data", lambda _connection, _date: sample_report_data())
    monkeypatch.setattr(generate_report, "generate_llm_executive_summary", fail_llm_summary)
    monkeypatch.setattr(
        generate_report,
        "write_report",
        lambda _markdown, output_dir, report_date: output_dir
        / f"market_report_{report_date.isoformat()}.md",
    )

    output_dir = REPO_ROOT / "outputs" / "reports" / "test-output"
    args = SimpleNamespace(
        output_dir=output_dir,
        use_llm_summary=False,
        date=date(2026, 4, 27),
    )

    path = generate_report.run(args)

    assert called == {}
    assert path.name == "market_report_2026-04-27.md"


def test_llm_prompt_contains_safety_constraints():
    messages = generate_report.build_llm_summary_messages(sample_report_data())
    combined = "\n".join(message["content"] for message in messages)

    assert "Do not perform web research" in combined
    assert "Do not invent market share" in combined
    assert "Do not invent competitor facts" in combined
    assert "Clearly distinguish proxy metrics from true market share" in combined
    assert "Do not declare a competitor winner from crawled word share alone" in combined
    assert 'Do not use the phrase "share of voice"' in combined
    assert "Do not say a competitor dominates, leads the market, or has market presence" in combined
    assert "do not say all crawled pages validated successfully" in combined
    assert "Do not say insights were extracted from all raw pages" in combined
    assert "Use data_quality.insights for extracted insight count" in combined
    assert "Use data_quality.valid_insights for analytically valid insight count" in combined
    assert "invalid_insights is greater than 0" in combined
    assert "Do not use vague strategic phrases" in combined
    assert "Use competitor names exactly as listed in allowed_competitor_names" in combined
    assert "Do not rename, abbreviate, title-case, or autocorrect competitor names" in combined


def test_llm_summary_facts_use_refocused_diagnostic_inputs():
    messages = generate_report.build_llm_summary_messages(sample_report_data())
    facts_json = messages[1]["content"].split("Database-derived report facts:\n", 1)[1]
    facts = json.loads(facts_json)

    assert "crawled_word_share_proxy_diagnostics" in facts
    assert "allowed_competitor_names" in facts
    assert facts["allowed_competitor_names"] == ["Acme Analytics", "demo_owned"]
    assert facts["invalid_or_non_evaluable_total"] == 5
    assert "core_competitor_scorecards" in facts
    assert "core_opportunity_backlog" in facts
    assert "topic_output_status" in facts
    assert "diagnostic_only" in facts["topic_output_status"]
    assert "topic_diagnostics" in facts

    assert "top_share_of_voice_proxy" not in facts
    assert "pricing_signals" not in facts
    assert "topics" not in facts
