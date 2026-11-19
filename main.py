from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from poe_map_crafter.config import AppConfig  # noqa: E402
from poe_map_crafter.gui import run_gui  # noqa: E402


def main() -> None:
    config = AppConfig.load()
    run_gui(config)


if __name__ == "__main__":
    main()