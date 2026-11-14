"""Extract structured market intelligence from crawled Markdown pages."""

from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import unquote

from dotenv import load_dotenv
from sqlalchemy import text

from db import get_engine
from llm_schemas import PageInsightExtraction


DEFAULT_MODEL = "gpt-4o-mini"
MIN_WORD_COUNT = 150
PAIN_POINT_TAXONOMY = {
    "manual work": [
        "manual",
        "hands-on",
        "hand off",
        "by hand",
        "manual cleanup",
        "manual process",
    ],
    "repetitive workflow": [
        "repetitive",
        "repeatable",
        "repeated",
        "batch",
        "routine",
        "same task",
    ],
    "time cost": [
        "time-consuming",
        "time consuming",
        "save time",
        "hours",
        "faster",
        "speed up",
        "slow",
    ],
    "export/bounce overhead": [
        "export",
        "exports",
        "bounce",
        "bounces",
        "stem",
        "stems",
        "deliverables",
    ],
    "review friction": [
        "review",
        "feedback",
        "notes",
        "revision",
        "revisions",
        "approval notes",
    ],
    "sync/versioning": [
        "sync",
        "synchronization",
        "version",
        "versions",
        "versioning",
        "reference track",
    ],
    "licensing complexity": [
        "license",
        "licence",
        "licensing",
        "subscription",
        "seat",
        "activation",
    ],
    "collaboration bottleneck": [
        "collaboration",
        "collaborate",
        "team",
        "handoff",
        "share",
        "shared",
    ],
    "approval bottleneck": [
        "approval",
        "approve",
        "sign-off",
        "sign off",
        "signoff",
        "stakeholder",
    ],
}
PAIN_POINT_EVIDENCE_TYPES = {
    "explicit",
    "inferred_from_benefit",
    "keyword_fallback",
    "not_pain_point",
}
EXPLICIT_PAIN_MARKERS = [
    "frustrat",
    "slow",
    "slowness",
    "take hours",
    "takes hours",
    "lose time",
    "lost time",
    "time-consuming",
    "time consuming",
    "manual work",
    "manual process",
    "by hand",
    "still have to",
    "have to",
    "hard to",
    "difficult",
    "error",
    "errors",
    "problem",
    "problems",
    "limitation",
    "limitations",
    "cost",
    "costly",
    "complex",
    "complexity",
    "blocker",
    "blocks",
    "stop",
    "stops",
    "breaks down",
    "miss",
    "missed",
    "scattered",
    "cannot",
    "can't",
]
BENEFIT_IMPLICATION_MARKERS = [
    "save",
    "reduce",
    "automate",
    "simplify",
    "keep",
    "without",
    "faster",
    "speed up",
    "eliminate",
]
KEYWORD_FALLBACK_PATTERNS = {
    "manual work": [
        ("manual", "cleanup"),
        ("manual", "process"),
        ("manual", "session prep"),
        ("manual", "export"),
        ("by hand",),
    ],
    "repetitive workflow": [
        ("repetitive",),
        ("repeatable",),
        ("repeated",),
        ("batch", "routine"),
    ],
    "time cost": [
        ("save time",),
        ("save hours",),
        ("hours",),
        ("time-consuming",),
        ("time consuming",),
    ],
    "export/bounce overhead": [
        ("batch", "bounce"),
        ("stem", "naming"),
        ("stem", "delivery"),
        ("deliverable",),
        ("export package",),
    ],
    "review friction": [
        ("feedback", "notes"),
        ("review", "notes"),
        ("revision",),
        ("approval notes",),
    ],
    "sync/versioning": [
        ("versioning",),
        ("version", "sync"),
        ("reference track",),
    ],
    "licensing complexity": [
        ("subscription", "seat"),
        ("activation",),
        ("renewal",),
        ("seat management",),
    ],
    "collaboration bottleneck": [
        ("team", "handoff"),
        ("handoff",),
        ("shared session",),
    ],
    "approval bottleneck": [
        ("approval",),
        ("sign-off",),
        ("sign off",),
        ("stakeholder",),
    ],
}
TECHNICAL_SUBSTRING_PATTERNS = [
    re.compile(r"https?://\S+", re.IGNORECASE),
    re.compile(r"www\.\S+", re.IGNORECASE),
    re.compile(r"(?:https?|ftp)%3A%2F%2F\S+", re.IGNORECASE),
    re.compile(
        r"\b[\w./-]+\.(?:png|jpe?g|gif|webp|svg|ico)(?:\?\S*)?",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:utm_[a-z0-9_]+|token|session(?:_id)?|data-image-id|width|height)=[^\s&]+",
        re.IGNORECASE,
    ),
    re.compile(r"(?:^|\s)\?[^\s]+", re.IGNORECASE),
    re.compile(r"\b[\w.+-]+@[\w.-]+\.[a-z]{2,}\b", re.IGNORECASE),
]
PURE_DOMAIN_PATTERN = re.compile(
    r"^(?:[a-z0-9-]+\.)+[a-z]{2,}(?:/[^\s]*)?$", re.IGNORECASE
)
TECHNICAL_TOKEN_PATTERN = re.compile(r"^[a-z0-9_-]{16,}$", re.IGNORECASE)
SUPPORT_BOILERPLATE = {
    "contact support",
    "support",
    "help center",
    "customer support",
    "technical support",
}
NON_CONTENT_WORDS = {
    "assets",
    "asset",
    "images",
    "image",
    "img",
    "cdn",
    "static",
    "media",
    "uploads",
    "width",
    "height",
    "token",
    "session",
    "source",
    "footer",
    "support",
    "contact",
}


