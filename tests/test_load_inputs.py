import importlib.util
import sys
from pathlib import Path

import pandas as pd
import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "00_load_inputs.py"

sys.path.insert(0, str(REPO_ROOT / "scripts"))
spec = importlib.util.spec_from_file_location("load_inputs", SCRIPT_PATH)
load_inputs = importlib.util.module_from_spec(spec)
sys.modules["load_inputs"] = load_inputs
spec.loader.exec_module(load_inputs)


class FakeRow:
    def __init__(self, **values):
        self._mapping = values


class FakeResult:
    def __init__(self, rows=None, rowcount=0):
        self.rows = rows or []
        self.rowcount = rowcount

    def __iter__(self):
        return iter(self.rows)


class FakeConnection:
    def __init__(self):
        self.competitors = {}
        self.competitor_owned_domains = {}
        self.source_urls = set()
        self.next_competitor_id = 1
        self.calls = []
        self.params_calls = []

    def execute(self, statement, params=None):
        sql = str(statement)
        params = params or {}
        self.calls.append(sql)
        self.params_calls.append(params)

        if "TRUNCATE page_insights" in sql:
            self.competitors.clear()
            self.competitor_owned_domains.clear()
            self.source_urls.clear()
            self.next_competitor_id = 1
            return FakeResult()

        if "SELECT name FROM competitors" in sql:
            rows = [
                FakeRow(name=name)
                for name in params["names"]
                if name in self.competitors
            ]
            return FakeResult(rows=rows)

        if "SELECT id, name FROM competitors" in sql:
            rows = [
                FakeRow(id=self.competitors[name], name=name)
                for name in params["names"]
                if name in self.competitors
            ]
            return FakeResult(rows=rows)

        if "INSERT INTO competitors" in sql:
            name = params["name"]
            if name in self.competitors:
                return FakeResult(rowcount=0)

            self.competitors[name] = self.next_competitor_id
            self.competitor_owned_domains[name] = bool(params.get("is_owned_domain"))
            self.next_competitor_id += 1
            return FakeResult(rowcount=1)

        if "SELECT competitor_id, url" in sql:
            if "competitor_ids" in params:
                rows = [
                    FakeRow(competitor_id=competitor_id, url=url)
                    for competitor_id, url in self.source_urls
                    if competitor_id in params["competitor_ids"] and url in params["urls"]
                ]
                return FakeResult(rows=rows)

            key = (params["competitor_id"], params["url"])
            if key in self.source_urls:
                return FakeResult(
                    rows=[
                        FakeRow(competitor_id=params["competitor_id"], url=params["url"])
                    ]
                )
            return FakeResult()

        if "INSERT INTO source_urls" in sql:
            key = (params["competitor_id"], params["url"])
            if key in self.source_urls:
                return FakeResult(rowcount=0)

            self.source_urls.add(key)
            return FakeResult(rowcount=1)

        raise AssertionError(f"Unexpected SQL: {sql}")


class FakeBegin:
    def __init__(self, connection):
        self.connection = connection

    def __enter__(self):
        return self.connection

    def __exit__(self, exc_type, exc, traceback):
        return False


class FakeEngine:
    def __init__(self, connection):
        self.connection = connection

    def begin(self):
        return FakeBegin(self.connection)


def test_read_input_csv_requires_expected_headers(monkeypatch):
    monkeypatch.setattr(
        load_inputs.pd,
        "read_csv",
        lambda *args, **kwargs: pd.DataFrame(
            [{"name": "Example", "category": "Analytics"}]
        ),
    )

    with pytest.raises(load_inputs.InputLoadError, match="missing required column"):
        load_inputs.read_input_csv(REPO_ROOT, load_inputs.COMPETITOR_COLUMNS)


def test_validate_required_values_reports_blank_fields():
    dataframe = pd.DataFrame(
        [{"competitor_name": "Example", "url": "", "source_type": "homepage"}]
    )

    with pytest.raises(load_inputs.InputLoadError, match="urls.csv row 2"):
        load_inputs.validate_required_values(
            dataframe, load_inputs.REQUIRED_URL_FIELDS, "urls.csv"
        )


