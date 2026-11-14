import importlib.util
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "03_topic_modeling.py"
TOPIC_TAXONOMY_PATH = REPO_ROOT / "config" / "content_topics.yml"
REQUIRED_CONTROLLED_TOPIC_IDS = {
    "bounce_automation",
    "licensing_model",
    "workflow_efficiency",
    "pricing_strategy",
    "support_documentation",
    "unknown_other",
}

sys.path.insert(0, str(REPO_ROOT / "scripts"))
spec = importlib.util.spec_from_file_location("topic_modeling", SCRIPT_PATH)
topic_modeling = importlib.util.module_from_spec(spec)
sys.modules["topic_modeling"] = topic_modeling
spec.loader.exec_module(topic_modeling)


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


class FakeContext:
    def __init__(self, connection):
        self.connection = connection

    def __enter__(self):
        return self.connection

    def __exit__(self, exc_type, exc, traceback):
        return False


class FakeEngine:
    def __init__(self, rows=None):
        self.connect_connection = FakeConnection(rows)
        self.begin_connection = FakeConnection()

    def connect(self):
        return FakeContext(self.connect_connection)

    def begin(self):
        return FakeContext(self.begin_connection)


class FakeTopicModel:
    def __init__(self, topics=None):
        self.topics = topics or {
            0: [("pricing", 0.5), ("automation", 0.3), ("analytics", 0.2)],
            1: [("security", 0.6), ("governance", 0.4)],
        }

    def get_topic(self, topic_id):
        return self.topics.get(topic_id)


class ToListWrapper:
    def __init__(self, value):
        self.value = value

    def tolist(self):
        return self.value


def test_parse_args_defaults_and_validation():
    args = topic_modeling.parse_args([])

    assert args.min_words == 150
    assert args.limit is None
    assert args.force is False

    with pytest.raises(SystemExit):
        topic_modeling.parse_args(["--min-words", "0"])

    with pytest.raises(SystemExit):
        topic_modeling.parse_args(["--limit", "-1"])


def test_build_raw_page_query_filters_eligible_pages_without_force():
    args = topic_modeling.parse_args(["--min-words", "200", "--limit", "10"])

    statement, params = topic_modeling.build_raw_page_query(args)
    sql = str(statement)

    assert "rp.success = TRUE" in sql
    assert "rp.markdown IS NOT NULL" in sql
    assert "btrim(rp.markdown) <> ''" in sql
    assert "rp.word_count >= :min_words" in sql
    assert "NOT EXISTS" in sql
    assert "topic_documents td" in sql
    assert "LIMIT :limit" in sql
    assert params == {"min_words": 200, "limit": 10}


def test_build_raw_page_query_uses_valid_asset_layer_for_topic_eligibility():
    args = topic_modeling.parse_args(["--min-words", "200"])

    statement, params = topic_modeling.build_raw_page_query(args)
    sql = str(statement).lower()

    assert "v_content_asset_validity" in sql, (
        "topic modeling eligibility must use the validity layer so 404, "
        "placeholder, thin, and non-evaluable pages cannot become topic documents"
    )
    assert re.search(r"is_valid_content_asset\s*=\s*true", sql), (
        "topic modeling must filter to valid analytical assets"
    )
    assert "rp.word_count >= :min_words" in sql, (
        "topic modeling must keep the existing minimum-word threshold"
    )
    assert params == {"min_words": 200}


def test_build_raw_page_query_includes_existing_topics_with_force():
    args = topic_modeling.parse_args(["--force"])

    statement, params = topic_modeling.build_raw_page_query(args)

    assert "NOT EXISTS" not in str(statement)
    assert params == {"min_words": 150}


def test_controlled_topic_taxonomy_config_exists_outside_script():
    assert TOPIC_TAXONOMY_PATH.exists(), (
        "controlled topic taxonomy must live in config/content_topics.yml, "
        "not only inside scripts/03_topic_modeling.py"
    )


def test_load_topic_taxonomy_schema_and_required_mvp_topics():
    assert hasattr(topic_modeling, "load_topic_taxonomy"), (
        "scripts/03_topic_modeling.py must expose load_topic_taxonomy(path=None)"
    )

    taxonomy = topic_modeling.load_topic_taxonomy(TOPIC_TAXONOMY_PATH)
    topic_ids = {topic["id"] for topic in taxonomy}
    strategic_topics = topic_ids - {"unknown_other"}

    assert topic_ids == REQUIRED_CONTROLLED_TOPIC_IDS
    assert len(strategic_topics) <= 5
    for topic in taxonomy:
        for field_name in [
            "id",
            "label",
            "description",
            "seed_terms",
            "positive_examples",
            "negative_examples",
        ]:
            assert topic.get(field_name), f"{topic.get('id')} missing {field_name}"
        assert isinstance(topic["seed_terms"], list)
        assert isinstance(topic["positive_examples"], list)
        assert isinstance(topic["negative_examples"], list)


