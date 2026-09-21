"""What Windows runs when one of this app's notifications is clicked.

Registered as the command for the ``origenerator:`` link a notice carries, and
run by path with its own checkout in front of everything else, because the copy
that must answer a preview's notice is the preview's own.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from origenerator.app_link import follow  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(follow(sys.argv[1:]))
