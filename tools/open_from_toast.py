"""What Windows runs when one of this app's toasts is clicked.

Registered as the command for the ``origenerator:`` link a toast carries, the
production checkout's whichever copy raised the toast, and run by path with
that checkout in front of everything else, so the code that answers is its own
whatever the venv has installed.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from origenerator.app_link import follow  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(follow(sys.argv[1:]))
