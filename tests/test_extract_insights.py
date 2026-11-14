import importlib.util
import json
import sys
from types import SimpleNamespace
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "02_extract_insights.py"
PAIN_POINT_FIXTURE_PATH = (
    REPO_ROOT / "tests" / "fixtures" / "pain_point_classification_examples.json"
)

sys.path.insert(0, str(REPO_ROOT / "scripts"))
spec = importlib.util.spec_from_file_location("extract_script", SCRIPT_PATH)
extract_script = importlib.util.module_from_spec(spec)
sys.modules["extract_script"] = extract_script
spec.loader.exec_module(extract_script)


class FakeRow:
    def __init__(self, **values):
        self._mapping = values


class FakeConnection:
    def __init__(self, rows=None):
        self.rows = rows or []
        self.calls = []

    def execute(self, statement, params=None):
        self.calls.append((str(statement), params or {}))
        return self.rows


class FakeEngine:
    def __init__(self):
        self.connections = []

    def begin(self):
        connection = FakeConnection()
        self.connections.append(connection)
        return FakeContext(connection)


class FakeContext:
    def __init__(self, connection):
        self.connection = connection

    def __enter__(self):
        return self.connection

    def __exit__(self, exc_type, exc, traceback):
        return False


class FakeClient:
    def __init__(self):
        self.calls = 0


class FakeResponsesClient:
    def __init__(self):
        self.input = None

    def parse(self, model, input, text_format):
        self.input = input
        return SimpleNamespace(
            output_parsed=extract_script.PageInsightExtraction(summary="ok")
        )


class FakeOpenAIClient:
    def __init__(self):
        self.responses = FakeResponsesClient()


def load_pain_point_examples():
    return json.loads(PAIN_POINT_FIXTURE_PATH.read_text(encoding="utf-8"))


def classify_pain_point_example(example):
    page = extract_script.RawPage(
        id=100,
        competitor_id=2,
        competitor_name="FixtureCo",
        source_type="homepage",
        url=f"https://fixture.example/{example['id']}",
        title=example["id"],
        word_count=250,
        markdown=example["markdown"],
    )
    enriched = extract_script.enrich_pain_points_with_fallbacks(
        {"pain_points": [], "benefits": example["benefits"]},
        page,
    )
    if not enriched:
        return {
            "evidence_type": "not_pain_point",
            "category": None,
            "source_text": None,
        }

    first = enriched[0]
    if isinstance(first, dict):
        return {
            "evidence_type": first.get("pain_point_evidence_type"),
            "category": first.get("pain_point_category"),
            "source_text": first.get("source_text"),
        }

    return {
        "evidence_type": "explicit",
        "category": extract_script.classify_pain_category(str(first)),
        "source_text": None,
    }


def pain_point_fixture_results():
    return [
        {
            "example": example,
            "actual": classify_pain_point_example(example),
        }
        for example in load_pain_point_examples()
    ]


def test_build_raw_page_query_filters_eligible_pages_without_force():
    args = extract_script.parse_args(
        ["--limit", "5", "--competitor", "Acme", "--source-type", "pricing"]
    )

    statement, params = extract_script.build_raw_page_query(args)
    sql = str(statement)

    assert "rp.success = TRUE" in sql
    assert "rp.word_count >= :min_word_count" in sql
    assert "btrim(rp.markdown) <> ''" in sql
    assert "NOT EXISTS" in sql
    assert "c.name = :competitor" in sql
    assert "su.source_type = :source_type" in sql
    assert "LIMIT :limit" in sql
    assert params == {
        "min_word_count": 150,
        "competitor": "Acme",
        "source_type": "pricing",
        "limit": 5,
    }


def test_build_raw_page_query_includes_existing_pages_with_force():
    args = extract_script.parse_args(["--force"])

    statement, _ = extract_script.build_raw_page_query(args)

    assert "NOT EXISTS" not in str(statement)


