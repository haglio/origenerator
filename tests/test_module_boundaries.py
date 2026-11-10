"""Which modules are allowed to need Qt, held as an equality.

Each module is imported in a fresh interpreter, because PyQt6 is already loaded in this process.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

QT_FREE = (
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
