"""This repo's prose ceiling, the one check here the family's gates do not yet ship.

The dead-code checks that sat beside it are app_support's gates, which every repo
names once in its pytest options.
"""
from __future__ import annotations

import io
import tokenize
from pathlib import Path

import pytest

pytestmark = pytest.mark.repo_check

ROOT = Path(__file__).resolve().parent.parent
SCANNED = (ROOT / "origenerator", ROOT / "tools")


MAX_PROSE_LINES = 15970


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