def test_fetch_raw_pages_maps_database_rows():
    connection = FakeConnection(
        [
            FakeRow(
                raw_page_id=9,
                competitor_id=2,
                competitor_name="Acme",
                source_type="pricing",
                url="https://example.com/pricing",
                title="Pricing",
                word_count=250,
                markdown="Market page",
                has_existing_insight=True,
            )
        ]
    )

    pages = extract_script.fetch_raw_pages(connection, extract_script.parse_args([]))

    assert pages == [
        extract_script.RawPage(
            id=9,
            competitor_id=2,
            competitor_name="Acme",
            source_type="pricing",
            url="https://example.com/pricing",
            title="Pricing",
            word_count=250,
            markdown="Market page",
            has_existing_insight=True,
        )
    ]


def test_build_prompt_messages_includes_required_instructions_and_metadata():
    page = extract_script.RawPage(
        id=9,
        competitor_id=2,
        competitor_name="Acme",
        source_type="pricing",
        url="https://example.com/pricing",
        title="Pricing",
        word_count=250,
        markdown="# Pricing\nEnterprise plan available.",
    )

    messages = extract_script.build_prompt_messages(page)
    combined = "\n".join(message["content"] for message in messages)

    assert "senior market intelligence analyst" in combined
    assert "Do not invent information" in combined
    assert "Do not invent information, proof, CTAs, claims, pricing, or positioning" in combined
    assert "Output schema expectations" in combined
    assert "Do not use \"likely\"" in combined
    assert "Claims must be explicit page statements" in combined
    assert "Every proof element and CTA must be grounded in visible source text" in combined
    assert "Pain points must be visible page pains or clearly implied pains only" in combined
    assert "explicit pain from inferred pain" in combined
    assert "pain_point_text, pain_point_category" in combined
    assert "inferred_from_benefit" in combined
    assert "Do not invent pains absent from the page" in combined
    assert "Generic commercial claims" in combined
    assert "are not strong proof" in combined
    assert "text, proof_type, proof_strength, source_text" in combined
    assert "Navigation and footer links are not primary CTA coverage" in combined
    assert "text, cta_class, target, source_text" in combined
    assert "perform this self-check silently" in combined
    assert "Any ungrounded proof or CTA item has been removed" in combined
    assert "A navigation link labeled \"Pricing\" is not" in combined
    assert "Do not mention that pricing details are available" in combined
    assert "Objections handled must be explicit assurances" in combined
    assert "Differentiators must be concrete capabilities" in combined
    assert "raw_page_id: 9" in combined
    assert "competitor_name: Acme" in combined
    assert "source_type: pricing" in combined
    assert "<<<PAGE_MARKDOWN" in combined
    assert "PAGE_MARKDOWN" in combined
    assert "Do not generate market share numbers" in combined
    assert "unless the page explicitly says so" in combined


def test_save_page_insight_serializes_jsonb_fields_and_force_deletes_existing_rows():
    connection = FakeConnection()
    page = extract_script.RawPage(
        id=9,
        competitor_id=2,
        competitor_name="Acme",
        source_type="pricing",
        url="https://example.com/pricing",
        title="Pricing",
        word_count=250,
        markdown="Market page",
    )
    insight = extract_script.PageInsightExtraction(
        main_value_proposition="Value",
        sentiment="neutral",
        key_features=["Feature A"],
        claims=["Claim A"],
        ctas=["Book demo"],
    )

    extract_script.save_page_insight(connection, page, insight, force=True)

    delete_sql, delete_params = connection.calls[0]
    insert_sql, insert_params = connection.calls[1]

    assert "DELETE FROM page_insights" in delete_sql
    assert delete_params == {"raw_page_id": 9}
    assert "CAST(:key_features AS JSONB)" in insert_sql
    assert json.loads(insert_params["key_features"]) == ["Feature A"]
    assert json.loads(insert_params["claims"]) == ["Claim A"]
    pain_points = json.loads(insert_params["pain_points"])
    assert pain_points == []
    assert json.loads(insert_params["objections_handled"]) == []
    assert json.loads(insert_params["ctas"]) == ["Book demo"]
    assert json.loads(insert_params["differentiators"]) == []


