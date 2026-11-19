# ruff: noqa: PLC0415
# Imports below are late on purpose: the overlay is swapped for the example before config reads it.
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from pathlib import Path

from app_support import haglio_settings
from app_support.subprocess_utils import hidden_subprocess_kwargs

CHECKOUT = Path(__file__).resolve().parent.parent
REHEARSAL_BUDGET_S = 180
_WAITED_FOR_AFTER_THE_BUDGET_S = 60
_LOOKED_AT_EVERY_S = 0.1
BOTH_HANDED = "Both Satellites were handed a slideshow"
_STATE_DIR = "ORIGENERATOR_STATE_DIR"
_BRANCH_SESSION = "ORIGENERATOR_BRANCH_SESSION"
_MADE_UP = {"portrait": (90, 160), "landscape": (160, 90)}
_ENDED: list[int] = []
_VERDICT = "The rehearsed start: "


def rehearse(argv: list[str], *, child: list[str] | None = None) -> int:
    child = child or [sys.executable, "-m", __name__]
    with tempfile.TemporaryDirectory(prefix="origenerator-rehearsal-",
                                     ignore_cleanup_errors=True) as folder:
        try:
            ran = subprocess.run(
                [*child, *argv], cwd=CHECKOUT, env=_away_from_his_machine(Path(folder)),
                timeout=REHEARSAL_BUDGET_S + _WAITED_FOR_AFTER_THE_BUDGET_S, check=False,
                stdin=subprocess.DEVNULL, capture_output=True, encoding="utf-8",
                errors="replace", **hidden_subprocess_kwargs())
        except subprocess.TimeoutExpired:
            print(f"The rehearsed start was still running {REHEARSAL_BUDGET_S} s after it "
                  "began, and was ended", file=sys.stderr, flush=True)
            return 1
    print(_the_verdict_of(ran), file=sys.stderr if ran.returncode else sys.stdout, flush=True)
    return ran.returncode


def _the_verdict_of(ran: subprocess.CompletedProcess) -> str:
    verdicts = [line.removeprefix(_VERDICT) for line in ran.stdout.splitlines()
                if line.startswith(_VERDICT)]
    if verdicts and (ran.returncode == 0 or verdicts[-1] != BOTH_HANDED):
        return verdicts[-1]
    if verdicts:
        return (f"Origenerator handed both Satellites a slideshow, then exited with code "
                f"{ran.returncode} as it closed")
    said = [line for line in ran.stderr.splitlines()
            if line.strip() and not line.startswith((" ", "\t", "Traceback"))]
    return said[-1] if said else f"The rehearsed start exited with code {ran.returncode}"


def _away_from_his_machine(folder: Path) -> dict[str, str]:
    env = {name: value for name, value in os.environ.items() if name != _BRANCH_SESSION}
    (folder / "appdata").mkdir()
    return {**env, _STATE_DIR: str(folder / "state"), "LOCALAPPDATA": str(folder / "appdata"),
            haglio_settings.SETTINGS_ENV: haglio_settings.THE_EXAMPLE,
            "QT_QPA_PLATFORM": "offscreen"}


def away_from_his_library() -> None:
    from origenerator import content

    content.LOCAL_CONTENT = content.EXAMPLE_CONTENT


def main(argv: list[str]) -> int:
    away_from_his_library()
    from origenerator import app, config
    from origenerator.fun_time_mode import parse_app_args
    from origenerator.gui import off_the_machine

    for keep_off in off_the_machine.EVERYTHING_OFF_THE_MACHINE:
        keep_off(setattr)
    _a_made_up_library(config.DB_PATH, Path(os.environ[_STATE_DIR]).parent / "made-up library")
    sys.excepthook = _end_on_what_escaped
    threading.Thread(target=_FunTimesPart(parse_app_args(argv).fun_time).play,
                     name="Fun Time's part", daemon=True).start()
    stopped = app.main(argv)
    if _ENDED:
        return _ENDED[0]
    print(f"{_VERDICT}Origenerator stopped, with exit code {stopped}, before it had handed "
          "both Satellites a slideshow", flush=True)
    return stopped or 1


def _a_made_up_library(db_path: Path, folder: Path) -> None:
    from PIL import Image

    from origenerator.db import Database
    from origenerator.generation_state import GenerationSource, GenerationStatus

    folder.mkdir(parents=True)
    rows = []
    for shape, size in _MADE_UP.items():
        image = folder / f"made-up {shape}.png"
        Image.new("RGB", size).save(image)
        rows.append({
            "prompt_id": f"made-up-{shape}", "workflow_name": "sdxl_t2i",
            "workflow_version": "v1", "params_json": "{}", "workflow_json": "{}",
            "source": GenerationSource.GENERATED, "status": GenerationStatus.COMPLETED,
            "output_files": json.dumps([{"filename": image.name, "path": str(image)}]),
            "thumbnail_path": str(image), "shape": shape,
        })
    db_path.parent.mkdir(parents=True, exist_ok=True)
    Database(db_path).insert_rows(rows)


def _end(code: int, said: str) -> None:
    from PySide6.QtCore import QCoreApplication

    if _ENDED:
        return
    _ENDED.append(code)
    print(f"{_VERDICT}{said}", flush=True)
    running = QCoreApplication.instance()
    if running is None:
        os._exit(code)
    running.exit(code)


def _end_on_what_escaped(kind, error, trace) -> None:
    traceback.print_exception(kind, error, trace)
    said = " ".join(str(error).split())
    _end(1, f"{kind.__name__}: {said}" if said else kind.__name__)


class _FunTimesPart:
    def __init__(self, session):
        self._session = session

    def play(self) -> None:
        from origenerator.fun_time_mode import START_FAILED, UP

        deadline = time.monotonic() + REHEARSAL_BUDGET_S
        asked = False
        while time.monotonic() < deadline:
            status = self._status()
            if _ENDED:
                return
            if failed := status.get(START_FAILED):
                _end(1, failed)
            elif not asked and status.get(UP) == "1":
                self._ask_for_both_slideshows()
                asked = True
            elif asked and all(map(self._handed, _MADE_UP)):
                _end(0, BOTH_HANDED)
            time.sleep(_LOOKED_AT_EVERY_S)
        _end(1, f"Origenerator had not handed both Satellites a slideshow "
                f"{REHEARSAL_BUDGET_S} s after it started")

    def _status(self) -> dict[str, str]:
        from app_support.file_channel import read_key_values

        try:
            return read_key_values(self._session.status_file)
        except OSError:
            return {}

    def _ask_for_both_slideshows(self) -> None:
        from funestra.file_channel import append_command

        from origenerator.fun_time_mode import OPEN_SLIDESHOW
        from origenerator.osr2_controls_commands import spelled_for

        for shape in _MADE_UP:
            append_command(self._session.command_file, spelled_for(shape, OPEN_SLIDESHOW))

    def _handed(self, shape: str) -> bool:
        from funestra.playlist import read_playlist

        try:
            played = read_playlist(self._session.funestra(shape).playlist)
        except OSError:
            return False
        return any(Path(item.path).name == f"made-up {shape}.png" for item in played)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