def test_duplicate_competitors_and_urls_are_counted_existing():
    connection = FakeConnection()
    competitors = pd.DataFrame(
        [
            {
                "name": "Example",
                "website": "https://example.com",
                "category": "Analytics",
                "country": "United States",
                "notes": "First row",
            },
            {
                "name": "Example",
                "website": "https://example.com",
                "category": "Analytics",
                "country": "United States",
                "notes": "Duplicate row",
            },
        ]
    )
    urls = pd.DataFrame(
        [
            {
                "competitor_name": "Example",
                "url": "https://example.com",
                "source_type": "homepage",
            },
            {
                "competitor_name": "Example",
                "url": "https://example.com",
                "source_type": "homepage",
            },
        ]
    )

    competitor_summary = load_inputs.load_competitors(connection, competitors)
    url_summary = load_inputs.load_source_urls(connection, urls)

    assert competitor_summary.competitors_inserted == 1
    assert competitor_summary.competitors_existing == 1
    assert url_summary.urls_inserted == 1
    assert url_summary.urls_existing == 1


def test_load_competitors_defaults_missing_owned_domain_false():
    connection = FakeConnection()
    competitors = pd.DataFrame(
        [
            {
                "name": "Example",
                "website": "https://example.com",
                "category": "Analytics",
                "country": "United States",
                "notes": "No owned column in fixture",
            }
        ]
    )

    summary = load_inputs.load_competitors(connection, competitors)

    assert summary.competitors_inserted == 1
    assert connection.competitor_owned_domains == {"Example": False}


def test_load_competitors_accepts_exactly_one_owned_domain():
    connection = FakeConnection()
    competitors = pd.DataFrame(
        [
            {
                "name": "Owned",
                "website": "https://owned.example",
                "category": "Analytics",
                "country": "Italy",
                "notes": "Owned domain",
                "is_owned_domain": "true",
            },
            {
                "name": "External",
                "website": "https://external.example",
                "category": "Analytics",
                "country": "United States",
                "notes": "External competitor",
                "is_owned_domain": "",
            },
        ]
    )

    summary = load_inputs.load_competitors(connection, competitors)

    assert summary.competitors_inserted == 2
    assert connection.competitor_owned_domains == {
        "Owned": True,
        "External": False,
    }


def test_load_inputs_rejects_multiple_owned_domains_before_dataset_reset(monkeypatch):
    competitors_path = Path("competitors.csv")
    urls_path = Path("urls.csv")
    competitors = pd.DataFrame(
        [
            {
                "name": "Owned One",
                "website": "https://owned-one.example",
                "category": "Analytics",
                "country": "Italy",
                "notes": "First owned row",
                "is_owned_domain": "true",
            },
            {
                "name": "Owned Two",
                "website": "https://owned-two.example",
                "category": "Analytics",
                "country": "United States",
                "notes": "Second owned row",
                "is_owned_domain": "yes",
            },
        ]
    )
    urls = pd.DataFrame(
        [
            {
                "competitor_name": "Owned One",
                "url": "https://owned-one.example",
                "source_type": "homepage",
            },
            {
                "competitor_name": "Owned Two",
                "url": "https://owned-two.example",
                "source_type": "homepage",
            },
        ]
    )

    def fake_read_input_csv(path, required_columns, optional_columns=None):
        if required_columns == load_inputs.COMPETITOR_COLUMNS:
            return competitors
        if required_columns == load_inputs.URL_COLUMNS:
            return urls
        raise AssertionError(f"Unexpected columns: {required_columns}")

    def fail_if_called():
        raise AssertionError(
            "database should not be opened before owned-domain validation"
        )

    monkeypatch.setattr(load_inputs, "read_input_csv", fake_read_input_csv)
    monkeypatch.setattr(load_inputs, "get_engine", fail_if_called)

    with pytest.raises(load_inputs.InputLoadError, match="owned domain"):
        load_inputs.load_inputs(competitors_path, urls_path)