def test_controlled_topic_classifier_keeps_insufficient_evidence_unknown_other():
    assert hasattr(topic_modeling, "classify_controlled_topics"), (
        "scripts/03_topic_modeling.py must expose classify_controlled_topics"
    )
    taxonomy = topic_modeling.load_topic_taxonomy(TOPIC_TAXONOMY_PATH)
    page = topic_modeling.RawPage(
        id=91,
        competitor_id=7,
        url="https://example.com/generic",
        title="Overview",
        word_count=240,
        markdown="Create more with a flexible platform for modern audio teams.",
        source_type="homepage",
    )

    assignments = topic_modeling.classify_controlled_topics(page, taxonomy)

    assert len(assignments) == 1
    assignment = assignments[0]
    assert assignment.topic_id == "unknown_other"
    assert assignment.topic_confidence == "low"
    assert "insufficient evidence" in assignment.assignment_reason.lower()


def test_controlled_topic_classifier_assigns_required_topics_from_clear_evidence():
    taxonomy = topic_modeling.load_topic_taxonomy(TOPIC_TAXONOMY_PATH)
    examples = {
        "bounce_automation": "Batch bounce stems, automate exports, and prepare deliverables from Pro Tools sessions.",
        "licensing_model": "Compare subscription seats, license activation, renewal options, and studio plan limits.",
        "workflow_efficiency": "Reduce manual session prep, repetitive cleanup, handoffs, and review workflow delays.",
        "pricing_strategy": "Pricing tiers, free trial terms, monthly plans, and enterprise quotes are explained.",
        "support_documentation": "Documentation, support guides, install instructions, and troubleshooting help are available.",
    }

    for expected_topic_id, markdown in examples.items():
        page = topic_modeling.RawPage(
            id=100,
            competitor_id=7,
            url=f"https://example.com/{expected_topic_id}",
            title=expected_topic_id,
            word_count=260,
            markdown=markdown,
            source_type="product",
        )
        assignments = topic_modeling.classify_controlled_topics(page, taxonomy)
        assigned_ids = {assignment.topic_id for assignment in assignments}

        assert expected_topic_id in assigned_ids


def test_bertopic_diagnostic_label_helpers_remain_available():
    model = FakeTopicModel(
        topics={0: [("download", 0.9), ("audio", 0.8), ("tracks", 0.7)]}
    )

    assert topic_modeling.build_topic_label(model, 0) == "download / audio / tracks"


def test_fetch_raw_pages_maps_database_rows():
    connection = FakeConnection(
        [
            FakeRow(
                raw_page_id=4,
                competitor_id=2,
                url="https://example.com",
                title="Home",
                word_count=350,
                markdown="# Home\nMessaging",
                has_existing_topic=True,
            )
        ]
    )

    pages = topic_modeling.fetch_raw_pages(connection, topic_modeling.parse_args([]))

    assert pages == [
        topic_modeling.RawPage(
            id=4,
            competitor_id=2,
            url="https://example.com",
            title="Home",
            word_count=350,
            markdown="# Home\nMessaging",
            has_existing_topic=True,
        )
    ]


def test_build_topic_label_uses_top_terms_and_outlier_label():
    model = FakeTopicModel()

    assert topic_modeling.build_topic_label(model, 0) == "pricing / automation / analytics"
    assert topic_modeling.build_topic_label(model, 1) == "security / governance"
    assert topic_modeling.build_topic_label(model, -1) == "Outlier"
    assert topic_modeling.build_topic_label(model, 99) == "Topic 99 [low confidence]"


def test_extract_topic_probability_handles_scalar_vectors_and_array_like_values():
    assert topic_modeling.extract_topic_probability([0.2, 0.8], 1, 1) == 0.8
    assert topic_modeling.extract_topic_probability([[0.1, 0.7], [0.8, 0.2]], 0, 0) == 0.7
    assert (
        topic_modeling.extract_topic_probability(
            ToListWrapper([[0.3, 0.4], [0.9, 0.1]]),
            1,
            1,
        )
        == 0.9
    )
    assert topic_modeling.extract_topic_probability(None, 0, 0) is None


def test_build_topic_assignments_maps_pages_topics_labels_and_probabilities():
    pages = [
        topic_modeling.RawPage(1, 10, "https://a.example", None, 200, "alpha"),
        topic_modeling.RawPage(2, 11, "https://b.example", "B", 210, "beta"),
    ]

    assignments = topic_modeling.build_topic_assignments(
        pages,
        [0, -1],
        [[0.1, 0.9], [0.6, 0.4]],
        FakeTopicModel(),
    )

    assert assignments == [
        topic_modeling.TopicAssignment(1, 10, 0, "pricing / automation / analytics", 0.9),
        topic_modeling.TopicAssignment(2, 11, -1, "Outlier", 0.6),
    ]


