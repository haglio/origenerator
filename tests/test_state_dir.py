"""Where the app keeps its state: the checkout's own, unless the process says otherwise."""

from __future__ import annotations

import _winapi
import json
import os
from pathlib import Path

from app_support import haglio_settings

from origenerator import config
from tests.children import run_python

_PROBE = (
    "from origenerator import config; "
    "print(config.STATE_DIR); print(config.DB_PATH); print(config.THUMB_DIR); "
    "print(config.UI_STATE_PATH); print(config.PROJECT_DIR); "
    "print(config.TRASH_DIR); print(config.project_dir('origenerator')); print(config.RECORDS_DIR); "
    "print(config.PRODUCTION_CHECKOUT)"
)


def _paths(state_dir: str | None, *, branch_session: bool = False,
           settings: Path | None = None) -> list[Path]:
    env = {k: v for k, v in os.environ.items()
           if k not in ("ORIGENERATOR_STATE_DIR", "ORIGENERATOR_BRANCH_SESSION")}
    if state_dir is not None:
        env["ORIGENERATOR_STATE_DIR"] = state_dir
    if branch_session:
        env["ORIGENERATOR_BRANCH_SESSION"] = "1"
    if settings is not None:
        env[haglio_settings.SETTINGS_ENV] = str(settings)
    result = run_python(["-c", _PROBE], env=env, check=True)
    return [Path(line) for line in result.stdout.splitlines()]


def _settings_naming_this_checkout_the_production_one(tmp_path: Path) -> Path:
    roots = tmp_path / "roots"
    roots.mkdir()
    _winapi.CreateJunction(str(config.PROJECT_DIR), str(roots / "origenerator"))
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({**haglio_settings.EXAMPLE, "project_roots": [str(roots)]}),
                        encoding="utf-8")
    return settings


def test_the_production_app_keeps_its_state_in_its_checkout_and_its_pictures_files_in_the_library(
        tmp_path):
    state, db, thumbs, ui, project, trash, _primary, records, production = _paths(
        None, settings=_settings_naming_this_checkout_the_production_one(tmp_path))
    assert state == project / "state"
    assert production == project
    assert db == state / "origenerator.db"
    assert thumbs == records / "thumbnails"
    assert trash == records / "trash"
    assert ui == state / "ui_state.json"
    assert records == config.LIBRARY_ROOT / "app_data" / "origenerator"


def test_another_checkout_started_without_the_preview_flag_keeps_its_trash_beside_its_own_database():
    state, db, thumbs, _ui, project, trash, _primary, _records, _production = _paths(None)
    assert db == project / "state" / "origenerator.db"
    assert (thumbs, trash) == (state / "thumbnails", state / "trash")


def test_a_process_told_where_its_state_is_keeps_every_path_there(tmp_path):
    # The suite is that process: it points every run at a directory of its own,
    # and every module that binds a path at import has to follow.
    state, db, thumbs, ui, _project, trash, _primary, _records, _production = _paths(
        str(tmp_path / "elsewhere"))
    assert state == tmp_path / "elsewhere"
    assert db.parent == state
    assert thumbs.parent == state
    assert trash.parent == state
    assert ui.parent == state


def test_a_branch_session_shares_the_live_installs_library_and_keeps_its_own_window_state():
    # The library -- its database, and the thumbnails and trash kept beside the
    # pictures -- is the production app's wherever the app runs from, so every
    # instance shows every generation, made in a preview or not. What is about
    # this window alone (its saved geometry and tabs, its logs) stays in the
    # checkout that runs it.
    state, db, thumbs, ui, project, trash, primary, records, production = _paths(
        None, branch_session=True)
    library = primary / "state"
    assert production == primary
    assert state == project / "state"
    assert (db, thumbs, trash) == (library / "origenerator.db", records / "thumbnails",
                                  records / "trash")
    assert ui == state / "ui_state.json"


def test_this_run_is_not_writing_into_the_live_state_directory():
    assert config.STATE_DIR != config.PROJECT_DIR / "state"