def test_unknown_competitor_name_fails_clearly():
    connection = FakeConnection()
    urls = pd.DataFrame(
        [
            {
                "competitor_name": "Missing Competitor",
                "url": "https://example.com",
                "source_type": "homepage",
            }
        ]
    )

    with pytest.raises(load_inputs.InputLoadError, match="Missing Competitor"):
        load_inputs.load_source_urls(connection, urls)


def test_load_inputs_resets_dataset_after_validation_and_before_inserts(monkeypatch):
    competitors_path = Path("competitors.csv")
    urls_path = Path("urls.csv")
    competitors = pd.DataFrame(
        [
            {
                "name": "Fresh",
                "website": "https://fresh.example",
                "category": "Analytics",
                "country": "Italy",
                "notes": "New row",
            }
        ]
    )
    urls = pd.DataFrame(
        [
            {
                "competitor_name": "Fresh",
                "url": "https://fresh.example",
                "source_type": "homepage",
            }
        ]
    )
    connection = FakeConnection()
    connection.competitors = {"Stale": 42}
    connection.source_urls = {(42, "https://stale.example")}

    def fake_read_input_csv(path, required_columns):
        if required_columns == load_inputs.COMPETITOR_COLUMNS:
            return competitors
        if required_columns == load_inputs.URL_COLUMNS:
            return urls
        raise AssertionError(f"Unexpected columns: {required_columns}")

    monkeypatch.setattr(load_inputs, "read_input_csv", fake_read_input_csv)
    monkeypatch.setattr(load_inputs, "get_engine", lambda: FakeEngine(connection))

    summary = load_inputs.load_inputs(competitors_path, urls_path)

    truncate_index = next(
        index
        for index, sql in enumerate(connection.calls)
        if "TRUNCATE page_insights" in sql
    )
    first_insert_index = next(
        index
        for index, sql in enumerate(connection.calls)
        if "INSERT INTO competitors" in sql
    )
    assert truncate_index < first_insert_index
    assert connection.competitors == {"Fresh": 1}
    assert connection.source_urls == {(1, "https://fresh.example")}
    assert summary.dataset_reset is True
    assert summary.competitors_inserted == 1
    assert summary.urls_inserted == 1


def test_load_inputs_does_not_reset_dataset_when_csv_validation_fails(monkeypatch):
    competitors_path = Path("competitors.csv")
    urls_path = Path("urls.csv")
    competitors = pd.DataFrame(
        [
            {
                "name": "Fresh",
                "website": "https://fresh.example",
                "category": "Analytics",
                "country": "Italy",
                "notes": "New row",
            }
        ]
    )
    urls = pd.DataFrame(
        [{"competitor_name": "Fresh", "url": "https://fresh.example", "source_type": ""}]
    )

    def fake_read_input_csv(path, required_columns):
        if required_columns == load_inputs.COMPETITOR_COLUMNS:
            return competitors
        if required_columns == load_inputs.URL_COLUMNS:
            return urls
        raise AssertionError(f"Unexpected columns: {required_columns}")

    def fail_if_called():
        raise AssertionError("database should not be opened before CSV validation")

    monkeypatch.setattr(load_inputs, "read_input_csv", fake_read_input_csv)
    monkeypatch.setattr(load_inputs, "get_engine", fail_if_called)

    with pytest.raises(load_inputs.InputLoadError, match="urls.csv row 2"):
        load_inputs.load_inputs(competitors_path, urls_path)


def test_print_summary_includes_all_counts(capsys):
    summary = load_inputs.LoadSummary(
        competitors_inserted=1,
        competitors_existing=2,
        urls_inserted=3,
        urls_existing=4,
    )

    load_inputs.print_summary(summary)

    output = capsys.readouterr().out
    assert "competitors inserted: 1" in output
    assert "competitors already existing: 2" in output
    assert "URLs inserted: 3" in output
    assert "URLs already existing: 4" in output


def test_print_summary_reports_dataset_reset(capsys):
    summary = load_inputs.LoadSummary(dataset_reset=True)

    load_inputs.print_summary(summary)

    output = capsys.readouterr().out
    assert "previous dataset reset: yes" in output