def test_run_small_dataset_exits_cleanly_without_modeling(monkeypatch, capsys):
    rows = [
        FakeRow(
            raw_page_id=1,
            competitor_id=2,
            url="https://example.com/1",
            title=None,
            word_count=200,
            markdown="one",
            has_existing_topic=False,
        )
    ]
    engine = FakeEngine(rows)
    monkeypatch.setattr(topic_modeling, "get_engine", lambda: engine)
    monkeypatch.setattr(topic_modeling, "fetch_competitor_info", lambda conn: ([], []))

    def fail_fit_topics(pages, label_stopwords=frozenset()):
        raise AssertionError("fit_topics should not be called for small datasets")

    monkeypatch.setattr(topic_modeling, "fit_topics", fail_fit_topics)

    summary = topic_modeling.run(topic_modeling.parse_args([]))

    captured = capsys.readouterr()
    assert "Topic modeling skipped" in captured.out
    assert summary.eligible_documents == 1
    assert summary.inserted_documents == 0
    assert summary.skipped_documents == 1
    assert engine.begin_connection.calls == []


def test_run_saves_assignments_for_enough_documents(monkeypatch):
    rows = [
        FakeRow(
            raw_page_id=index,
            competitor_id=2,
            url=f"https://example.com/{index}",
            title=None,
            word_count=200,
            markdown=f"document {index}",
            has_existing_topic=False,
        )
        for index in range(1, 6)
    ]
    engine = FakeEngine(rows)
    monkeypatch.setattr(topic_modeling, "get_engine", lambda: engine)
    monkeypatch.setattr(topic_modeling, "fetch_competitor_info", lambda conn: ([], []))
    monkeypatch.setattr(
        topic_modeling,
        "fit_topics",
        lambda pages, label_stopwords=frozenset(): [
            topic_modeling.TopicAssignment(page.id, page.competitor_id, 0, "pricing", 0.7)
            for page in pages
        ],
    )

    summary = topic_modeling.run(topic_modeling.parse_args([]))

    insert_calls = [
        call for call in engine.begin_connection.calls if "INSERT INTO topic_documents" in call[0]
    ]
    delete_calls = [
        call for call in engine.begin_connection.calls if "DELETE FROM topic_documents" in call[0]
    ]

    assert summary.inserted_documents == 5
    assert len(insert_calls) == 5
    assert delete_calls == []
    assert insert_calls[0][1]["raw_page_id"] == 1
    assert insert_calls[0][1]["topic_label"] == "pricing"
    assert insert_calls[0][1]["topic_probability"] == 0.7
    assert insert_calls[0][1]["funnel_stage"] == "unknown"


def test_save_topic_documents_deletes_existing_rows_when_forced():
    connection = FakeConnection()
    assignments = [
        topic_modeling.TopicAssignment(3, 4, 1, "security / governance", 0.8)
    ]

    topic_modeling.save_topic_documents(connection, assignments, force=True)

    delete_sql, delete_params = connection.calls[0]
    insert_sql, insert_params = connection.calls[1]

    assert "DELETE FROM topic_documents" in delete_sql
    assert delete_params == {"raw_page_id": 3}
    assert "INSERT INTO topic_documents" in insert_sql
    assert insert_params == {
        "raw_page_id": 3,
        "competitor_id": 4,
        "topic_id": 1,
        "topic_label": "security / governance",
        "topic_probability": 0.8,
        "funnel_stage": "unknown",
    }


def test_build_label_stopwords_contains_page_type_and_url_tokens():
    stopwords = topic_modeling.build_label_stopwords()

    for token in ("blog", "pricing", "homepage", "docs", "reviews", "comparison"):
        assert token in stopwords, f"expected page-type token {token!r} in stopwords"
    for token in ("www", "com", "https", "http"):
        assert token in stopwords, f"expected URL token {token!r} in stopwords"


def test_build_label_stopwords_includes_competitor_names():
    stopwords = topic_modeling.build_label_stopwords(competitor_names=["demo_owned", "demo-delta"])

    assert "demo_owned" in stopwords
    assert "demo-delta" in stopwords


def test_build_label_stopwords_extracts_tokens_from_competitor_urls():
    stopwords = topic_modeling.build_label_stopwords(
        competitor_urls=["https://www.demo_owned.com/", "https://demo-delta.org/"]
    )

    assert "demo_owned" in stopwords
    assert "demo-delta" in stopwords


