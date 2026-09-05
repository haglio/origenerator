"""Where the app keeps its state: the checkout's own, unless the process says otherwise."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent

_PROBE = (
    "from origenerator import config; "
    "print(config.STATE_DIR); print(config.DB_PATH); print(config.THUMB_DIR); "
    "print(config.UI_STATE_PATH); print(config.PROJECT_DIR)"
)


def _paths(state_dir: str | None) -> list[Path]:
    env = {k: v for k, v in os.environ.items() if k != "ORIGENERATOR_STATE_DIR"}
    if state_dir is not None:
        env["ORIGENERATOR_STATE_DIR"] = state_dir
    result = subprocess.run([sys.executable, "-c", _PROBE], cwd=_REPO_ROOT, env=env,
                            capture_output=True, text=True, check=True)
    return [Path(line) for line in result.stdout.splitlines()]


def test_the_app_keeps_its_state_in_its_own_checkout():
    state, db, thumbs, ui, project = _paths(None)
    assert state == project / "state"
    assert db == state / "origenerator.db"
    assert thumbs == state / "thumbnails"
    assert ui == state / "ui_state.json"


def test_a_process_told_where_its_state_is_keeps_every_path_there(tmp_path):
    # The suite is that process: it points every run at a directory of its own,
    # and every module that binds a path at import has to follow.
    state, db, thumbs, ui, _project = _paths(str(tmp_path / "elsewhere"))
    assert state == tmp_path / "elsewhere"
    assert db.parent == state
    assert thumbs.parent == state
    assert ui.parent == state


def test_this_run_is_not_writing_into_the_live_state_directory():
    from origenerator import config

    assert config.STATE_DIR != config.PROJECT_DIR / "state"
