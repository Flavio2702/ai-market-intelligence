import hashlib
import importlib.util
import sys
from types import SimpleNamespace
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "01_crawl.py"

sys.path.insert(0, str(REPO_ROOT / "scripts"))
spec = importlib.util.spec_from_file_location("crawl_script", SCRIPT_PATH)
crawl_script = importlib.util.module_from_spec(spec)
sys.modules["crawl_script"] = crawl_script
spec.loader.exec_module(crawl_script)


class FakeRow:
    def __init__(self, **values):
        self._mapping = values


class FakeConnection:
    def __init__(self, rows=None, rowcount=1, existing_raw_page=False):
        self.rows = rows or []
        self.calls = []
        self.rowcount = rowcount
        self.existing_raw_page = existing_raw_page

    def execute(self, statement, params=None):
        sql = str(statement)
        self.calls.append((sql, params or {}))
        if "SELECT 1" in sql and "FROM raw_pages" in sql:
            return [object()] if self.existing_raw_page else []
        if self.rows:
            return self.rows
        return type("FakeResult", (), {"rowcount": self.rowcount})()


def test_parse_args_accepts_filters():
    args = crawl_script.parse_args(
        ["--limit", "3", "--competitor", "Acme", "--source-type", "pricing"]
    )

    assert args.limit == 3
    assert args.competitor == "Acme"
    assert args.source_type == "pricing"


def test_build_source_url_query_filters_active_joined_urls():
    args = crawl_script.parse_args(
        ["--limit", "5", "--competitor", "Acme", "--source-type", "pricing"]
    )

    statement, params = crawl_script.build_source_url_query(args)
    sql = str(statement)

    assert "FROM source_urls su" in sql
    assert "JOIN competitors c ON c.id = su.competitor_id" in sql
    assert "su.active = TRUE" in sql
    assert "c.name = :competitor" in sql
    assert "su.source_type = :source_type" in sql
    assert "LIMIT :limit" in sql
    assert params == {
        "competitor": "Acme",
        "source_type": "pricing",
        "limit": 5,
    }


def test_compatibility_wrapper_delegates_to_canonical_script(monkeypatch):
    wrapper_path = REPO_ROOT / "scripts" / "02_crawl_pages.py"
    wrapper_spec = importlib.util.spec_from_file_location("crawl_wrapper", wrapper_path)
    wrapper = importlib.util.module_from_spec(wrapper_spec)
    sys.modules["crawl_wrapper"] = wrapper
    wrapper_spec.loader.exec_module(wrapper)

    called = {}

    def fake_main(argv=None):
        called["argv"] = argv

    real_module_from_spec = importlib.util.module_from_spec

    def fake_module_from_spec(spec):
        if spec.name == "crawl_01":
            return SimpleNamespace(main=fake_main)

        return real_module_from_spec(spec)

    class FakeLoader:
        def exec_module(self, module):
            return None

    class FakeSpec:
        name = "crawl_01"
        loader = FakeLoader()

    monkeypatch.setattr(importlib.util, "spec_from_file_location", lambda *_: FakeSpec())
    monkeypatch.setattr(importlib.util, "module_from_spec", fake_module_from_spec)

    wrapper.main(["--limit", "2"])

    assert called["argv"] == ["--limit", "2"]


def test_fetch_source_urls_maps_database_rows():
    connection = FakeConnection(
        [
            FakeRow(
                source_url_id=7,
                competitor_id=2,
                competitor_name="Acme",
                url="https://example.com/pricing",
                source_type="pricing",
            )
        ]
    )

    sources = crawl_script.fetch_source_urls(connection, crawl_script.parse_args([]))

    assert sources == [
        crawl_script.SourceUrl(
            id=7,
            competitor_id=2,
            competitor_name="Acme",
            url="https://example.com/pricing",
            source_type="pricing",
        )
    ]


def test_prepare_page_content_counts_words_and_hashes_markdown():
    content = crawl_script.prepare_page_content("  Hello market intelligence  ")

    assert content.markdown == "Hello market intelligence"
    assert content.word_count == 3
    assert content.content_hash == hashlib.sha256(
        b"Hello market intelligence"
    ).hexdigest()


def test_ensure_crawl4ai_base_directory_defaults_to_repo_root(monkeypatch):
    monkeypatch.delenv("CRAWL4_AI_BASE_DIRECTORY", raising=False)

    base_directory = crawl_script.ensure_crawl4ai_base_directory()

    assert base_directory == REPO_ROOT
    assert (REPO_ROOT / ".crawl4ai").exists()


def test_save_raw_page_inserts_success_record():
    connection = FakeConnection()
    source = crawl_script.SourceUrl(
        id=1,
        competitor_id=2,
        competitor_name="Acme",
        url="https://example.com",
        source_type="homepage",
    )

    saved = crawl_script.save_raw_page(
        connection,
        source,
        markdown="A useful page",
        title="Example",
        success=True,
    )

    assert saved is True
    sql, params = connection.calls[1]
    assert "INSERT INTO raw_pages" in sql
    assert params["source_url_id"] == 1
    assert params["competitor_id"] == 2
    assert params["url"] == "https://example.com"
    assert params["markdown"] == "A useful page"
    assert params["title"] == "Example"
    assert params["word_count"] == 3
    assert params["content_hash"] == hashlib.sha256(b"A useful page").hexdigest()
    assert params["success"] is True
    assert params["error_message"] is None


def test_save_raw_page_inserts_failure_record():
    connection = FakeConnection()
    source = crawl_script.SourceUrl(
        id=1,
        competitor_id=2,
        competitor_name="Acme",
        url="https://example.com",
        source_type="homepage",
    )

    saved = crawl_script.save_raw_page(
        connection,
        source,
        success=False,
        error_message="Timeout",
    )

    assert saved is True
    _, params = connection.calls[0]
    assert params["markdown"] is None
    assert params["word_count"] == 0
    assert params["content_hash"] is None
    assert params["success"] is False
    assert params["error_message"] == "Timeout"


def test_save_raw_page_skips_duplicate_success_record():
    connection = FakeConnection(existing_raw_page=True)
    source = crawl_script.SourceUrl(
        id=1,
        competitor_id=2,
        competitor_name="Acme",
        url="https://example.com",
        source_type="homepage",
    )

    saved = crawl_script.save_raw_page(
        connection,
        source,
        markdown="A useful page",
        title="Example",
        success=True,
    )

    assert saved is False
    assert len(connection.calls) == 1


def test_save_raw_page_skips_empty_success_record():
    connection = FakeConnection()
    source = crawl_script.SourceUrl(
        id=1,
        competitor_id=2,
        competitor_name="Acme",
        url="https://example.com",
        source_type="homepage",
    )

    saved = crawl_script.save_raw_page(
        connection,
        source,
        markdown="   ",
        success=True,
    )

    assert saved is False
    assert connection.calls == []
