"""Pydantic schemas for LLM market intelligence extraction."""

from __future__ import annotations

from typing import Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, field_validator


SENTIMENT_VALUES = ("positive", "neutral", "negative", "mixed", "not_found")
FUNNEL_STAGE_VALUES = ("TOFU", "MOFU", "BOFU", "retention/support", "unknown")
PROOF_STRENGTH_VALUES = ("high", "medium", "low", "unknown", "not_found")
CTA_CLASS_VALUES = ("primary", "secondary", "navigation", "footer", "unknown", "not_found")
PAIN_POINT_EVIDENCE_VALUES = (
    "explicit",
    "inferred_from_benefit",
    "keyword_fallback",
    "not_found",
)


class ProofElement(BaseModel):
    """Future typed proof shape, while legacy string arrays remain valid."""

    model_config = ConfigDict(extra="forbid")

    text: str = "not_found"
    proof_type: str = "not_found"
    proof_strength: Literal["high", "medium", "low", "unknown", "not_found"] = (
        "not_found"
    )
    source_text: str = "not_found"

    @field_validator("text", "proof_type", "proof_strength", "source_text", mode="before")
    @classmethod
    def normalize_missing_strings(cls, value):
        if value is None:
            return "not_found"

        normalized = str(value).strip()
        return normalized or "not_found"


class CtaRecord(BaseModel):
    """Future typed CTA shape, while legacy string arrays remain valid."""

    model_config = ConfigDict(extra="forbid")

    text: str = "not_found"
    cta_class: Literal[
        "primary", "secondary", "navigation", "footer", "unknown", "not_found"
    ] = "not_found"
    target: str = "not_found"
    source_text: str = "not_found"

    @field_validator("text", "cta_class", "target", "source_text", mode="before")
    @classmethod
    def normalize_missing_strings(cls, value):
        if value is None:
            return "not_found"

        normalized = str(value).strip()
        return normalized or "not_found"


class PainPointRecord(BaseModel):
    """Future typed pain point shape, while legacy string arrays remain valid."""

    model_config = ConfigDict(extra="forbid")

    pain_point_text: str = "not_found"
    pain_point_category: str = "not_found"
    pain_point_evidence_type: Literal[
        "explicit", "inferred_from_benefit", "keyword_fallback", "not_found"
    ] = "not_found"
    source_text: str = "not_found"

    @field_validator(
        "pain_point_text",
        "pain_point_category",
        "pain_point_evidence_type",
        "source_text",
        mode="before",
    )
    @classmethod
    def normalize_missing_strings(cls, value):
        if value is None:
            return "not_found"

        normalized = str(value).strip()
        return normalized or "not_found"


ProofElementValue: TypeAlias = str | ProofElement
CtaValue: TypeAlias = str | CtaRecord
PainPointValue: TypeAlias = str | PainPointRecord


