import sys
from pathlib import Path

import pytest
from pydantic import ValidationError


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from llm_schemas import CtaRecord, PageInsightExtraction, PainPointRecord, ProofElement


def test_page_insight_schema_accepts_valid_payload():
    insight = PageInsightExtraction(
        main_value_proposition="Fast competitive research",
        target_audience="Marketing teams",
        tone_of_voice="Confident: direct enterprise messaging",
        sentiment="positive",
        positioning="AI market intelligence platform",
        pricing_model="Subscription pricing is visible",
        key_features=["Crawling", "Dashboards"],
        claims=["Saves research time"],
        objections_handled=["No setup required"],
        ctas=["Start trial"],
        differentiators=["Local-first workflow"],
        summary="The page positions the company as a research automation tool.",
    )

    assert insight.sentiment == "positive"
    assert insight.key_features == ["Crawling", "Dashboards"]


def test_page_insight_schema_rejects_invalid_sentiment():
    with pytest.raises(ValidationError):
        PageInsightExtraction(sentiment="excited")


def test_page_insight_schema_normalizes_missing_values():
    insight = PageInsightExtraction(
        main_value_proposition=None,
        target_audience=" ",
        tone_of_voice=None,
        sentiment=None,
        key_features=None,
        claims=None,
        objections_handled=None,
        ctas=None,
        differentiators=None,
        summary="",
    )

    assert insight.main_value_proposition == "not_found"
    assert insight.target_audience == "not_found"
    assert insight.tone_of_voice == "not_found"
    assert insight.sentiment == "not_found"
    assert insight.key_features == []
    assert insight.claims == []
    assert insight.objections_handled == []
    assert insight.ctas == []
    assert insight.differentiators == []
    assert insight.summary == "not_found"


def test_page_insight_schema_rejects_extra_fields():
    with pytest.raises(ValidationError):
        PageInsightExtraction(unexpected="value")


def test_page_insight_schema_accepts_typed_proof_objects():
    insight = PageInsightExtraction(
        proof_elements=[
            {
                "text": "Rated 4.8 by 200 users",
                "proof_type": "review",
                "proof_strength": "high",
                "source_text": "Rated 4.8 by 200 users",
            },
            {
                "text": "",
                "proof_type": None,
                "proof_strength": "medium",
                "source_text": " ",
            },
        ]
    )

    assert isinstance(insight.proof_elements[0], ProofElement)
    assert insight.proof_elements[0].proof_strength == "high"
    assert insight.proof_elements[1].text == "not_found"
    assert insight.proof_elements[1].proof_type == "not_found"
    assert insight.proof_elements[1].source_text == "not_found"


def test_page_insight_schema_accepts_typed_cta_objects():
    insight = PageInsightExtraction(
        ctas=[
            {
                "text": "Book demo",
                "cta_class": "primary",
                "target": "/demo",
                "source_text": "Book demo",
            },
            {
                "text": "Privacy",
                "cta_class": "footer",
                "target": None,
                "source_text": "",
            },
        ]
    )

    assert isinstance(insight.ctas[0], CtaRecord)
    assert insight.ctas[0].cta_class == "primary"
    assert insight.ctas[1].cta_class == "footer"
    assert insight.ctas[1].target == "not_found"
    assert insight.ctas[1].source_text == "not_found"


def test_page_insight_schema_accepts_typed_pain_point_objects():
    insight = PageInsightExtraction(
        pain_points=[
            {
                "pain_point_text": "Manual exports take too long",
                "pain_point_category": "manual work",
                "pain_point_evidence_type": "explicit",
                "source_text": "Manual exports take too long.",
            },
            {
                "pain_point_text": "",
                "pain_point_category": None,
                "pain_point_evidence_type": "inferred_from_benefit",
                "source_text": " ",
            },
        ]
    )

    assert isinstance(insight.pain_points[0], PainPointRecord)
    assert insight.pain_points[0].pain_point_evidence_type == "explicit"
    assert insight.pain_points[1].pain_point_text == "not_found"
    assert insight.pain_points[1].pain_point_category == "not_found"
    assert insight.pain_points[1].source_text == "not_found"


def test_page_insight_schema_preserves_legacy_proof_and_cta_strings():
    insight = PageInsightExtraction(
        pain_points=["Slow reporting", "  "],
        proof_elements=["Named customer: Acme", "  "],
        ctas=["Start trial", ""],
    )
    dumped = insight.model_dump()

    assert insight.pain_points == ["Slow reporting"]
    assert insight.proof_elements == ["Named customer: Acme"]
    assert insight.ctas == ["Start trial"]
    assert dumped["pain_points"] == ["Slow reporting"]
    assert dumped["proof_elements"] == ["Named customer: Acme"]
    assert dumped["ctas"] == ["Start trial"]


def test_page_insight_schema_rejects_invalid_proof_strength_and_cta_class():
    with pytest.raises(ValidationError):
        PageInsightExtraction(proof_elements=[{"text": "Proof", "proof_strength": "strong"}])

    with pytest.raises(ValidationError):
        PageInsightExtraction(ctas=[{"text": "Go", "cta_class": "commercial"}])

    with pytest.raises(ValidationError):
        PageInsightExtraction(
            pain_points=[
                {
                    "pain_point_text": "Slow review",
                    "pain_point_evidence_type": "guessed",
                }
            ]
        )
