"""Compatibility wrapper for the canonical extraction script."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> None:
    script_path = Path(__file__).with_name("02_extract_insights.py")
    spec = importlib.util.spec_from_file_location("extract_insights_02", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["extract_insights_02"] = module
    spec.loader.exec_module(module)
    module.main(argv)


if __name__ == "__main__":
    main()