class PageInsightExtraction(BaseModel):
    """Validated structured insight payload returned by the LLM."""

    model_config = ConfigDict(extra="forbid")

    main_value_proposition: str = "not_found"
    value_proposition_themes: list[str] = Field(default_factory=list)
    messaging_pillars: list[str] = Field(default_factory=list)
    target_audience: str = "not_found"
    tone_of_voice: str = "not_found"
    tone_label: str = "not_found"
    tone_explanation: str = "not_found"
    sentiment: Literal["positive", "neutral", "negative", "mixed", "not_found"] = (
        "not_found"
    )
    positioning: str = "not_found"
    pricing_model: str = "not_found"
    key_features: list[str] = Field(default_factory=list)
    features: list[str] = Field(default_factory=list)
    benefits: list[str] = Field(default_factory=list)
    pain_points: list[PainPointValue] = Field(default_factory=list)
    claims: list[str] = Field(default_factory=list)
    proof_elements: list[ProofElementValue] = Field(default_factory=list)
    objections_handled: list[str] = Field(default_factory=list)
    ctas: list[CtaValue] = Field(default_factory=list)
    cta_texts: list[str] = Field(default_factory=list)
    cta_types: list[str] = Field(default_factory=list)
    cta_targets: list[str] = Field(default_factory=list)
    has_cta: bool = False
    funnel_stage: Literal["TOFU", "MOFU", "BOFU", "retention/support", "unknown"] = "unknown"
    search_intent: str = "unknown"
    has_pricing_signal: bool = False
    has_case_study_signal: bool = False
    conversion_links: list[str] = Field(default_factory=list)
    bofu_strength_score: int = 0
    proof_score: int = 0
    freshness_score: int = 0
    structure_score: int = 0
    clarity_score: int = 0
    clarity_reason: str = "not_found"
    cta_alignment_score: int = 0
    content_quality_score: int = 0
    quality_warnings: list[str] = Field(default_factory=list)
    genericity_score: int = 0
    differentiators: list[str] = Field(default_factory=list)
    summary: str = "not_found"

    @field_validator(
        "main_value_proposition",
        "target_audience",
        "tone_of_voice",
        "tone_label",
        "tone_explanation",
        "sentiment",
        "funnel_stage",
        "search_intent",
        "positioning",
        "pricing_model",
        "clarity_reason",
        "summary",
        mode="before",
    )
    @classmethod
    def normalize_missing_strings(cls, value):
        if value is None:
            return "not_found"

        normalized = str(value).strip()
        return normalized or "not_found"

    @field_validator(
        "key_features",
        "value_proposition_themes",
        "messaging_pillars",
        "features",
        "benefits",
        "claims",
        "objections_handled",
        "cta_texts",
        "cta_types",
        "cta_targets",
        "conversion_links",
        "quality_warnings",
        "differentiators",
        mode="before",
    )
    @classmethod
    def normalize_missing_lists(cls, value):
        if value is None:
            return []

        return value

    @field_validator(
        "key_features",
        "value_proposition_themes",
        "messaging_pillars",
        "features",
        "benefits",
        "claims",
        "objections_handled",
        "cta_texts",
        "cta_types",
        "cta_targets",
        "conversion_links",
        "quality_warnings",
        "differentiators",
    )
    @classmethod
    def normalize_list_items(cls, value: list[str]) -> list[str]:
        items: list[str] = []
        for item in value:
            normalized = str(item).strip()
            if normalized:
                items.append(normalized)

        return items

    @field_validator("pain_points", "proof_elements", "ctas", mode="before")
    @classmethod
    def normalize_missing_mixed_lists(cls, value):
        if value is None:
            return []

        return value

    @field_validator("pain_points")
    @classmethod
    def normalize_pain_points(
        cls, value: list[PainPointValue]
    ) -> list[PainPointValue]:
        items: list[PainPointValue] = []
        for item in value:
            if isinstance(item, str):
                normalized = item.strip()
                if normalized:
                    items.append(normalized)
                continue

            items.append(item)

        return items

    @field_validator("proof_elements")
    @classmethod
    def normalize_proof_elements(
        cls, value: list[ProofElementValue]
    ) -> list[ProofElementValue]:
        items: list[ProofElementValue] = []
        for item in value:
            if isinstance(item, str):
                normalized = item.strip()
                if normalized:
                    items.append(normalized)
                continue

            items.append(item)

        return items

    @field_validator("ctas")
    @classmethod
    def normalize_ctas(cls, value: list[CtaValue]) -> list[CtaValue]:
        items: list[CtaValue] = []
        for item in value:
            if isinstance(item, str):
                normalized = item.strip()
                if normalized:
                    items.append(normalized)
                continue

            items.append(item)

        return items

    @field_validator(
        "bofu_strength_score",
        "proof_score",
        "freshness_score",
        "structure_score",
        "clarity_score",
        "cta_alignment_score",
        "content_quality_score",
        "genericity_score",
        mode="before",
    )
    @classmethod
    def normalize_score(cls, value):
        if value is None or value == "":
            return 0
        try:
            parsed = int(float(value))
        except (TypeError, ValueError):
            return 0
        return max(0, min(100, parsed))