@dataclass(frozen=True)
class SanitizedText:
    original_text: str
    sanitized_text: str
    discarded: bool = False
    discard_reason: str = ""

    @property
    def text(self) -> str:
        return self.sanitized_text


@dataclass(frozen=True)
class RawPage:
    id: int
    competitor_id: int
    competitor_name: str
    source_type: str
    url: str
    title: str | None
    word_count: int
    markdown: str
    asset_type: str = "other"
    freshness_bucket: str = "unknown"
    content_depth_score: int = 0
    metadata_completeness_score: int = 0
    conversion_links: list[str] = None
    has_existing_insight: bool = False

    def __post_init__(self):
        if self.conversion_links is None:
            object.__setattr__(self, "conversion_links", [])
        if self.asset_type == "other" and self.source_type not in {"", "not_found"}:
            object.__setattr__(self, "asset_type", self.source_type)


@dataclass
class ExtractionSummary:
    extracted: int = 0
    refreshed: int = 0
    failed: int = 0
    skipped: int = 0


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Extract structured page insights from successful raw pages with "
            "OpenAI. Every eligible page can make an API call."
        )
    )
    parser.add_argument(
        "--limit",
        type=positive_int,
        help="Maximum pages to extract. Use 15 for the recommended first experiment.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Refresh pages that already have page_insights rows; this can repeat OpenAI calls.",
    )
    parser.add_argument("--competitor", help="Only extract pages for this exact competitor name.")
    parser.add_argument(
        "--source-type",
        help="Only extract pages with this source_type, such as pricing or product.",
    )
    return parser.parse_args(argv)


def build_raw_page_query(args: argparse.Namespace) -> tuple[Any, dict[str, Any]]:
    conditions = [
        "rp.success = TRUE",
        "rp.word_count >= :min_word_count",
        "rp.markdown IS NOT NULL",
        "btrim(rp.markdown) <> ''",
    ]
    params: dict[str, Any] = {"min_word_count": MIN_WORD_COUNT}

    if not args.force:
        conditions.append(
            "NOT EXISTS ("
            "SELECT 1 FROM page_insights pi "
            "WHERE pi.raw_page_id = rp.id"
            ")"
        )

    if args.competitor:
        conditions.append("c.name = :competitor")
        params["competitor"] = args.competitor

    if args.source_type:
        conditions.append("su.source_type = :source_type")
        params["source_type"] = args.source_type

    sql = f"""
        SELECT
            rp.id AS raw_page_id,
            rp.competitor_id,
            c.name AS competitor_name,
            su.source_type,
            rp.url,
            rp.title,
            COALESCE(rp.asset_type, su.source_type, 'other') AS asset_type,
            COALESCE(rp.freshness_bucket, 'unknown') AS freshness_bucket,
            COALESCE(rp.content_depth_score, 0) AS content_depth_score,
            COALESCE(rp.metadata_completeness_score, 0) AS metadata_completeness_score,
            COALESCE(rp.conversion_links, '[]'::jsonb) AS conversion_links,
            rp.word_count,
            rp.markdown,
            EXISTS (
                SELECT 1
                FROM page_insights pi
                WHERE pi.raw_page_id = rp.id
            ) AS has_existing_insight
        FROM raw_pages rp
        JOIN competitors c ON c.id = rp.competitor_id
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
            competitor_name=row._mapping["competitor_name"],
            source_type=row._mapping["source_type"] or "not_found",
            url=row._mapping["url"],
            title=row._mapping["title"],
            asset_type=row._mapping.get("asset_type", row._mapping["source_type"] or "other"),
            freshness_bucket=row._mapping.get("freshness_bucket", "unknown"),
            content_depth_score=row._mapping.get("content_depth_score", 0),
            metadata_completeness_score=row._mapping.get("metadata_completeness_score", 0),
            conversion_links=list(row._mapping.get("conversion_links") or []),
            word_count=row._mapping["word_count"],
            markdown=row._mapping["markdown"],
            has_existing_insight=bool(row._mapping["has_existing_insight"]),
        )
        for row in rows
    ]


def sanitize_classification_text(
    text_value: Any, *, require_readable_text: bool = True
) -> SanitizedText:
    original = str(text_value or "").strip()
    if not original:
        return SanitizedText(original, "", True, "empty")

    decoded = unquote(original)
    if decoded != original:
        original_for_checks = decoded
    else:
        original_for_checks = original

    normalized_original = normalize_evidence_text(original_for_checks)
    if normalized_original in SUPPORT_BOILERPLATE:
        return SanitizedText(original, "", True, "support_boilerplate")
    if PURE_DOMAIN_PATTERN.match(original_for_checks):
        return SanitizedText(original, "", True, "domain_only")
    if TECHNICAL_TOKEN_PATTERN.match(original_for_checks):
        return SanitizedText(original, "", True, "technical_token")

    cleaned = original_for_checks
    removed_technical = False
    for pattern in TECHNICAL_SUBSTRING_PATTERNS:
        cleaned, count = pattern.subn(" ", cleaned)
        removed_technical = removed_technical or bool(count)

    cleaned = clean_sanitized_spacing(cleaned)
    if not cleaned:
        return SanitizedText(
            original,
            "",
            True,
            "technical_fragment" if removed_technical else "empty_after_sanitization",
        )

    normalized_cleaned = normalize_evidence_text(cleaned)
    if normalized_cleaned in SUPPORT_BOILERPLATE:
        return SanitizedText(original, "", True, "support_boilerplate")
    if PURE_DOMAIN_PATTERN.match(cleaned):
        return SanitizedText(original, "", True, "domain_only")
    if not require_readable_text:
        return SanitizedText(original, cleaned, False, "")

    if not is_readable_classification_text(cleaned):
        reason = "technical_noise" if removed_technical else "non_content_text"
        return SanitizedText(original, "", True, reason)

    return SanitizedText(original, cleaned, False, "")


def sanitize_markdown_for_extraction(markdown: str) -> dict[str, Any]:
    kept_lines: list[str] = []
    discarded: list[dict[str, str]] = []
    for line in markdown.splitlines():
        result = sanitize_classification_text(
            strip_markdown_line_marker(line),
            require_readable_text=False,
        )
        if result.discarded:
            if result.original_text:
                discarded.append(
                    {
                        "text": result.original_text,
                        "discard_reason": result.discard_reason,
                    }
                )
            continue
        kept_lines.append(result.sanitized_text)

    return {
        "markdown": "\n".join(kept_lines).strip(),
        "discarded_fragments": discarded,
    }


def strip_markdown_line_marker(value: str) -> str:
    stripped = value.strip()
    stripped = re.sub(r"^#{1,6}\s+", "", stripped)
    stripped = re.sub(r"^(?:[-*]\s+|\d+[.)]\s+)", "", stripped)
    return stripped.strip()


def clean_sanitized_spacing(value: str) -> str:
    cleaned = value.replace("&", " ")
    cleaned = re.sub(r"\s+([,.;:!?])", r"\1", cleaned)
    cleaned = re.sub(r"(?<!\w)[=/|]+(?!\w)", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip(" -_\t\r\n")


def is_readable_classification_text(value: str) -> bool:
    normalized = normalize_evidence_text(value)
    if not normalized:
        return False
    words = re.findall(r"[a-zA-Z][a-zA-Z'-]*", value)
    if (
        len(words) < 3
        and normalized not in PAIN_POINT_TAXONOMY
        and not has_explicit_pain_marker(normalized)
    ):
        return False
    semantic_words = [
        word.lower()
        for word in words
        if len(word) > 2 and word.lower() not in NON_CONTENT_WORDS
    ]
    if len(semantic_words) < 2:
        return False
    alpha_chars = sum(1 for char in value if char.isalpha())
    visible_chars = sum(1 for char in value if not char.isspace())
    if visible_chars and alpha_chars / visible_chars < 0.55:
        return False
    return True


def build_prompt_messages(
    page: RawPage, sanitized_page: dict[str, Any] | None = None
) -> list[dict[str, str]]:
    system_prompt = """
