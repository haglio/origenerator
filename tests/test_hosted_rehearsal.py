from __future__ import annotations

import sys
from pathlib import Path

from origenerator import fun_time_mode as contract
from origenerator import hosted_rehearsal
from tests.children import run_python

A_REHEARSAL_S = hosted_rehearsal.REHEARSAL_BUDGET_S + 60


def a_hosted_launch_in(folder: Path) -> list[str]:
    def rect(prefix: str, x: int) -> list[str]:
        return [word for field, value in zip(contract.RECT_FIELDS, (x, 0, 1440, 1720), strict=True)
                for word in (f"--{prefix}{field}", str(value))]

    return [
        contract.MODE_FLAG,
        *rect(contract.MAIN_RECT_PREFIX, 0),
        *(word for shape, prefix in contract.REGION_RECT_PREFIXES.items()
          for word in rect(prefix, 2560 if shape == "portrait" else 4000)),
        contract.TASKBAR_IDENTITY_FLAG, "Invented.Session.Identity",
        *(word for name in contract.SESSION_FILES
          for word in (f"--{name}", str(folder / f"{name}.txt"))),
        *(word for shape in contract.SHAPES
          for flag in (*contract.funestra_flags(shape), *contract.message_flags(shape))
          for word in (flag, str(folder / f"{flag.removeprefix('--')}.txt"))),
    ]


def test_a_rehearsed_hosted_start_hands_both_satellites_a_slideshow(tmp_path):
    ran = run_python(["-m", "origenerator", *a_hosted_launch_in(tmp_path),
                      contract.REHEARSE_FLAG], timeout=A_REHEARSAL_S)

    assert ran.returncode == 0, ran.stdout + ran.stderr
    assert hosted_rehearsal.BOTH_HANDED in ran.stdout


def test_a_rehearsal_that_meets_an_error_filling_a_satellite_fails_with_its_last_line(
        tmp_path, capfd):
    breaking = [sys.executable, "-m", "tests.rehearsal_that_breaks_filling"]

    failed = hosted_rehearsal.rehearse(a_hosted_launch_in(tmp_path), child=breaking)

    assert failed != 0
    assert "TypeError: an invented fault filling the portrait Satellite" in capfd.readouterr().err