def test_save_page_insight_serializes_typed_proof_and_cta_objects_with_legacy_cta_fallbacks():
    connection = FakeConnection()
    page = extract_script.RawPage(
        id=10,
        competitor_id=2,
        competitor_name="Acme",
        source_type="homepage",
        url="https://example.com",
        title="Home",
        word_count=250,
        markdown="Rated 4.8 by users. Book demo.",
    )
    insight = extract_script.PageInsightExtraction(
        proof_elements=[
            {
                "text": "Rated 4.8 by users",
                "proof_type": "review",
                "proof_strength": "high",
                "source_text": "Rated 4.8 by users.",
            },
            "Customer logo: Acme",
        ],
        ctas=[
            {
                "text": "Book demo",
                "cta_class": "primary",
                "target": "/demo",
                "source_text": "Book demo.",
            },
            "Learn more",
        ],
    )

    extract_script.save_page_insight(connection, page, insight)

    _, insert_params = connection.calls[0]
    proof_elements = json.loads(insert_params["proof_elements"])
    ctas = json.loads(insert_params["ctas"])

    assert proof_elements == [
        {
            "text": "Rated 4.8 by users",
            "proof_type": "review",
            "proof_strength": "high",
            "source_text": "Rated 4.8 by users.",
        },
        "Customer logo: Acme",
    ]
    assert ctas == [
        {
            "text": "Book demo",
            "cta_class": "primary",
            "target": "/demo",
            "source_text": "Book demo.",
        },
        "Learn more",
    ]
    assert json.loads(insert_params["cta_texts"]) == ["Book demo", "Learn more"]
    assert json.loads(insert_params["cta_types"]) == ["primary"]
    assert json.loads(insert_params["cta_targets"]) == ["/demo"]
    assert insert_params["has_cta"] is True


def test_save_page_insight_serializes_typed_pain_points_without_fallback_duplication():
    connection = FakeConnection()
    page = extract_script.RawPage(
        id=11,
        competitor_id=2,
        competitor_name="Acme",
        source_type="homepage",
        url="https://example.com",
        title="Home",
        word_count=250,
        markdown="Manual exports take hours. Book demo.",
    )
    insight = extract_script.PageInsightExtraction(
        pain_points=[
            {
                "pain_point_text": "Manual exports take hours",
                "pain_point_category": "manual work",
                "pain_point_evidence_type": "explicit",
                "source_text": "Manual exports take hours.",
            }
        ]
    )

    extract_script.save_page_insight(connection, page, insight)

    _, insert_params = connection.calls[0]
    assert json.loads(insert_params["pain_points"]) == [
        {
            "pain_point_text": "Manual exports take hours",
            "pain_point_category": "manual work",
            "pain_point_evidence_type": "explicit",
            "source_text": "Manual exports take hours.",
        }
    ]


def test_pain_point_fallback_uses_benefits_then_keyword_categories():
    page = extract_script.RawPage(
        id=12,
        competitor_id=2,
        competitor_name="Acme",
        source_type="homepage",
        url="https://example.com",
        title="Home",
        word_count=250,
        markdown=(
            "Automate manual exports and bounce deliverables. "
            "Review notes stay in sync for every approval."
        ),
    )
    payload = {
        "pain_points": [],
        "benefits": ["Save hours by automating repetitive review workflows"],
    }

    enriched = extract_script.enrich_pain_points_with_fallbacks(payload, page)

    categories = {item["pain_point_category"] for item in enriched}
    evidence_types = {item["pain_point_evidence_type"] for item in enriched}

    assert "time cost" in categories
    assert "manual work" in categories
    assert "export/bounce overhead" in categories
    assert "inferred_from_benefit" in evidence_types
    assert "keyword_fallback" in evidence_types


def _classification_sanitizer_result(text):
    assert hasattr(extract_script, "sanitize_classification_text"), (
        "Report Integrity Patch requires sanitize_classification_text(text) "
        "before pain point classification"
    )
    return extract_script.sanitize_classification_text(text)


def _sanitized_text(result):
    if isinstance(result, dict):
        return result.get("text") or result.get("sanitized_text") or ""
    if isinstance(result, tuple):
        return result[0] or ""
    return getattr(result, "text", getattr(result, "sanitized_text", "")) or ""


