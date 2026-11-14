"""Compatibility wrapper for the canonical Crawl4AI crawler script."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> None:
    script_path = Path(__file__).with_name("01_crawl.py")
    spec = importlib.util.spec_from_file_location("crawl_01", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["crawl_01"] = module
    spec.loader.exec_module(module)
    module.main(argv)


if __name__ == "__main__":
    main()
