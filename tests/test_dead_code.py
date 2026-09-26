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
#
# 19316 when a tab's preview stopped asking the show it opened a window's
# question: its two notes on what builds that show, one of them calling it a
# window, are the factory's one line now, and a pane wired to nothing opening
# nothing is test_a_pane_with_nothing_wired_opens_nothing.
#
# 19310 when the pass Esc keeps became the playlist's, for a show on a
# session's player as for a window: what the window's note said is
# test_esc_again_puts_back_everything_it_took_off and
# test_a_show_of_a_run_in_flight_comes_back_as_a_show_of_the_folder.
#
# 19309 when a show's answers became the table the command file's published
# lines are built from: what the old chain's notes said is
# test_the_maps_chrome_loops_the_axes_widens_the_row_and_walks_the_cells.
#
# 19290 when closing the window started asking first: its notes on the close --
# where the quit shortcut fires, what a close hands ComfyUI and saves, the queue
# flushed last, no chore able to take the session down -- are
# test_quit_shortcut_fires_from_anywhere_in_the_app,
# test_ctrl_alt_q_answered_yes_quits_keeping_the_session,
# test_closing_hands_comfyui_the_experiments_to_run_while_away (red with the flush
# first), test_close_event_persists_session and
# test_a_broken_close_chore_still_leaves_the_session_saved.
#
# 19287 when a standalone launch began offering its window to Fun Time while it
# is still being built: the note on why a hosted launch never asks for the
# foreground is test_a_boot_fun_time_launched_leaves_what_is_in_front_to_the_session.
#
# 19281 when a standalone window stopped being shown before Fun Time could ask for
# it: the window builder's notes on showing, parking and the headset are
# test_main_in_fun_time_mode_parks_the_window_and_threads_the_session,
# test_a_boot_hosted_in_the_headset_is_not_parked and
# test_main_shows_loading_screen_during_boot_and_closes_it_after_window.
#
# 19279 when a clip handed to Evolver began taking its funscript along: what
# the hand-over's note said of the order it renames its copies in is
# test_shows_up_only_after_its_clip_so_evolver_never_finds_it_alone.
#
# 19262 when the preview began naming its generation with its file, rather than
# waiting for its owner to arm a drag: the three notes on that arming went with
# the method, and what they said is test_a_transient_view_disarms_the_drag and
# test_dragging_the_armed_preview_carries_its_generation; the director's note
# that a lone picture keeps its row for its versions is
# test_a_double_click_on_a_picture_no_folder_lists_still_names_its_generation.
#
# 19261 when a discarded seed's relaunch moved ahead of the folder's redraw: the
# helper that wrapped the drop and the redraw went, and what its line said is
# test_a_tab_watching_the_loop_follows_it_onto_the_next_seed.
#
# 19254 when the button bank's marks grew to fill their buttons: the bank
# button's note that its icon was drawn near the button's full height, which it
# never was, is test_every_mark_on_the_bank_spans_more_than_half_its_button.
MAX_PROSE_LINES = 19254


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