You are a senior market intelligence analyst focused on competitor content intelligence.

Task:
Extract structured competitor content intelligence from a crawled competitor page.

Critical extraction rules:
- Do not invent information, proof, CTAs, claims, pricing, or positioning.
- If something is not present, return "not_found" for strings or [] for lists.
- Use only facts visible in the page Markdown. Do not use "likely", "probably",
  "appears to", "suggests", or similar speculative wording in any field.
- Every proof element and CTA must be grounded in visible source text from the
  page. If the source text is absent, omit the item.
- Claims must be explicit page statements or close paraphrases of visible page
  text. Do not convert brand logos, customer logos, or generic trust sections
  into unsupported leadership claims.
- Interpretations such as positioning, tone, and summary must be grounded in
  specific visible wording from the page.
- Keep arrays concise and page-specific. Avoid generic features such as
  "automation" when the page names a more specific capability.
- Sentiment must be one of: positive, neutral, negative, mixed, not_found.
- Funnel stage must be one of: TOFU, MOFU, BOFU, retention/support, unknown.
- Separate features from benefits. Features are product capabilities; benefits are outcomes.
- Pain points must be visible page pains or clearly implied pains only. Separate
  explicit pain from inferred pain in the evidence type.
- Prefer pain_points as typed objects with exactly these fields when pain
  evidence exists: pain_point_text, pain_point_category,
  pain_point_evidence_type, source_text. Use pain_point_evidence_type explicit
  for visible pain statements and inferred_from_benefit only when a visible
  benefit clearly implies the pain it solves.
- Require source_text for pain points when possible. For inferred pain, use the
  visible benefit wording as source_text. Do not invent pains absent from the page.
- Proof elements must be visible evidence such as numbers, testimonials, customer logos,
  certifications, awards, case studies, reviews, named sources, or measurable results.
- Generic commercial claims such as "powerful", "trusted", "easy", "best",
  "leading", or "save time" are not strong proof unless backed by a visible
  metric, named source, testimonial, certification, award, case study, or review.
- Prefer proof_elements as typed objects with exactly these fields when proof
  exists: text, proof_type, proof_strength, source_text. Use proof_strength
  high, medium, low, unknown, or not_found.
- CTA types must use these labels when possible: book demo, start trial, contact sales,
  view pricing, download, subscribe, sign up, buy now, learn more, request quote, other.
- Navigation and footer links are not primary CTA coverage. Classify visible CTA
  records as primary, secondary, navigation, footer, or unknown.
- Prefer ctas as typed objects with exactly these fields when CTA records are
  visible: text, cta_class, target, source_text. Use target for the href,
  destination label, or not_found when no target is visible.
- Messaging pillars should be short recurring message themes, such as save time,
  reduce costs, automate workflows, improve quality, enterprise security, simplicity,
  speed, transparency, privacy, or control.
- Clarity score, CTA alignment score, proof score, BOFU strength score, content quality
  score, and genericity score must be integers from 0 to 100. Use 0 only when no
  evidence is available.
- Tone of voice should be a short label plus short explanation based on visible
  language. Avoid generic labels unless the explanation makes them specific.
- Pricing model should only be extracted if actual pricing, a named plan, a paid
  model, or a free trial is visible. A navigation link labeled "Pricing" is not
  enough. Do not mention that pricing details are available, accessible, linked,
  or found elsewhere. If only a pricing link is visible, return "not_found".
