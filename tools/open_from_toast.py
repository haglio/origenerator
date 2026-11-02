from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from origenerator.app_link import follow

if __name__ == "__main__":
    raise SystemExit(follow(sys.argv[1:]))
