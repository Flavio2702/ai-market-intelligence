"""Run the local MVP market intelligence pipeline in order."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
REPORT_PATH_PATTERN = re.compile(r"^Report written:\s*(?P<path>.+?)\s*$", re.MULTILINE)


def configure_output_encoding() -> None:
    """Keep relayed child-process output printable on Windows consoles."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


@dataclass(frozen=True)
class Stage:
    name: str
    script_name: str
    args: tuple[str, ...] = ()

    @property
    def script_path(self) -> Path:
        return SCRIPTS_DIR / self.script_name


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run the local AI market intelligence MVP pipeline. The default run "
            "initializes the schema, loads CSVs, crawls, extracts, models topics, "
            "computes KPIs, refreshes Superset views, and writes a Markdown report."
        )
    )
    parser.add_argument(
        "--crawl-limit",
        type=positive_int,
        help="Maximum URLs to crawl. Recommended first experiment: 15.",
    )
    parser.add_argument(
        "--extract-limit",
        type=positive_int,
        help=(
            "Maximum crawled pages to extract insights from. Each eligible page can "
            "call OpenAI; recommended first experiment: 15."
        ),
    )
    parser.add_argument(
        "--skip-crawl",
        action="store_true",
        help="Skip crawling and use existing raw_pages records.",
    )
    parser.add_argument(
        "--skip-extraction",
        action="store_true",
        help="Skip OpenAI extraction and use existing page_insights records.",
    )
    parser.add_argument(
        "--skip-topics",
        action="store_true",
        help="Skip BERTopic topic modeling. Useful when the corpus is still small.",
    )
    parser.add_argument(
        "--use-llm-summary",
        action="store_true",
        help=(
            "Ask OpenAI to polish the report executive summary from database facts "
            "only. Requires OPENAI_API_KEY."
        ),
    )
    return parser.parse_args(argv)


def build_stages(args: argparse.Namespace) -> list[Stage]:
    stages = [
        Stage("Database schema initialization", "init_db.py"),
        Stage("CSV input load", "00_load_inputs.py"),
    ]

    if not args.skip_crawl:
        crawl_args: list[str] = []
        if args.crawl_limit is not None:
            crawl_args.extend(["--limit", str(args.crawl_limit)])
        stages.append(Stage("Crawling", "01_crawl.py", tuple(crawl_args)))

    if not args.skip_extraction:
        extraction_args: list[str] = []
        if args.extract_limit is not None:
            extraction_args.extend(["--limit", str(args.extract_limit)])
        stages.append(
            Stage(
                "OpenAI extraction",
                "02_extract_insights.py",
                tuple(extraction_args),
            )
        )

    if not args.skip_topics:
        stages.append(Stage("Topic modeling", "03_topic_modeling.py"))

    stages.append(Stage("KPI computation", "04_compute_kpis.py"))
    stages.append(Stage("Superset view refresh", "refresh_views.py"))

    report_args: list[str] = []
    if args.use_llm_summary:
        report_args.append("--use-llm-summary")
    stages.append(Stage("Report generation", "05_generate_report.py", tuple(report_args)))

    return stages


def build_stage_command(stage: Stage) -> list[str]:
    return [sys.executable, str(stage.script_path), *stage.args]


def format_command(command: list[str]) -> str:
    return " ".join(command)


def run_stage(stage: Stage) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PYTHONUTF8", "1")
    return subprocess.run(
        build_stage_command(stage),
        cwd=REPO_ROOT,
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )


def echo_stage_output(result: subprocess.CompletedProcess[str]) -> None:
    if result.stdout:
        print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
    if result.stderr:
        print(result.stderr, file=sys.stderr, end="" if result.stderr.endswith("\n") else "\n")


def extract_report_path(output: str) -> str | None:
    match = REPORT_PATH_PATTERN.search(output)
    if not match:
        return None
    return match.group("path")


def build_failure_hint(stage: Stage, output: str) -> str | None:
    lowered = output.lower()

    if "database_url" in lowered or "could not connect" in lowered or "connection refused" in lowered:
        return (
            "Hint: verify PostgreSQL is running, the target database exists, and "
            "DATABASE_URL in .env has the right user, password, host, port, and database."
        )

    if stage.script_name == "01_crawl.py":
        if "crawl4ai" in lowered or "browser" in lowered or "playwright" in lowered:
            return (
                "Hint: verify Crawl4AI and its browser/runtime dependencies are "
                "installed. Also check that selected URLs are reachable and not blocked by robots.txt."
            )

    if stage.script_name == "02_extract_insights.py":
        if "openai_api_key" in lowered or "api key" in lowered:
            return (
                "Hint: set OPENAI_API_KEY in .env before extraction. Use "
                "--extract-limit on first runs to control API spend."
            )

    if stage.script_name == "03_topic_modeling.py" and "at least 5" in lowered:
        return (
            "Hint: BERTopic needs at least five eligible documents. Add or crawl "
            "more pages with enough text, then rerun the pipeline."
        )

    if stage.script_name == "refresh_views.py":
        return (
            "Hint: Superset views are refreshed from sql/views.sql. Verify the "
            "schema was initialized and PostgreSQL accepts the DATABASE_URL connection."
        )

    return None


def run_pipeline(args: argparse.Namespace) -> str | None:
    stages = build_stages(args)
    report_path: str | None = None

    for index, stage in enumerate(stages, start=1):
        print(f"\n=== {index}/{len(stages)} {stage.name} ===")
        print(f"$ {format_command(build_stage_command(stage))}")
        result = run_stage(stage)
        echo_stage_output(result)

        if result.returncode != 0:
            combined_output = f"{result.stdout}\n{result.stderr}"
            print(
                f"Pipeline failed during stage {index}/{len(stages)}: "
                f"{stage.name} ({stage.script_name}) exited with code "
                f"{result.returncode}.",
                file=sys.stderr,
            )
            hint = build_failure_hint(stage, combined_output)
            if hint:
                print(hint, file=sys.stderr)
            raise SystemExit(result.returncode)

        if stage.script_name == "05_generate_report.py":
            report_path = extract_report_path(result.stdout)

    if report_path:
        print(f"\nPipeline complete. Report: {report_path}")
    else:
        print("\nPipeline complete. Report: not reported by generator")
    return report_path


def main(argv: list[str] | None = None) -> None:
    configure_output_encoding()
    args = parse_args(argv)
    run_pipeline(args)


if __name__ == "__main__":
    main()
