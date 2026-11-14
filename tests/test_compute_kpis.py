import importlib.util
import sys
from datetime import date
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "04_compute_kpis.py"

sys.path.insert(0, str(REPO_ROOT / "scripts"))
spec = importlib.util.spec_from_file_location("compute_kpis", SCRIPT_PATH)
compute_kpis = importlib.util.module_from_spec(spec)
sys.modules["compute_kpis"] = compute_kpis
spec.loader.exec_module(compute_kpis)


class FakeResult:
    def __init__(self, rowcount=0, scalar=None):
        self.rowcount = rowcount
        self.scalar = scalar

    def scalar_one(self):
        return self.scalar


class FakeConnection:
    def __init__(self):
        self.calls = []

    def execute(self, statement):
        sql = str(statement)
        self.calls.append(sql)

        if "INSERT INTO kpi_competitor_daily" in sql:
            return FakeResult(rowcount=3)

        if "SELECT CURRENT_DATE" in sql:
            return FakeResult(scalar=date(2026, 4, 27))

        raise AssertionError(f"Unexpected SQL: {sql}")


def test_compute_kpis_upserts_todays_snapshot():
    connection = FakeConnection()

    summary = compute_kpis.compute_kpis(connection)

    assert "INSERT INTO kpi_competitor_daily" in connection.calls[0]
    assert "ON CONFLICT (competitor_id, date) DO UPDATE" in connection.calls[0]
    assert summary.deleted_rows == 0
    assert summary.inserted_rows == 3
    assert summary.snapshot_date == "2026-04-27"


def test_insert_snapshot_sql_includes_required_kpi_aggregates():
    sql = str(compute_kpis.UPSERT_TODAYS_SNAPSHOTS_SQL)

    assert "raw_pages" in sql
    assert "success = TRUE" in sql
    assert "pages_analyzed counts pages that crawled OK" in sql
    assert "Valid analytical asset counts are exposed live through SQL views" in sql
    assert "COUNT(*) AS pages_analyzed" in sql
    assert "SUM(COALESCE(word_count, 0))" in sql
    assert "share_of_voice" in sql
    assert "sentiment = 'positive'" in sql
    assert "sentiment = 'negative'" in sql
    assert "pricing_model IS NOT NULL" in sql
    assert "jsonb_array_length(key_features)" in sql
    assert "NULLIF" in sql
    assert "EXCLUDED.pages_analyzed" in sql
