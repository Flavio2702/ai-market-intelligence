import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "run_pipeline.py"

sys.path.insert(0, str(REPO_ROOT / "scripts"))
spec = importlib.util.spec_from_file_location("run_pipeline", SCRIPT_PATH)
run_pipeline = importlib.util.module_from_spec(spec)
sys.modules["run_pipeline"] = run_pipeline
spec.loader.exec_module(run_pipeline)


def completed(stdout="", stderr="", returncode=0):
    return subprocess.CompletedProcess(
        args=["python"],
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


def test_parse_args_defaults_and_positive_int_validation():
    args = run_pipeline.parse_args([])

    assert args.crawl_limit is None
    assert args.extract_limit is None
    assert args.skip_crawl is False
    assert args.skip_extraction is False
    assert args.skip_topics is False
    assert args.use_llm_summary is False

    with pytest.raises(SystemExit):
        run_pipeline.parse_args(["--crawl-limit", "0"])

    with pytest.raises(SystemExit):
        run_pipeline.parse_args(["--extract-limit", "-1"])


def test_limits_are_passed_through_to_stage_scripts():
    args = run_pipeline.parse_args(["--crawl-limit", "5", "--extract-limit", "7"])

    stages = run_pipeline.build_stages(args)
    by_script = {stage.script_name: stage for stage in stages}

    assert by_script["01_crawl.py"].args == ("--limit", "5")
    assert by_script["02_extract_insights.py"].args == ("--limit", "7")


def test_skip_flags_remove_optional_stages():
    args = run_pipeline.parse_args(
        ["--skip-crawl", "--skip-extraction", "--skip-topics"]
    )

    scripts = [stage.script_name for stage in run_pipeline.build_stages(args)]

    assert scripts == [
        "init_db.py",
        "00_load_inputs.py",
        "04_compute_kpis.py",
        "refresh_views.py",
        "05_generate_report.py",
    ]


def test_default_stage_order_includes_init_and_view_refresh():
    scripts = [stage.script_name for stage in run_pipeline.build_stages(run_pipeline.parse_args([]))]

    assert scripts == [
        "init_db.py",
        "00_load_inputs.py",
        "01_crawl.py",
        "02_extract_insights.py",
        "03_topic_modeling.py",
        "04_compute_kpis.py",
        "refresh_views.py",
        "05_generate_report.py",
    ]


def test_nonzero_load_failure_stops_pipeline(monkeypatch, capsys):
    calls = []

    def fake_run_stage(stage):
        calls.append(stage.script_name)
        return completed(stdout="load failed\n", returncode=1)

    monkeypatch.setattr(run_pipeline, "run_stage", fake_run_stage)

    with pytest.raises(SystemExit) as exc_info:
        run_pipeline.run_pipeline(run_pipeline.parse_args([]))

    captured = capsys.readouterr()
    assert exc_info.value.code == 1
    assert calls == ["init_db.py"]
    assert "load failed" in captured.out
    assert (
        "Pipeline failed during stage 1/8: Database schema initialization "
        "(init_db.py) exited with code 1."
    ) in captured.err


def test_nonzero_crawl_failure_stops_pipeline(monkeypatch):
    calls = []

    def fake_run_stage(stage):
        calls.append(stage.script_name)
        if stage.script_name == "01_crawl.py":
            return completed(stderr="crawl exploded\n", returncode=2)
        return completed()

    monkeypatch.setattr(run_pipeline, "run_stage", fake_run_stage)

    with pytest.raises(SystemExit) as exc_info:
        run_pipeline.run_pipeline(run_pipeline.parse_args([]))

    assert exc_info.value.code == 2
    assert calls == ["init_db.py", "00_load_inputs.py", "01_crawl.py"]


def test_nonzero_extraction_failure_stops_pipeline(monkeypatch):
    calls = []

    def fake_run_stage(stage):
        calls.append(stage.script_name)
        if stage.script_name == "02_extract_insights.py":
            return completed(stderr="missing api key\n", returncode=3)
        return completed()

    monkeypatch.setattr(run_pipeline, "run_stage", fake_run_stage)

    with pytest.raises(SystemExit) as exc_info:
        run_pipeline.run_pipeline(run_pipeline.parse_args([]))

    assert exc_info.value.code == 3
    assert calls == [
        "init_db.py",
        "00_load_inputs.py",
        "01_crawl.py",
        "02_extract_insights.py",
    ]


def test_nonzero_topic_failure_stops_pipeline(monkeypatch):
    calls = []

    def fake_run_stage(stage):
        calls.append(stage.script_name)
        if stage.script_name == "03_topic_modeling.py":
            return completed(stderr="bertopic import failed\n", returncode=4)
        return completed()

    monkeypatch.setattr(run_pipeline, "run_stage", fake_run_stage)

    with pytest.raises(SystemExit) as exc_info:
        run_pipeline.run_pipeline(run_pipeline.parse_args([]))

    assert exc_info.value.code == 4
    assert calls == [
        "init_db.py",
        "00_load_inputs.py",
        "01_crawl.py",
        "02_extract_insights.py",
        "03_topic_modeling.py",
    ]


def test_nonzero_kpi_failure_stops_pipeline(monkeypatch):
    calls = []

    def fake_run_stage(stage):
        calls.append(stage.script_name)
        if stage.script_name == "04_compute_kpis.py":
            return completed(stderr="kpi sql failed\n", returncode=5)
        return completed()

    monkeypatch.setattr(run_pipeline, "run_stage", fake_run_stage)

    with pytest.raises(SystemExit) as exc_info:
        run_pipeline.run_pipeline(run_pipeline.parse_args(["--skip-topics"]))

    assert exc_info.value.code == 5
    assert calls == [
        "init_db.py",
        "00_load_inputs.py",
        "01_crawl.py",
        "02_extract_insights.py",
        "04_compute_kpis.py",
    ]


def test_nonzero_report_failure_stops_pipeline(monkeypatch):
    calls = []

    def fake_run_stage(stage):
        calls.append(stage.script_name)
        if stage.script_name == "05_generate_report.py":
            return completed(stderr="report query failed\n", returncode=6)
        return completed()

    monkeypatch.setattr(run_pipeline, "run_stage", fake_run_stage)

    with pytest.raises(SystemExit) as exc_info:
        run_pipeline.run_pipeline(run_pipeline.parse_args(["--skip-topics"]))

    assert exc_info.value.code == 6
    assert calls == [
        "init_db.py",
        "00_load_inputs.py",
        "01_crawl.py",
        "02_extract_insights.py",
        "04_compute_kpis.py",
        "refresh_views.py",
        "05_generate_report.py",
    ]


def test_clean_topic_skip_continues_to_report(monkeypatch, capsys):
    calls = []

    def fake_run_stage(stage):
        calls.append(stage.script_name)
        if stage.script_name == "03_topic_modeling.py":
            return completed(
                stdout=(
                    "Topic modeling skipped: found 1 eligible document(s), "
                    "but at least 5 are required.\n"
                )
            )
        if stage.script_name == "05_generate_report.py":
            return completed(stdout="Report written: outputs/reports/report.md\n")
        return completed()

    monkeypatch.setattr(run_pipeline, "run_stage", fake_run_stage)

    report_path = run_pipeline.run_pipeline(run_pipeline.parse_args([]))

    captured = capsys.readouterr()
    assert report_path == "outputs/reports/report.md"
    assert calls[-1] == "05_generate_report.py"
    assert "Topic modeling skipped" in captured.out
    assert "Pipeline complete. Report: outputs/reports/report.md" in captured.out


def test_failure_hint_for_missing_openai_key(monkeypatch, capsys):
    def fake_run_stage(stage):
        if stage.script_name == "02_extract_insights.py":
            return completed(stderr="OPENAI_API_KEY is required\n", returncode=3)
        return completed()

    monkeypatch.setattr(run_pipeline, "run_stage", fake_run_stage)

    with pytest.raises(SystemExit):
        run_pipeline.run_pipeline(run_pipeline.parse_args([]))

    captured = capsys.readouterr()
    assert "set OPENAI_API_KEY in .env" in captured.err


def test_run_stage_uses_current_python_without_shell(monkeypatch):
    observed = {}
    stage = run_pipeline.Stage("Load CSV inputs", "00_load_inputs.py")

    def fake_subprocess_run(command, **kwargs):
        observed["command"] = command
        observed["kwargs"] = kwargs
        return completed()

    monkeypatch.setattr(run_pipeline.subprocess, "run", fake_subprocess_run)

    run_pipeline.run_stage(stage)

    assert observed["command"] == [
        sys.executable,
        str(run_pipeline.SCRIPTS_DIR / "00_load_inputs.py"),
    ]
    assert observed["kwargs"]["cwd"] == run_pipeline.REPO_ROOT
    assert observed["kwargs"]["env"]["PYTHONIOENCODING"] == "utf-8"
    assert observed["kwargs"]["env"]["PYTHONUTF8"] == "1"
    assert observed["kwargs"]["encoding"] == "utf-8"
    assert observed["kwargs"]["errors"] == "replace"
    assert observed["kwargs"]["check"] is False
    assert "shell" not in observed["kwargs"]


def test_pipeline_prints_stage_command(monkeypatch, capsys):
    def fake_run_stage(stage):
        if stage.script_name == "05_generate_report.py":
            return completed(stdout="Report written: outputs/reports/report.md\n")
        return completed()

    monkeypatch.setattr(run_pipeline, "run_stage", fake_run_stage)

    run_pipeline.run_pipeline(
        run_pipeline.parse_args(
            ["--crawl-limit", "5", "--extract-limit", "5", "--skip-topics"]
        )
    )

    captured = capsys.readouterr()
    assert "=== 1/7 Database schema initialization ===" in captured.out
    assert "$ " in captured.out
    assert "01_crawl.py --limit 5" in captured.out
    assert "02_extract_insights.py --limit 5" in captured.out