def _discard_reason(result):
    if isinstance(result, dict):
        return result.get("discard_reason") or result.get("reason") or ""
    if isinstance(result, tuple):
        return result[1] if len(result) > 1 else ""
    return getattr(result, "discard_reason", getattr(result, "reason", "")) or ""


def _is_discarded(result):
    if isinstance(result, dict):
        return bool(result.get("discarded") or result.get("is_discarded"))
    if isinstance(result, tuple):
        return not bool(result[0])
    return bool(getattr(result, "discarded", getattr(result, "is_discarded", False)))


def test_sanitize_classification_text_keeps_readable_residual_after_technical_link():
    result = _classification_sanitizer_result(
        "Manual exports take hours for every revision "
        "https://cdn.example.com/assets/bounce.png?token=abc123&utm_source=footer"
    )

    clean_text = _sanitized_text(result)

    assert not _is_discarded(result)
    assert "Manual exports take hours for every revision" in clean_text
    assert "https://" not in clean_text
    assert "bounce.png" not in clean_text
    assert "token=abc123" not in clean_text
    assert not _discard_reason(result)


def test_sanitize_classification_text_discards_technical_or_boilerplate_fragments():
    noisy_fragments = [
        "/assets/images/bounce-export-card.png",
        "https%3A%2F%2Fcdn.example.com%2Fimage.png%3Ftoken%3Dabc123",
        "?utm_source=footer&token=abc123&session_id=456",
        "support@example.com",
        "cdn.example.com",
        "contact support",
        "data-image-id=abc123 width=1200 height=600",
    ]

    for fragment in noisy_fragments:
        result = _classification_sanitizer_result(fragment)

        assert _is_discarded(result), fragment
        assert not _sanitized_text(result).strip(), fragment
        assert _discard_reason(result).strip(), fragment


def test_explicit_pain_detection_uses_sanitized_source_text_not_technical_noise():
    page = extract_script.RawPage(
        id=13,
        competitor_id=2,
        competitor_name="Acme",
        source_type="homepage",
        url="https://example.com",
        title="Home",
        word_count=250,
        markdown=(
            "Manual exports take hours for each client revision "
            "https://cdn.example.com/assets/bounce.png?token=abc123&utm_source=footer\n"
            "/assets/images/support-card.png\n"
            "contact support"
        ),
    )

    enriched = extract_script.enrich_pain_points_with_fallbacks(
        {"pain_points": [], "benefits": []},
        page,
    )
    explicit_items = [
        item
        for item in enriched
        if item.get("pain_point_evidence_type") == "explicit"
    ]

    assert explicit_items
    for item in explicit_items:
        source_text = item.get("source_text", "")
        assert "Manual exports take hours" in source_text
        assert "https://" not in source_text
        assert ".png" not in source_text
        assert "token=abc123" not in source_text
        assert "contact support" not in source_text.lower()


def test_build_prompt_messages_uses_sanitized_markdown_for_extraction():
    page = extract_script.RawPage(
        id=14,
        competitor_id=2,
        competitor_name="Acme",
        source_type="homepage",
        url="https://example.com",
        title="Home",
        word_count=250,
        markdown=(
            "# Home\n"
            "Manual exports take hours for every revision.\n"
            "https%3A%2F%2Fcdn.example.com%2Fworkflow.png%3Ftoken%3Dabc123\n"
            "contact support\n"
        ),
    )

    messages = extract_script.build_prompt_messages(page)
    combined = "\n".join(message["content"] for message in messages)

    assert "Manual exports take hours for every revision" in combined
    assert "https%3A%2F%2Fcdn.example.com" not in combined
    assert "workflow.png" not in combined
    assert "token%3Dabc123" not in combined
    assert "contact support" not in combined.lower()


