import importlib.util
import sys
from datetime import date
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "check_data_quality.py"

sys.path.insert(0, str(REPO_ROOT / "scripts"))
spec = importlib.util.spec_from_file_location("check_data_quality", SCRIPT_PATH)
check_data_quality = importlib.util.module_from_spec(spec)
sys.modules["check_data_quality"] = check_data_quality
spec.loader.exec_module(check_data_quality)


class FakeResult:
    def __init__(self, value):
        self.value = value

    def scalar(self):
        return self.value


class FakeConnection:
    def __init__(self, values):
        self.values = values

    def execute(self, statement):
        sql = " ".join(str(statement).split()).lower()

        if "from competitors" in sql:
            return FakeResult(self.values["competitors"])
        if "from source_urls" in sql and "lower(source_type) = 'pricing'" in sql:
            return FakeResult(self.values["pricing_pages"])
        if "from source_urls" in sql:
            return FakeResult(self.values["source_urls"])
        if "from v_content_asset_validity" in sql and "has_insight = true" in sql:
            return FakeResult(self.values["valid_analytical_assets"])
        if "from v_content_asset_validity" in sql:
            return FakeResult(self.values["extraction_eligible_assets"])
        if "from page_insights pi" in sql and "is_valid_content_asset = false" in sql:
            return FakeResult(self.values["invalid_asset_insights"])
        if "from raw_pages" in sql and "success = true" in sql and "word_count" in sql:
            return FakeResult(self.values["short_raw_pages"])
        if "from raw_pages" in sql and "success = true" in sql:
            return FakeResult(self.values["successful_raw_pages"])
        if "from raw_pages" in sql and "success = false" in sql:
            return FakeResult(self.values["failed_raw_pages"])
        if "from page_insights" in sql:
            return FakeResult(self.values["extracted_insights"])
        if "from topic_documents" in sql:
            return FakeResult(self.values["topic_documents"])
        if "from kpi_competitor_daily" in sql:
            return FakeResult(self.values["latest_kpi_snapshot_date"])

        raise AssertionError(f"Unexpected SQL: {sql}")


def snapshot_values(**overrides):
    values = {
        "competitors": 3,
        "source_urls": 12,
        "successful_raw_pages": 10,
        "failed_raw_pages": 1,
        "short_raw_pages": 2,
        "extraction_eligible_assets": 10,
        "valid_analytical_assets": 8,
        "extracted_insights": 8,
        "invalid_asset_insights": 0,
        "topic_documents": 5,
        "latest_kpi_snapshot_date": date(2026, 4, 27),
        "pricing_pages": 1,
    }
    values.update(overrides)
    return values


def test_fetch_snapshot_maps_database_counts():
    snapshot = check_data_quality.fetch_snapshot(FakeConnection(snapshot_values()))

    assert snapshot.competitors == 3
    assert snapshot.source_urls == 12
    assert snapshot.successful_raw_pages == 10
    assert snapshot.failed_raw_pages == 1
    assert snapshot.short_raw_pages == 2
    assert snapshot.extraction_eligible_assets == 10
    assert snapshot.valid_analytical_assets == 8
    assert snapshot.extracted_insights == 8
    assert snapshot.invalid_asset_insights == 0
    assert snapshot.topic_documents == 5
    assert snapshot.latest_kpi_snapshot_date == date(2026, 4, 27)
    assert snapshot.pricing_pages == 1
    assert snapshot.extraction_coverage == 0.8


def test_print_report_includes_required_metric_labels(capsys):
    snapshot = check_data_quality.fetch_snapshot(FakeConnection(snapshot_values()))

    check_data_quality.print_report(snapshot)

    output = capsys.readouterr().out
    for label in [
        "competitors:",
        "source URLs:",
        "successful raw pages:",
        "failed raw pages:",
        "pages with word_count < 150:",
        "extraction-eligible assets:",
        "valid analytical assets:",
        "extracted insights:",
        "invalid-asset insights:",
        "topic documents:",
        "latest KPI snapshot date:",
    ]:
        assert label in output


def test_low_data_snapshot_emits_all_warning_types(capsys):
    snapshot = check_data_quality.fetch_snapshot(
        FakeConnection(
            snapshot_values(
                competitors=2,
                successful_raw_pages=9,
                extraction_eligible_assets=10,
                valid_analytical_assets=7,
                extracted_insights=7,
                topic_documents=0,
                pricing_pages=0,
                latest_kpi_snapshot_date=None,
            )
        )
    )

    check_data_quality.print_report(snapshot)

    output = capsys.readouterr().out
    assert "fewer than 3 competitors" in output
    assert "fewer than 10 successful pages" in output
    assert "valid analytical asset coverage below 80%" in output
    assert "no pricing pages" in output
    assert "no topic documents" in output
    assert "latest KPI snapshot date: not_available" in output


def test_healthy_snapshot_prints_no_warnings(capsys):
    snapshot = check_data_quality.fetch_snapshot(FakeConnection(snapshot_values()))

    check_data_quality.print_report(snapshot)

    output = capsys.readouterr().out
    assert "Warnings: none" in output
    assert "  -" not in output