def test_build_topic_label_filters_page_type_terms():
    model = FakeTopicModel(topics={
        0: [("pricing", 0.9), ("workflow", 0.7), ("automation", 0.4)],
    })
    stopwords = topic_modeling.PAGE_TYPE_STOPWORDS

    label = topic_modeling.build_topic_label(model, 0, label_stopwords=stopwords)

    assert "pricing" not in label
    assert "workflow" in label


def test_build_topic_label_filters_brand_name_terms():
    model = FakeTopicModel(topics={
        0: [("demo_owned", 0.9), ("automation", 0.7), ("workflow", 0.4)],
    })
    stopwords = frozenset({"demo_owned"})

    label = topic_modeling.build_topic_label(model, 0, label_stopwords=stopwords)

    assert "demo_owned" not in label
    assert "automation" in label


def test_build_topic_label_deduplicates_terms():
    model = FakeTopicModel(topics={
        0: [("workflow", 0.9), ("workflow", 0.5), ("automation", 0.3)],
    })

    label = topic_modeling.build_topic_label(model, 0)

    parts = label.split(" / ")
    assert len(parts) == len(set(parts)), f"duplicate terms in label: {label!r}"


def test_build_topic_label_marks_low_confidence_when_all_terms_removed():
    model = FakeTopicModel(topics={
        5: [("blog", 0.9), ("demo_owned", 0.8), ("pricing", 0.5)],
    })
    stopwords = frozenset({"blog", "demo_owned", "pricing"})

    label = topic_modeling.build_topic_label(model, 5, label_stopwords=stopwords)

    assert "[low confidence]" in label
    assert "5" in label


def test_build_topic_label_marks_low_confidence_for_only_url_and_page_type_terms():
    model = FakeTopicModel(topics={
        7: [("www", 0.9), ("com", 0.8), ("docs", 0.7), ("homepage", 0.6)],
    })
    stopwords = topic_modeling.build_label_stopwords()

    label = topic_modeling.build_topic_label(model, 7, label_stopwords=stopwords)

    assert label == "Topic 7 [low confidence]"


def test_build_topic_label_marks_audited_brand_entity_topics_low_confidence():
    model = FakeTopicModel(topics={
        8: [("bounce", 0.9), ("factory", 0.8), ("demo aurora", 0.7)],
        9: [("track", 0.9), ("macros", 0.8), ("barry", 0.7)],
    })
    stopwords = topic_modeling.build_label_stopwords()

    assert topic_modeling.build_topic_label(model, 8, label_stopwords=stopwords) == (
        "Topic 8 [low confidence]"
    )
    assert topic_modeling.build_topic_label(model, 9, label_stopwords=stopwords) == (
        "Topic 9 [low confidence]"
    )


def test_build_topic_label_fallback_filters_brand_from_title():
    model = FakeTopicModel(topics={
        3: [("blog", 0.9), ("demo_owned", 0.8)],
    })
    stopwords = frozenset({"blog", "demo_owned", "pricing", "homepage"})
    page = topic_modeling.RawPage(
        id=1, competitor_id=1,
        url="https://demo_owned.com/blog",
        title="demo_owned Blog",
        word_count=200,
        markdown="some content",
        source_type="blog",
    )

    label = topic_modeling.build_topic_label(model, 3, page=page, label_stopwords=stopwords)

    assert "[low confidence]" in label


def test_build_label_stopwords_returns_frozenset():
    result = topic_modeling.build_label_stopwords(
        competitor_names=["demo_owned"],
        competitor_urls=["https://www.demovendor.com/products/demo-cedro"],
    )

    assert isinstance(result, frozenset)
    assert "demo_owned" in result
    assert "demovendor" in result


def test_compatibility_wrapper_delegates_to_canonical_script(monkeypatch):
    wrapper_path = REPO_ROOT / "scripts" / "05_prepare_topics.py"
    wrapper_spec = importlib.util.spec_from_file_location("topics_wrapper", wrapper_path)
    wrapper = importlib.util.module_from_spec(wrapper_spec)
    sys.modules["topics_wrapper"] = wrapper
    wrapper_spec.loader.exec_module(wrapper)

    called = {}

    def fake_main(argv=None):
        called["argv"] = argv

    real_module_from_spec = importlib.util.module_from_spec

    def fake_module_from_spec(spec):
        if spec.name == "topic_modeling_03":
            return SimpleNamespace(main=fake_main)

        return real_module_from_spec(spec)

    class FakeLoader:
        def exec_module(self, module):
            return None

    class FakeSpec:
        name = "topic_modeling_03"
        loader = FakeLoader()

    monkeypatch.setattr(importlib.util, "spec_from_file_location", lambda *_: FakeSpec())
    monkeypatch.setattr(importlib.util, "module_from_spec", fake_module_from_spec)

    wrapper.main(["--limit", "2"])

    assert called["argv"] == ["--limit", "2"]
