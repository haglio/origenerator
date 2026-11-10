"""Which modules are allowed to need Qt, held as an equality.

Each module is imported in a fresh interpreter, because PyQt6 is already loaded in this process.
"""
from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

import pytest

from origenerator import config, provenance
from origenerator.db import Database

REPO_ROOT = Path(__file__).resolve().parents[1]

QT_FREE = (
    "origenerator.gallery",
    "origenerator.experiments.policy",
    "origenerator.gallery.tree",
    "origenerator.search",
    "origenerator.app",
    "origenerator.boot_passes",
    "origenerator.passes_on_the_files",
    "origenerator.app_link",
    "origenerator.windows_toast",
    "origenerator.landed_while_away",
    "origenerator.toast_raising",
    "origenerator.single_instance",
    "origenerator.comfyui_api",
    "origenerator.completion",
    "origenerator.inflight",
    "origenerator.favorite_reconcile",
    "origenerator.base_backfill",
    "origenerator.export_lane",
    "origenerator.importer",
    "origenerator.db",
    "origenerator.trash_collection",
    "origenerator.branch_session",
    "origenerator.content",
    "origenerator.config",
    "origenerator.undo_stack",
    "origenerator.gallery_edits",
    "origenerator.run_toast",
    "origenerator.timing",
    "origenerator.file_refs",
    "origenerator.generation_metadata",
    "origenerator.workflows.derived_size",
    "origenerator.item_shape",
    "origenerator.spin_arrows",
    "origenerator.slideshow_buttons",
    "origenerator.osr2_controls_commands",
    "origenerator.funestras_engine",
)

NEEDS_QT = (
    "origenerator.comfyui_client",
    "origenerator.icon_design",
)


def _loaded_after_importing(module: str, what: str) -> bool:
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env["PYTHONPATH"] = os.pathsep.join(
        p for p in (str(REPO_ROOT), os.environ.get("PYTHONPATH", "")) if p)
    result = subprocess.run(
        [sys.executable, "-c",
         ("import sys\n"
         "import origenerator.content as content\n"
         "content.LOCAL_CONTENT = content.EXAMPLE_CONTENT\n"
         f"import {module}\n"
         f'print("{what}" in sys.modules)')],
        cwd=REPO_ROOT, env=env, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip() == "True"


@pytest.mark.parametrize("module", QT_FREE)
def test_a_module_that_claims_to_be_qt_free_is(module):
    assert _loaded_after_importing(module, "PyQt6") is False


def test_the_experiment_policy_asks_no_language_model():
    assert _loaded_after_importing(
        "origenerator.experiments.policy", "origenerator.local_llm") is False, \
        "it works from the gallery's rows alone, so it runs offline and with a random source handed in"


OPENS_WINDOWS = {"action_setter_tool.py", "app.py", "check_animations.py", "downtime.py",
                 "own_window.py"}


def test_only_what_opens_a_window_imports_the_widget_package():
    package = REPO_ROOT / "origenerator"
    reaching_in = {
        path.relative_to(package).as_posix() for path in package.rglob("*.py")
        if "gui" not in path.relative_to(package).parts
        and any(isinstance(node, (ast.Import, ast.ImportFrom))
                and ("origenerator.gui" in ast.unparse(node)
                     or ast.unparse(node).startswith("from origenerator import gui"))
                for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))))}

    assert reaching_in == OPENS_WINDOWS, "imports run upward: nothing below the widgets reaches in"


def test_the_language_model_is_asked_on_this_machine():
    assert urlparse(config.LOCAL_LLM_BASE_URL).hostname == "localhost", (
        "no prompt leaves the machine")


def test_every_unstamped_row_is_stamped_in_one_write(tmp_path):
    db = Database(tmp_path / "t.db")
    writes = []
    fill_in = db.fill_in
    db.fill_in = lambda *args: writes.append(1) or fill_in(*args)

    provenance.stamp_unstamped(db, history=lambda _workflow: [])

    assert writes == [1], "a commit for each row took half a minute of the launch that writes them all"


def test_timing_loads_no_database():
    assert _loaded_after_importing("origenerator.timing", "origenerator.db") is False


@pytest.mark.parametrize("module", NEEDS_QT)
def test_the_modules_that_do_need_qt_are_only_these(module):
    assert _loaded_after_importing(module, "PyQt6") is True
OUTSIDE_THE_WIDGETS = (
    "radio",
    "osr2_controls_commands",
    "fun_time_bridge",
    "item_shape",
    "osr2_driver",
    "osr2_motion_driver",
    "slideshow_buttons",
    "spin_arrows",
)


@pytest.mark.parametrize("module", OUTSIDE_THE_WIDGETS)
def test_the_app_own_machinery_is_not_in_the_widget_package(module):
    assert (REPO_ROOT / "origenerator" / f"{module}.py").exists()
    assert not (REPO_ROOT / "origenerator" / "gui" / f"{module}.py").exists()


def test_file_refs_leans_on_neither_the_gallery_nor_the_workflows():
    assert _loaded_after_importing("origenerator.file_refs", "origenerator.gallery") is False
    assert _loaded_after_importing("origenerator.file_refs", "origenerator.workflows") is False


def test_derived_size_imports_no_workflow_so_the_form_and_the_workflows_share_it():
    source = (REPO_ROOT / "origenerator" / "workflows" / "derived_size.py").read_text(encoding="utf-8")
    imported = [node.module for node in ast.walk(ast.parse(source))
                if isinstance(node, ast.ImportFrom) and node.module]

    assert not [module for module in imported if module.startswith("origenerator.workflows")]
