"""This repo's dead-code gate. The scan it calls is `app_support.dead_code`.

The largest codebase in the family was one of three with no such gate, which is
a good deal of why the audit found the most dead code here.

**Production only — the tests are not scanned.** For an application that is the
question worth asking: a name reachable only from a test is a name production
has stopped calling, and reading it as used would hide exactly the accessors and
constants this repo has accumulated. It also keeps the report readable, since
`unittest.mock` assigns `return_value` and `side_effect` on throwaway objects and
vulture reports every one of them.

`vulture_whitelist.py` has two halves. The first is the framework false
positives, permanent by nature — Qt hooks the C++ event loop calls, a ctypes
struct field COM reads. The second is everything the scan reported on the day
the gate went in: the gate had to come before the deletions or they would have
had nothing watching them, so those names are recorded rather than judged.
Emptying that half is backlog item 24.
"""
from __future__ import annotations

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
