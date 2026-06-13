"""Run the CE-SQL demo running example and print a JSON report."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cesql.core.pipeline import run_running_example


def main() -> None:
    result = run_running_example()
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