- Objections handled must be explicit assurances from the page, such as "no
  manual cleanup", "no scripting required", or "no learning curve". Do not
  invent user concerns like "concerns about time-consuming processes".
- Differentiators must be concrete capabilities, integrations, or named
  technology visible on the page. Do not add generic benefits such as
  "enhanced performance" unless the page explicitly says them.
- Do not generate market share numbers.
- Do not claim a competitor is the leader unless the page explicitly says so.

Output schema expectations:
Return only data matching the PageInsightExtraction JSON schema:
main_value_proposition, target_audience, tone_of_voice, sentiment, positioning,
pricing_model, key_features, claims, proof_elements, objections_handled, ctas,
cta_texts, cta_types, cta_targets, pain_points, differentiators, summary, and the vertical
content intelligence fields in the schema. For absent fields, use "not_found"
or [] consistently.

Before final output, perform this self-check silently:
- Each proof element has visible source text and is not invented.
- Each CTA record has visible source text; navigation/footer links are not
  marked as primary CTA coverage.
- Each pain point is explicit or clearly implied by visible source text; absent
  pains are omitted rather than guessed.
- Any ungrounded proof or CTA item has been removed or set to []/not_found.
""".strip()

    sanitized_page = sanitized_page or sanitize_markdown_for_extraction(page.markdown)
    page_markdown = sanitized_page["markdown"]

    user_prompt = f"""
Page metadata:
- raw_page_id: {page.id}
- competitor_name: {page.competitor_name}
- source_type: {page.source_type}
- asset_type: {page.asset_type}
- url: {page.url}
- title: {page.title or "not_found"}
- word_count: {page.word_count}
- deterministic_depth_score: {page.content_depth_score}
- deterministic_structure_score: {page.metadata_completeness_score}
- freshness_bucket: {page.freshness_bucket}
- conversion_links: {json.dumps(page.conversion_links)}