def test_build_prompt_messages_preserves_short_cta_and_pricing_evidence():
    page = extract_script.RawPage(
        id=15,
        competitor_id=2,
        competitor_name="Acme",
        source_type="pricing",
        url="https://example.com/pricing",
        title="Pricing",
        word_count=250,
        markdown=(
            "# Pricing\n"
            "Book demo\n"
            "Contact sales\n"
            "Start free\n"
            "https://cdn.example.com/assets/pricing-card.png?token=abc123\n"
        ),
    )

    messages = extract_script.build_prompt_messages(page)
    combined = "\n".join(message["content"] for message in messages)

    assert "Book demo" in combined
    assert "Contact sales" in combined
    assert "Start free" in combined
    assert "pricing-card.png" not in combined
    assert "token=abc123" not in combined


def test_build_prompt_messages_preserves_leading_numeric_evidence():
    page = extract_script.RawPage(
        id=16,
        competitor_id=2,
        competitor_name="Acme",
        source_type="pricing",
        url="https://example.com/pricing",
        title="Pricing",
        word_count=250,
        markdown=(
            "# Pricing\n"
            "30 days free\n"
            "24/7 support\n"
            "4K video exports\n"
            "2 seats included\n"
            "1. Book demo\n"
        ),
    )

    messages = extract_script.build_prompt_messages(page)
    combined = "\n".join(message["content"] for message in messages)

    assert "30 days free" in combined
    assert "24/7 support" in combined
    assert "4K video exports" in combined
    assert "2 seats included" in combined
    assert "1. Book demo" not in combined
    assert "Book demo" in combined


def test_extract_page_insight_logs_sanitizer_discard_audit(capsys):
    page = extract_script.RawPage(
        id=17,
        competitor_id=2,
        competitor_name="Acme",
        source_type="homepage",
        url="https://example.com",
        title="Home",
        word_count=250,
        markdown=(
            "Manual exports take hours for every revision.\n"
            "https://cdn.example.com/assets/noise.png?token=abc123\n"
            "contact support\n"
        ),
    )
    client = FakeOpenAIClient()

    extract_script.extract_page_insight(client, page, "test-model")

    captured = capsys.readouterr().out
    assert "sanitizer_discard_audit" in captured
    assert '"raw_page_id": 17' in captured
    assert '"technical_fragment": 1' in captured
    assert '"support_boilerplate": 1' in captured
    assert "noise.png" not in captured
    assert "token=abc123" not in captured
    assert "contact support" not in captured


def test_pain_point_fixture_has_required_manual_annotations():
    examples = load_pain_point_examples()

    assert len(examples) == 20
    counts = {}
    for example in examples:
        counts[example["expected_evidence_type"]] = (
            counts.get(example["expected_evidence_type"], 0) + 1
        )
        for field_name in [
            "id",
            "expected_evidence_type",
            "expected_category",
            "markdown",
            "benefits",
            "expected_source_text_required",
        ]:
            assert field_name in example

    assert counts == {
        "explicit": 5,
        "inferred_from_benefit": 5,
        "keyword_fallback": 5,
        "not_pain_point": 5,
    }


def test_pain_point_fixture_classification_meets_quality_thresholds():
    results = pain_point_fixture_results()
    correct = [
        result
        for result in results
        if result["actual"]["evidence_type"]
        == result["example"]["expected_evidence_type"]
        and result["actual"]["category"] == result["example"]["expected_category"]
    ]
    explicit_results = [
        result
        for result in results
        if result["example"]["expected_evidence_type"] == "explicit"
    ]
    explicit_correct = [
        result
        for result in explicit_results
        if result["actual"]["evidence_type"] == "explicit"
        and result["actual"]["category"] == result["example"]["expected_category"]
    ]
    not_pain_results = [
        result
        for result in results
        if result["example"]["expected_evidence_type"] == "not_pain_point"
    ]
    not_pain_correct = [
        result
        for result in not_pain_results
        if result["actual"]["evidence_type"] == "not_pain_point"
    ]

    assert len(correct) >= 16
    assert len(explicit_correct) >= 4
    assert len(not_pain_correct) >= 4


def test_not_pain_point_fixture_examples_never_become_explicit():
    bad_results = [
        result
        for result in pain_point_fixture_results()
        if result["example"]["expected_evidence_type"] == "not_pain_point"
        and result["actual"]["evidence_type"] == "explicit"
    ]

    assert bad_results == []


