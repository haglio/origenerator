"""This repo's dead-code gate. The scan it calls is `app_support.dead_code`.

The largest codebase in the family was one of three with no such gate, which is
a good deal of why the audit found the most dead code here.

**Production only — the tests are not scanned.** For an application that is the
question worth asking: a name reachable only from a test is a name production
has stopped calling, and reading it as used would hide exactly the accessors and
constants this repo has accumulated. It also keeps the report readable, since
`unittest.mock` assigns `return_value` and `side_effect` on throwaway objects and
vulture reports every one of them.

`vulture_whitelist.py` holds nothing but callers vulture cannot follow — Qt's
C++ event loop, sqlite3, COM, player_core, one string-dispatch table. It had a
second half when the gate went in, the 38 names the first scan reported and
nobody had yet judged; backlog item 24 emptied it, deleting each name or giving
it a reader.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from app_support.dead_code import assert_no_dead_code, assert_whitelist_is_live

ROOT = Path(__file__).resolve().parent.parent
# Named one by one rather than scanning `.` behind an `--exclude` list: vulture
# matches those patterns against absolute paths, and this checkout may itself be
# `<repo>/.claude/worktrees/<name>`, where `--exclude .claude` matches the root
# of the tree being scanned and quietly excludes every file in it.
SCANNED = (ROOT / "origenerator", ROOT / "tools")
WHITELIST = ROOT / "vulture_whitelist.py"


def test_no_dead_code():
    assert_no_dead_code(*SCANNED, whitelist=WHITELIST)


def test_the_whitelist_still_suppresses_what_it_claims_to():
    assert_whitelist_is_live(*SCANNED, whitelist=WHITELIST)


def test_nothing_is_imported_or_assigned_and_left_unread():
    """The hole vulture cannot see: deadness local to one module.

    Vulture resolves names across the whole tree it is handed, so an import
    unused HERE but live in a sibling module does not report -- which is how
    `gallery_view` came to carry three unread imports and a line repeated
    twice over, and `comfyui_client` an `import urllib.parse` whose one caller
    had gone. ruff answers per file.

    It answers per file only where a file says what it exports: without an
    ``__all__``, `gallery/__init__.py`'s ninety-odd deliberate re-exports report
    as F401 and are the entire signal, so a genuinely accidental import there
    could never be seen among them.
    """
    result = subprocess.run(
        [sys.executable, "-m", "ruff", "check",
         "--output-format", "concise",
         "--select", "F401,F811,F841",
         *(str(target) for target in SCANNED)],
        capture_output=True, text=True, cwd=str(ROOT),
    )

    assert result.returncode == 0, result.stdout + result.stderr