Page Markdown:
<<<PAGE_MARKDOWN
{page_markdown}
PAGE_MARKDOWN
>>>
""".strip()

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def log_sanitizer_discards(page: RawPage, sanitized_page: dict[str, Any]) -> None:
    discarded_fragments = sanitized_page.get("discarded_fragments") or []
    if not discarded_fragments:
        return

    discard_reasons: dict[str, int] = {}
    for fragment in discarded_fragments:
        reason = str(fragment.get("discard_reason") or "unknown")
        discard_reasons[reason] = discard_reasons.get(reason, 0) + 1

    print(
        "sanitizer_discard_audit "
        + json.dumps(
            {
                "raw_page_id": page.id,
                "competitor_id": page.competitor_id,
                "discarded_count": len(discarded_fragments),
                "discard_reasons": discard_reasons,
            },
            sort_keys=True,
        )
    )


def require_openai_api_key() -> None:
    load_dotenv()
    if not os.getenv("OPENAI_API_KEY", "").strip():
        raise RuntimeError(
            "OPENAI_API_KEY is required. Set it in your environment or .env file. "
            "Use --limit for first runs to control API spend."
        )


def create_openai_client():
    from openai import OpenAI

    return OpenAI()


def extract_page_insight(client, page: RawPage, model: str) -> PageInsightExtraction:
    sanitized_page = sanitize_markdown_for_extraction(page.markdown)
    log_sanitizer_discards(page, sanitized_page)
    response = client.responses.parse(
        model=model,
        input=build_prompt_messages(page, sanitized_page=sanitized_page),
        text_format=PageInsightExtraction,
    )
    parsed = getattr(response, "output_parsed", None)

    if parsed is None:
        raise RuntimeError("OpenAI response did not include parsed structured output.")

    if isinstance(parsed, PageInsightExtraction):
        return parsed

    return PageInsightExtraction.model_validate(parsed)


def save_page_insight(
    connection,
    page: RawPage,
    insight: PageInsightExtraction,
    *,
    force: bool = False,
) -> None:
    if force:
        connection.execute(
            text("DELETE FROM page_insights WHERE raw_page_id = :raw_page_id"),
            {"raw_page_id": page.id},
        )

    payload = insight.model_dump()
    payload = enrich_payload_with_fallback_scores(payload, page)
    payload["pain_points"] = enrich_pain_points_with_fallbacks(payload, page)
    payload["pricing_model"] = clean_pricing_model(
        payload["pricing_model"], page.markdown
    )
    payload["objections_handled"] = clean_objections_handled(
        payload["objections_handled"], page.markdown
    )
    connection.execute(
        text(
            """
            INSERT INTO page_insights (
                raw_page_id,
                competitor_id,
                source_type,
                main_value_proposition,
                value_proposition_themes,
                messaging_pillars,
                target_audience,
                tone_of_voice,
                tone_label,
                tone_explanation,
                sentiment,
                positioning,
                pricing_model,
                key_features,
                features,
                benefits,
                pain_points,
                claims,
                proof_elements,
                objections_handled,
                ctas,
                cta_texts,
                cta_types,
                cta_targets,
                has_cta,
                funnel_stage,
                search_intent,
                has_pricing_signal,
                has_case_study_signal,
                conversion_links,
                bofu_strength_score,
                proof_score,
                freshness_score,
                structure_score,
                clarity_score,
                clarity_reason,
                cta_alignment_score,
                content_quality_score,
                quality_warnings,
                genericity_score,
                differentiators,
                summary
            )
            VALUES (
                :raw_page_id,
                :competitor_id,
                :source_type,
                :main_value_proposition,
                CAST(:value_proposition_themes AS JSONB),
                CAST(:messaging_pillars AS JSONB),
                :target_audience,
                :tone_of_voice,
                :tone_label,
                :tone_explanation,
                :sentiment,
                :positioning,
                :pricing_model,
                CAST(:key_features AS JSONB),
                CAST(:features AS JSONB),
                CAST(:benefits AS JSONB),
                CAST(:pain_points AS JSONB),
                CAST(:claims AS JSONB),
                CAST(:proof_elements AS JSONB),
                CAST(:objections_handled AS JSONB),
                CAST(:ctas AS JSONB),
                CAST(:cta_texts AS JSONB),
                CAST(:cta_types AS JSONB),
                CAST(:cta_targets AS JSONB),
                :has_cta,
                :funnel_stage,
                :search_intent,
                :has_pricing_signal,
                :has_case_study_signal,
                CAST(:conversion_links AS JSONB),
                :bofu_strength_score,
                :proof_score,
                :freshness_score,
                :structure_score,
                :clarity_score,
                :clarity_reason,
                :cta_alignment_score,
                :content_quality_score,
                CAST(:quality_warnings AS JSONB),
                :genericity_score,
                CAST(:differentiators AS JSONB),
                :summary
            )
            ON CONFLICT (raw_page_id) DO NOTHING
            """
        ),
        {
            "raw_page_id": page.id,
            "competitor_id": page.competitor_id,
            "source_type": page.source_type,
            "main_value_proposition": payload["main_value_proposition"],
            "value_proposition_themes": json.dumps(payload["value_proposition_themes"]),
            "messaging_pillars": json.dumps(payload["messaging_pillars"]),
            "target_audience": payload["target_audience"],
            "tone_of_voice": payload["tone_of_voice"],
            "tone_label": payload["tone_label"],
            "tone_explanation": payload["tone_explanation"],
            "sentiment": payload["sentiment"],
            "positioning": payload["positioning"],
            "pricing_model": payload["pricing_model"],
            "key_features": json.dumps(payload["key_features"]),
            "features": json.dumps(payload["features"]),
            "benefits": json.dumps(payload["benefits"]),
            "pain_points": json.dumps(payload["pain_points"]),
            "claims": json.dumps(payload["claims"]),
            "proof_elements": json.dumps(payload["proof_elements"]),
            "objections_handled": json.dumps(payload["objections_handled"]),
            "ctas": json.dumps(payload["ctas"]),
            "cta_texts": json.dumps(payload["cta_texts"]),
            "cta_types": json.dumps(payload["cta_types"]),
            "cta_targets": json.dumps(payload["cta_targets"]),
            "has_cta": payload["has_cta"],
            "funnel_stage": payload["funnel_stage"],
            "search_intent": payload["search_intent"],
            "has_pricing_signal": payload["has_pricing_signal"],
            "has_case_study_signal": payload["has_case_study_signal"],
            "conversion_links": json.dumps(payload["conversion_links"]),
            "bofu_strength_score": payload["bofu_strength_score"],
            "proof_score": payload["proof_score"],
            "freshness_score": payload["freshness_score"],
            "structure_score": payload["structure_score"],
            "clarity_score": payload["clarity_score"],
            "clarity_reason": payload["clarity_reason"],
            "cta_alignment_score": payload["cta_alignment_score"],
            "content_quality_score": payload["content_quality_score"],
            "quality_warnings": json.dumps(payload["quality_warnings"]),
            "genericity_score": payload["genericity_score"],
            "differentiators": json.dumps(payload["differentiators"]),
            "summary": payload["summary"],
        },
    )


def enrich_payload_with_fallback_scores(payload: dict[str, Any], page: RawPage) -> dict[str, Any]:
    payload = dict(payload)
    payload["features"] = payload.get("features") or payload.get("key_features") or []
    payload["cta_texts"] = payload.get("cta_texts") or extract_cta_object_field(
        payload.get("ctas"), "text"
    )
    payload["cta_types"] = payload.get("cta_types") or extract_cta_object_field(
        payload.get("ctas"), "cta_class"
    )
    payload["cta_targets"] = payload.get("cta_targets") or extract_cta_object_field(
        payload.get("ctas"), "target"
    )
    payload["has_cta"] = bool(payload.get("has_cta") or payload["cta_texts"])
    payload["conversion_links"] = payload.get("conversion_links") or page.conversion_links
    payload["funnel_stage"] = normalize_funnel_stage(
        payload.get("funnel_stage") or infer_funnel_stage(page.asset_type)
    )
    payload["has_pricing_signal"] = bool(
        payload.get("has_pricing_signal")
        or page.asset_type == "pricing"
        or clean_pricing_model(payload.get("pricing_model", "not_found"), page.markdown) != "not_found"
    )
    payload["has_case_study_signal"] = bool(
        payload.get("has_case_study_signal")
        or page.asset_type == "case_studies"
        or "case stud" in page.markdown.lower()
        or "customer stor" in page.markdown.lower()
    )
    payload["freshness_score"] = payload.get("freshness_score") or freshness_score(page.freshness_bucket)
    payload["structure_score"] = payload.get("structure_score") or page.metadata_completeness_score
    payload["proof_score"] = payload.get("proof_score") or proof_score(payload)
    payload["bofu_strength_score"] = payload.get("bofu_strength_score") or bofu_strength_score(payload, page)
    payload["clarity_score"] = payload.get("clarity_score") or clarity_score(payload)
    payload["cta_alignment_score"] = payload.get("cta_alignment_score") or cta_alignment_score(payload)
    warnings = list(payload.get("quality_warnings") or [])
    if page.freshness_bucket == "unknown":
        warnings.append("undated_content")
    if not payload["has_cta"]:
        warnings.append("missing_cta")
    payload["quality_warnings"] = sorted(set(warnings))
    payload["content_quality_score"] = payload.get("content_quality_score") or content_quality_score(payload, page)
    return payload


def enrich_pain_points_with_fallbacks(
    payload: dict[str, Any], page: RawPage
) -> list[Any]:
    pain_points = normalize_pain_point_values(payload.get("pain_points"), page)
    if pain_points:
        return pain_points

    fallback_records: list[dict[str, str]] = []
    seen_categories: set[str] = set()

    for category, source_text in detect_explicit_pain_phrases(page.markdown):
        if category in seen_categories:
            continue
        seen_categories.add(category)
        fallback_records.append(
            {
                "pain_point_text": source_text,
                "pain_point_category": category,
                "pain_point_evidence_type": "explicit",
                "source_text": source_text,
            }
        )

    for benefit in payload.get("benefits") or []:
        benefit_text = str(benefit).strip()
        if not benefit_text or not implies_pain_from_benefit(benefit_text):
            continue
        category = classify_pain_category(benefit_text)
        if not category or category in seen_categories:
            continue
        seen_categories.add(category)
        fallback_records.append(
            {
                "pain_point_text": category,
                "pain_point_category": category,
                "pain_point_evidence_type": "inferred_from_benefit",
                "source_text": str(benefit).strip(),
            }
        )

    for category, source_text in detect_keyword_pain_categories(page.markdown):
        if category in seen_categories:
            continue
        seen_categories.add(category)
        fallback_records.append(
            {
                "pain_point_text": category,
                "pain_point_category": category,
                "pain_point_evidence_type": "keyword_fallback",
                "source_text": source_text,
            }
        )

    return fallback_records


def normalize_pain_point_values(values: Any, page: RawPage | None = None) -> list[Any]:
    normalized_values: list[Any] = []
    for value in values or []:
        if isinstance(value, str):
            normalized = value.strip()
            if normalized:
                normalized_values.append(normalized)
            continue

        if isinstance(value, dict):
            normalized = normalize_typed_pain_point(value, page)
            if normalized is not None:
                normalized_values.append(normalized)
            continue

        normalized_values.append(value)

    return normalized_values


def normalize_typed_pain_point(
    value: dict[str, Any], page: RawPage | None = None
) -> dict[str, str] | None:
    text_result = sanitize_classification_text(
        str(value.get("pain_point_text") or value.get("text") or "").strip()
    )
    text_value = text_result.sanitized_text
    if not text_value or text_value == "not_found":
        return None

    raw_source_text = str(value.get("source_text") or "").strip()
    source_result = sanitize_classification_text(raw_source_text)
    source_text = source_result.sanitized_text if not source_result.discarded else ""
    category = normalize_pain_category(
        str(value.get("pain_point_category") or "").strip()
    ) or classify_pain_category(text_value)
    evidence_type = normalize_pain_evidence_type(
        str(value.get("pain_point_evidence_type") or "").strip()
    )

    if evidence_type == "not_pain_point":
        return None

    if evidence_type == "explicit":
        source_candidate = source_text or text_value
        source_candidate_result = sanitize_classification_text(source_candidate)
        if source_candidate_result.discarded:
            return None
        source_candidate = source_candidate_result.sanitized_text
        if not source_candidate or source_candidate == "not_found":
            return None
        explicit_category = classify_explicit_pain_phrase(source_candidate)
        if explicit_category is None:
            explicit_category = classify_explicit_pain_phrase(text_value)
        if explicit_category is None:
            evidence_type = "keyword_fallback"
        else:
            if not category or not category_keywords_present(category, source_candidate):
                category = explicit_category
            source_text = source_candidate

    if evidence_type == "inferred_from_benefit":
        source_candidate = source_text or text_value
        source_candidate_result = sanitize_classification_text(source_candidate)
        if source_candidate_result.discarded:
            return None
        source_candidate = source_candidate_result.sanitized_text
        if not implies_pain_from_benefit(source_candidate):
            evidence_type = "keyword_fallback"
        source_text = source_candidate

    if not category:
        category = classify_pain_category(source_text or text_value)
    if not category:
        return None
    if not source_text or source_text == "not_found":
        source_text = text_value

    return {
        "pain_point_text": text_value,
        "pain_point_category": category,
        "pain_point_evidence_type": evidence_type,
        "source_text": source_text,
    }


def normalize_pain_category(value: str) -> str | None:
    normalized = normalize_evidence_text(value)
    return normalized if normalized in PAIN_POINT_TAXONOMY else None


def normalize_pain_evidence_type(value: str) -> str:
    normalized = normalize_evidence_text(value)
    return normalized if normalized in PAIN_POINT_EVIDENCE_TYPES else "explicit"


def classify_pain_category(text_value: str) -> str | None:
    normalized = normalize_evidence_text(text_value)
    category_priority = [
        "time cost",
        "manual work",
        "repetitive workflow",
        "export/bounce overhead",
        "review friction",
        "collaboration bottleneck",
        "sync/versioning",
        "licensing complexity",
        "approval bottleneck",
    ]
    for category in category_priority:
        keywords = PAIN_POINT_TAXONOMY[category]
        if any(keyword in normalized for keyword in keywords):
            return category
    return None


def classify_explicit_pain_phrase(text_value: str) -> str | None:
    normalized = normalize_evidence_text(text_value)
    if not normalized or not has_explicit_pain_marker(normalized):
        return None

    if (
        ("collaboration" in normalized or "handoff" in normalized or "hand off" in normalized)
        and ("breaks down" in normalized or "cannot" in normalized or "can't" in normalized)
    ):
        return "collaboration bottleneck"
    if (
        "manual" in normalized
        and ("export" in normalized or "by hand" in normalized or "cleanup" in normalized)
    ):
        return "manual work"

    category_scores: dict[str, int] = {}
    for category, keywords in PAIN_POINT_TAXONOMY.items():
        score = sum(1 for keyword in keywords if keyword in normalized)
        if score:
            category_scores[category] = score

    if not category_scores:
        return None

    category_priority = [
        "manual work",
        "repetitive workflow",
        "review friction",
        "licensing complexity",
        "collaboration bottleneck",
        "time cost",
        "export/bounce overhead",
        "sync/versioning",
        "approval bottleneck",
    ]
    return max(
        category_scores,
        key=lambda category: (category_scores[category], -category_priority.index(category)),
    )


def category_keywords_present(category: str, text_value: str) -> bool:
    normalized = normalize_evidence_text(text_value)
    return any(keyword in normalized for keyword in PAIN_POINT_TAXONOMY.get(category, []))


def detect_explicit_pain_phrases(markdown: str) -> list[tuple[str, str]]:
    matches: list[tuple[str, str]] = []
    for phrase in split_source_phrases(markdown):
        category = classify_explicit_pain_phrase(phrase)
        if category:
            matches.append((category, phrase))
    return matches


def split_source_phrases(markdown: str) -> list[str]:
    phrases: list[str] = []
    for line in markdown.splitlines():
        normalized_line = strip_markdown_line_marker(line)
        if not normalized_line:
            continue
        sanitized_line = sanitize_classification_text(normalized_line)
        if sanitized_line.discarded:
            continue
        normalized_line = sanitized_line.sanitized_text
        parts = [
            part.strip()
            for part in normalized_line.replace("?", ".").replace("!", ".").split(".")
        ]
        for part in parts:
            sanitized_part = sanitize_classification_text(part)
            if not sanitized_part.discarded:
                phrases.append(sanitized_part.sanitized_text)
    if phrases:
        return [phrase[:240] for phrase in phrases]

    compact = " ".join(markdown.split()).strip()
    sanitized_compact = sanitize_classification_text(compact)
    return [sanitized_compact.sanitized_text[:240]] if not sanitized_compact.discarded else []


def has_explicit_pain_marker(normalized: str) -> bool:
    return any(marker in normalized for marker in EXPLICIT_PAIN_MARKERS)


def implies_pain_from_benefit(text_value: str) -> bool:
    normalized = normalize_evidence_text(text_value)
    return bool(normalized) and any(
        marker in normalized for marker in BENEFIT_IMPLICATION_MARKERS
    )


def detect_keyword_pain_categories(markdown: str) -> list[tuple[str, str]]:
    matches: list[tuple[str, str]] = []
    for phrase in split_source_phrases(markdown):
        normalized_phrase = normalize_evidence_text(phrase)
        if not normalized_phrase or has_explicit_pain_marker(normalized_phrase):
            continue
        for category, patterns in KEYWORD_FALLBACK_PATTERNS.items():
            if any(all(term in normalized_phrase for term in pattern) for pattern in patterns):
                matches.append((category, phrase[:240]))

    return matches


def extract_source_snippet(markdown: str, keyword: str) -> str:
    compact_lines = [line.strip() for line in markdown.splitlines() if line.strip()]
    for line in compact_lines:
        if keyword.lower() in line.lower():
            return line[:240]

    normalized = " ".join(markdown.split())
    index = normalized.lower().find(keyword.lower())
    if index == -1:
        return "not_found"
    start = max(0, index - 80)
    end = min(len(normalized), index + len(keyword) + 120)
    return normalized[start:end].strip()


def extract_cta_object_field(values: Any, field_name: str) -> list[str]:
    extracted: list[str] = []
    for value in values or []:
        if isinstance(value, str):
            if field_name == "text" and value.strip():
                extracted.append(value.strip())
            continue

        if not isinstance(value, dict):
            continue

        raw_value = value.get(field_name)
        if raw_value is None:
            continue

        normalized = str(raw_value).strip()
        if normalized and normalized != "not_found":
            extracted.append(normalized)

    return extracted


def normalize_funnel_stage(value: str) -> str:
    normalized = str(value or "").strip()
    allowed = {"TOFU", "MOFU", "BOFU", "retention/support", "unknown"}
    return normalized if normalized in allowed else "unknown"


def infer_funnel_stage(asset_type: str) -> str:
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
    }.get(asset_type, "unknown")


def freshness_score(bucket: str) -> int:
    return {"fresh": 100, "recent": 75, "old": 35, "unknown": 40}.get(bucket, 40)


def proof_score(payload: dict[str, Any]) -> int:
    proof_count = len(payload.get("proof_elements") or [])
    claim_count = len(payload.get("claims") or [])
    return min(100, proof_count * 20 + claim_count * 5)


def bofu_strength_score(payload: dict[str, Any], page: RawPage) -> int:
    score = 0
    score += 25 if payload.get("funnel_stage") == "BOFU" else 0
    score += 20 if payload.get("has_pricing_signal") else 0
    score += 15 if payload.get("has_case_study_signal") else 0
    score += 20 if payload.get("has_cta") else 0
    score += min(20, len(payload.get("proof_elements") or []) * 5)
    score += 10 if page.asset_type in {"pricing", "case_studies", "comparison", "product"} else 0
    return min(100, score)


def clarity_score(payload: dict[str, Any]) -> int:
    score = 0
    score += 35 if payload.get("main_value_proposition") != "not_found" else 0
    score += 25 if payload.get("target_audience") != "not_found" else 0
    score += 20 if payload.get("benefits") else 0
    score += 20 if payload.get("positioning") != "not_found" else 0
    return min(100, score)


def cta_alignment_score(payload: dict[str, Any]) -> int:
    if not payload.get("has_cta"):
        return 20 if payload.get("funnel_stage") in {"TOFU", "retention/support"} else 0
    cta_types = {str(item).lower() for item in payload.get("cta_types") or []}
    if payload.get("funnel_stage") == "BOFU" and cta_types & {
        "book demo",
        "start trial",
        "contact sales",
        "view pricing",
        "buy now",
        "request quote",
    }:
        return 100
    if payload.get("funnel_stage") == "TOFU" and cta_types & {"learn more", "subscribe", "download"}:
        return 85
    return 65


def content_quality_score(payload: dict[str, Any], page: RawPage) -> int:
    score = (
        0.25 * page.content_depth_score
        + 0.20 * payload.get("proof_score", 0)
        + 0.15 * payload.get("freshness_score", 0)
        + 0.15 * payload.get("structure_score", 0)
        + 0.15 * payload.get("clarity_score", 0)
        + 0.10 * payload.get("cta_alignment_score", 0)
    )
    return int(round(score))


def clean_pricing_model(value: str, markdown: str = "") -> str:
    """Remove unsupported pricing-link speculation before storing insights."""
    normalized = value.strip()
    free_trial = extract_visible_free_trial(markdown)

    if normalized == "not_found" and free_trial:
        return free_trial

    if not normalized or normalized == "not_found":
        return "not_found"

    speculative_fragments = [
        "pricing details are accessible",
        "pricing details are available",
        "pricing details can be found",
        "pricing details are found",
        "via links",
        "via a link",
        "pricing page",
        "pricing links available",
        "further details",
        "under 'pricing'",
        "under pricing",
        "not explicitly mentioned",
        "found elsewhere",
    ]
    if any(fragment in normalized.lower() for fragment in speculative_fragments):
        if "free trial" in normalized.lower():
            trial_only = normalized
            for delimiter in [
                ", with further details",
                "; with further details",
                ", specific pricing",
                "; specific pricing",
                ", pricing",
                "; pricing",
            ]:
                index = trial_only.lower().find(delimiter)
                if index != -1:
                    trial_only = trial_only[:index].strip()
            if not any(fragment in trial_only.lower() for fragment in speculative_fragments):
                return trial_only.rstrip(".") or free_trial or "not_found"

        parts = [
            part.strip()
            for part in normalized.replace(";", ".").split(".")
            if part.strip()
        ]
        supported_parts = [
            part
            for part in parts
            if not any(fragment in part.lower() for fragment in speculative_fragments)
        ]
        cleaned = ". ".join(supported_parts)
        return cleaned or free_trial or "not_found"

    return normalized


def extract_visible_free_trial(markdown: str) -> str | None:
    normalized = " ".join(markdown.lower().split())
    if "30 days for free" in normalized or "30-day free trial" in normalized:
        return "30-day free trial"
    if "free 7-day trial" in normalized or "7-day free trial" in normalized:
        return "Free 7-day trial"
    if "free trial" in normalized:
        return "Free trial"
    return None


def clean_objections_handled(values: list[str], markdown: str = "") -> list[str]:
    inferred_markers = [
        "concerns about",
        "questions about",
        "addresses by",
        "addressed by",
        "encourage user",
    ]
    normalized_markdown = normalize_evidence_text(markdown)
    cleaned: list[str] = []
    for value in values:
        normalized = value.strip()
        if not normalized:
            continue
        if any(marker in normalized.lower() for marker in inferred_markers):
            continue
        if normalized_markdown and normalize_evidence_text(normalized) not in normalized_markdown:
            continue
        cleaned.append(normalized)
    return cleaned


def normalize_evidence_text(value: str) -> str:
    return " ".join(value.lower().replace(".", "").strip().split())


def process_pages(engine, client, pages: list[RawPage], args: argparse.Namespace) -> ExtractionSummary:
    summary = ExtractionSummary()
    model = os.getenv("OPENAI_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL

    for index, page in enumerate(pages, start=1):
        prefix = (
            f"[{index}/{len(pages)}] page_id={page.id} "
            f"competitor={page.competitor_name} source_type={page.source_type}"
        )
        try:
            insight = extract_page_insight(client, page, model)
            with engine.begin() as connection:
                save_page_insight(connection, page, insight, force=args.force)

            if args.force and page.has_existing_insight:
                summary.refreshed += 1
                print(f"{prefix} status=refreshed")
            else:
                summary.extracted += 1
                print(f"{prefix} status=extracted")
        except Exception as exc:
            summary.failed += 1
            print(f"{prefix} status=failed error={type(exc).__name__}: {exc}")

    return summary


def run(args: argparse.Namespace) -> ExtractionSummary:
    require_openai_api_key()
    engine = get_engine()

    with engine.connect() as connection:
        pages = fetch_raw_pages(connection, args)

    if not pages:
        print(
            "No eligible raw pages matched the requested filters. Pages must be "
            f"successful, non-empty, at least {MIN_WORD_COUNT} words, and not "
            "already extracted unless --force is used."
        )
        return ExtractionSummary(skipped=0)

    print(f"Found {len(pages)} eligible raw page(s).")
    client = create_openai_client()
    return process_pages(engine, client, pages, args)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)

    try:
        summary = run(args)
    except ImportError as exc:
        print("Extraction failed: OpenAI SDK is not installed or cannot be imported.")
        print("  fix: install requirements, then rerun with OPENAI_API_KEY set in .env.")
        print(f"  details: {exc}")
        raise SystemExit(1) from exc
    except RuntimeError as exc:
        print("Extraction failed:")
        print(f"  errors: {exc}")
        raise SystemExit(1) from exc

    print(
        "Extraction summary: "
        f"extracted={summary.extracted}, "
        f"refreshed={summary.refreshed}, "
        f"failed={summary.failed}, "
        f"skipped={summary.skipped}"
    )


if __name__ == "__main__":
    main()