def test_explicit_pain_point_outputs_require_source_text():
    for result in pain_point_fixture_results():
        actual = result["actual"]
        if actual["evidence_type"] != "explicit":
            continue

        assert actual["source_text"]
        assert actual["source_text"] != "not_found"


def test_extract_cta_object_field_ignores_not_found_values():
    ctas = [
        {"text": "Book demo", "cta_class": "primary", "target": "not_found"},
        {"text": " ", "cta_class": "not_found", "target": "/demo"},
        "Legacy CTA",
    ]

    assert extract_script.extract_cta_object_field(ctas, "text") == [
        "Book demo",
        "Legacy CTA",
    ]
    assert extract_script.extract_cta_object_field(ctas, "cta_class") == ["primary"]
    assert extract_script.extract_cta_object_field(ctas, "target") == ["/demo"]


def test_clean_pricing_model_removes_pricing_link_speculation():
    assert (
        extract_script.clean_pricing_model(
            "Free 7-day trial available; specific pricing details are accessible via links."
        )
        == "Free 7-day trial available"
    )
    assert (
        extract_script.clean_pricing_model(
            "30 days free trial available, with further details under 'Pricing' (not explicitly mentioned on the homepage)."
        )
        == "30 days free trial available"
    )
    assert extract_script.clean_pricing_model("Specific pricing details are accessible via links.") == "not_found"
    assert (
        extract_script.clean_pricing_model("not_found", "Create more. Get 30 days for free.")
        == "30-day free trial"
    )


def test_clean_objections_handled_removes_inferred_user_concerns():
    assert extract_script.clean_objections_handled(
        [
            "Concerns about time-consuming manual processes are addressed by automation.",
            "No scripting required.",
        ],
        "No scripting required. No learning curve.",
    ) == ["No scripting required."]
    assert extract_script.clean_objections_handled(
        ["No manual cleanup.", "No scripting required."],
        "No scripting required.",
    ) == ["No scripting required."]


def test_process_pages_continues_after_llm_failure(monkeypatch):
    pages = [
        extract_script.RawPage(
            id=1,
            competitor_id=2,
            competitor_name="Acme",
            source_type="homepage",
            url="https://example.com",
            title=None,
            word_count=200,
            markdown="First page",
        ),
        extract_script.RawPage(
            id=2,
            competitor_id=2,
            competitor_name="Acme",
            source_type="pricing",
            url="https://example.com/pricing",
            title=None,
            word_count=220,
            markdown="Second page",
        ),
    ]
    engine = FakeEngine()

    def fake_extract(client, page, model):
        if page.id == 1:
            raise RuntimeError("LLM unavailable")

        return extract_script.PageInsightExtraction(summary="ok")

    monkeypatch.setattr(extract_script, "extract_page_insight", fake_extract)
    args = extract_script.parse_args([])

    summary = extract_script.process_pages(engine, FakeClient(), pages, args)

    assert summary.failed == 1
    assert summary.extracted == 1
    assert len(engine.connections) == 1


def test_compatibility_wrapper_delegates_to_canonical_script(monkeypatch):
    wrapper_path = REPO_ROOT / "scripts" / "03_extract_insights.py"
    wrapper_spec = importlib.util.spec_from_file_location("extract_wrapper", wrapper_path)
    wrapper = importlib.util.module_from_spec(wrapper_spec)
    sys.modules["extract_wrapper"] = wrapper
    wrapper_spec.loader.exec_module(wrapper)

    called = {}

    def fake_main(argv=None):
        called["argv"] = argv

    real_module_from_spec = importlib.util.module_from_spec

    def fake_module_from_spec(spec):
        if spec.name == "extract_insights_02":
            return SimpleNamespace(main=fake_main)

        return real_module_from_spec(spec)

    class FakeLoader:
        def exec_module(self, module):
            return None

    class FakeSpec:
        name = "extract_insights_02"
        loader = FakeLoader()

    monkeypatch.setattr(importlib.util, "spec_from_file_location", lambda *_: FakeSpec())
    monkeypatch.setattr(importlib.util, "module_from_spec", fake_module_from_spec)

    wrapper.main(["--limit", "2"])

    assert called["argv"] == ["--limit", "2"]
