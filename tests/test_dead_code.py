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

import io
import subprocess
import sys
import tokenize
from pathlib import Path

from app_support.dead_code import assert_no_dead_code, assert_whitelist_is_live

ROOT = Path(__file__).resolve().parent.parent
# Named one by one rather than scanning `.` under an `--exclude` list: vulture
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
    """The blind spot vulture cannot see: deadness local to one module.

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
# Prose the code has to be kept in step with by hand, and is not kept in step
# with by hand. This repo measured 0.6331 lines of it per line of code on
# 2026-09-21 -- against fun_time's 0.3107, which is the same family working the
# same findings -- and backlog item 70 is the file-by-file work of bringing it
# down. The ceiling exists so each step is kept: it only ever comes down, and a
# step that only deletes is refused, because prose you do not write is coverage
# you owe.
#
# 19327 on 2026-09-21, measured on the merged tree, when the ceiling went in with
# the two longest module preambles already under it: the fullscreen player's 90
# lines and the info pane's 71 are 30 and 31, which is what took the tree from
# 19416 to here. What they keep is what a test cannot say -- where the creep into
# a picture lives, why a run joins a show on its first frame and not before, why
# a show wears one panel where Fun Time wears two, why the tab row carries no
# "+" of its own, and that an edit is what a person did rather than what a load
# did. Every rule cut was already a test named for the claim (161 of them across
# the two files); each preamble now says so and names the file.
#
# 19323 when a folder's star stopped redrawing the gallery: the tree's note that
# the star is drawn from the folder rather than written before its name
# (test_favoriting_a_folder_persists_without_reordering and
# test_a_favorited_folder_wears_a_green_star_with_the_mouse_elsewhere), and the
# pane's that each side's Favorites collects its own side's bookmarks
# (test_favorites_collects_the_bookmarks_of_its_own_side).
MAX_PROSE_LINES = 19323


def _prose_and_code(path: Path) -> tuple[int, int]:
    """(prose lines, code lines) in one module.

    A line is prose when its only content is a comment or a docstring, so a
    trailing `# why` on a real statement costs nothing -- the ratio is about
    paragraphs, not annotations. The same measure fun_time's own ceiling uses,
    so the two repos' numbers can be read against each other; publishing it
    once for the family is item 70's own follow-up.
    """
    source = path.read_text(encoding="utf-8")
    lines = source.splitlines()
    kind = ["blank" if not line.strip() else "code" for line in lines]
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except (tokenize.TokenError, IndentationError):  # pragma: no cover - syntax is CI's job
        return 0, 0

    def mark(token, *, only_if_alone: bool):
        for n in range(token.start[0] - 1, token.end[0]):
            if kind[n] != "code":
                continue
            if only_if_alone and lines[n].split("#")[0].strip():
                continue  # a trailing `# why` on a statement is not prose
            kind[n] = "prose"

    opens_a_statement = tokenize.INDENT
    for token in tokens:
        if token.type == tokenize.COMMENT:
            mark(token, only_if_alone=True)
        elif token.type == tokenize.STRING and opens_a_statement in (
            tokenize.INDENT, tokenize.DEDENT, tokenize.NEWLINE, tokenize.NL,
        ):
            mark(token, only_if_alone=False)
        if token.type not in (tokenize.COMMENT, tokenize.NL):
            opens_a_statement = token.type
    return kind.count("prose"), kind.count("code")


def test_prose_does_not_outgrow_the_code_it_explains():
    """A ceiling that can only come down.

    Design that lives in prose has to be kept in step by hand, and is not kept
    in step by hand. Where a paragraph states a rule, the way to spend it is a
    name or a test, not another paragraph -- and this fails until one of those
    is what carries it.
    """
    prose = code = 0
    for target in SCANNED:
        for path in sorted(target.rglob("*.py")):
            module_prose, module_code = _prose_and_code(path)
            prose += module_prose
            code += module_code

    assert prose <= MAX_PROSE_LINES, (
        f"{prose} prose lines (ceiling {MAX_PROSE_LINES}), against {code} of code "
        f"-- {prose / code:.4f} per line. Delete a stale block, or move what it "
        "says into a name or a test; lower MAX_PROSE_LINES when you do."
    )
