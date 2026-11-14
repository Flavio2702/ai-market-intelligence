"""Compatibility wrapper for the canonical BERTopic topic modeling script."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> None:
    script_path = Path(__file__).with_name("03_topic_modeling.py")
    spec = importlib.util.spec_from_file_location("topic_modeling_03", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["topic_modeling_03"] = module
    spec.loader.exec_module(module)
    module.main(argv)


if __name__ == "__main__":
    main()
