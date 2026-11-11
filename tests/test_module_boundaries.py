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
    "origenerator.prompt_diff",
    "origenerator.prompt_edit",
    "origenerator.generation_config",
    "origenerator.action_settings",
    "origenerator.gallery",
    "origenerator.experiments.policy",
    "origenerator.gallery.tree",
    "origenerator.search",
    "origenerator.app",
    "origenerator.boot_passes",
    "origenerator.passes_on_the_files",
    "origenerator.windows_toast",
    "origenerator.landed_while_away",
    "origenerator.toast_raising",
    "origenerator.single_instance",
    "origenerator.comfyui_api",
    "origenerator.completion",
    "origenerator.inflight",
    "origenerator.queue_line",
    "origenerator.gallery.combine",
    "origenerator.gui.param_sections",
    "origenerator.navigation",
    "origenerator.gui.hud_nav_map",
    "origenerator.slideshow",
    "origenerator.app_state",
    "origenerator.voice.dictation",
    "origenerator.voice.text",
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
    "origenerator.gui.picking",
    "origenerator.gui.slideshow_set",
    "origenerator.nav_map",
    "origenerator.gui.modify_batch",
    "origenerator.fun_time_mode",
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


def test_what_windows_runs_on_a_toast_click_loads_no_qt():
    assert _loaded_after_importing("origenerator.app_link", "PyQt6") is False, (
        "Qt-free, because this is what runs on a click")


def test_the_experiment_policy_asks_no_language_model():
    assert _loaded_after_importing(
        "origenerator.experiments.policy", "origenerator.local_llm") is False, \
        "it works from the gallery's rows alone, so it runs offline and with a random source handed in"


def test_the_voice_router_routes_and_leaves_the_doing_to_its_host():
    router = REPO_ROOT / "origenerator" / "gui" / "voice_router.py"
    imported = [ast.unparse(node) for node in ast.walk(ast.parse(router.read_text(encoding="utf-8")))
                if isinstance(node, (ast.Import, ast.ImportFrom))]
    does_the_doing = ("slideshow_director", "job_queue", "comfyui_client")

    assert not [line for line in imported if any(name in line for name in does_the_doing)], (
        "what it does not hold is the doing: a slideshow's own words went to the slideshows, a "
        "Gallery pane button's press is the button's own click, and the orders about an image "
        "stay with the seams that run them")


def test_only_the_slideshows_fill_the_screen():
    package = REPO_ROOT / "origenerator"
    filling_the_screen = {path.relative_to(package).as_posix() for path in package.rglob("*.py")
                          if "showFullScreen" in path.read_text(encoding="utf-8")}

    assert filling_the_screen == {"gui/slideshow_director.py"}, (
        "the full-screen slideshow window is the one way this app fills the screen with an item")


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


def test_the_action_settings_load_no_database():
    assert _loaded_after_importing("origenerator.action_settings", "origenerator.db") is False


def test_the_trash_that_moves_files_knows_no_record_and_no_hold_time():
    assert _loaded_after_importing("origenerator.trash", "origenerator.db") is False, (
        "how long a batch is held is the Trash collection's to decide")
    assert _loaded_after_importing("origenerator.trash", "origenerator.trash_collection") is False


def test_the_folder_types_and_their_walkers_lean_on_nothing_else_of_this_app():
    groups = ast.parse((REPO_ROOT / "origenerator" / "gallery" / "groups.py").read_text(
        encoding="utf-8"))
    imported = {node.module or "" for node in ast.walk(groups) if isinstance(node, ast.ImportFrom)}

    assert not [module for module in imported if module.startswith(("origenerator", "."))], (
        "the walkers need only the folder types, so they live with them and not with the tree's builder")


def test_the_output_files_module_leans_on_nothing_of_the_folder_tree():
    output = ast.parse((REPO_ROOT / "origenerator" / "gallery" / "output.py").read_text(
        encoding="utf-8"))
    imported = {node.module or "" for node in ast.walk(output) if isinstance(node, ast.ImportFrom)}

    assert not [module for module in imported
                if module.endswith((".tree", ".groups", ".keys"))]


def test_one_module_alone_puts_a_question_to_the_language_model():
    package = REPO_ROOT / "origenerator"
    asking = {path.relative_to(package).as_posix() for path in package.rglob("*.py")
              if "/api/chat" in path.read_text(encoding="utf-8")}

    assert asking == {"local_llm.py"}, "a second way to the model would answer the same words two ways"


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


def test_populate_is_run_with_no_gallery_and_no_job():
    assert _loaded_after_importing(
        "origenerator.gui.populate_controller", "origenerator.gui.gallery_view") is False, (
        "it reaches the gallery only through the launch it is handed and the outcomes it is told")
    for job_module in ("origenerator.gui.job_queue", "origenerator.gui.generation_job"):
        assert _loaded_after_importing("origenerator.gui.populate_controller", job_module) is False


def test_the_lines_rules_ask_no_server():
    assert _loaded_after_importing("origenerator.queue_line", "origenerator.comfyui_api") is False, (
        "pure rules, so they are tested with no ComfyUI running")


def test_file_refs_leans_on_neither_the_gallery_nor_the_workflows():
    assert _loaded_after_importing("origenerator.file_refs", "origenerator.gallery") is False
    assert _loaded_after_importing("origenerator.file_refs", "origenerator.workflows") is False


def test_derived_size_imports_no_workflow_so_the_form_and_the_workflows_share_it():
    source = (REPO_ROOT / "origenerator" / "workflows" / "derived_size.py").read_text(encoding="utf-8")
    imported = [node.module for node in ast.walk(ast.parse(source))
                if isinstance(node, ast.ImportFrom) and node.module]

    assert not [module for module in imported if module.startswith("origenerator.workflows")]


def test_the_combine_is_drawn_with_no_database():
    assert _loaded_after_importing("origenerator.gui.combine", "origenerator.db") is False, (
        "the Combine only reports what was asked for; its controller owns the database")


def test_a_job_is_followed_with_no_database_of_its_own():
    assert _loaded_after_importing("origenerator.gui.generation_job", "origenerator.db") is False, (
        "a job owns no database: whoever launched it decides what to keep of it")


def _modules_imported_by(source_file: str) -> set[str]:
    tree = ast.parse((REPO_ROOT / source_file).read_text(encoding="utf-8"))
    named = {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    named |= {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import)
              for alias in node.names}
    return named - {"__future__"}


def _beyond_the_standard_library(modules: set[str]) -> set[str]:
    return {module for module in modules if module.split(".")[0] not in sys.stdlib_module_names}


def test_the_undo_stack_knows_nothing_of_what_it_undoes():
    assert _beyond_the_standard_library(_modules_imported_by("origenerator/undo_stack.py")) == set(), (
        "entirely generic: nothing in it knows what a generation is")


def test_the_voice_text_leans_on_nothing():
    assert _beyond_the_standard_library(_modules_imported_by("origenerator/voice/text.py")) == set(), (
        "the matchers that call it live in the workflows and the gallery as well as in the voice code")


def test_the_dictation_is_text_in_and_text_out():
    assert _beyond_the_standard_library(_modules_imported_by("origenerator/voice/dictation.py")) == {
        "origenerator.voice.text"}, (
        "no microphone and no model: the listener owns one and feeds it each transcription")


def test_the_script_that_speaks_imports_nothing_of_this_app():
    imported = _modules_imported_by("tools/speech_worker.py")

    assert not [module for module in imported if module.split(".")[0] == "origenerator"], (
        "it is run by path under the speech environment's own Python, which has none of this app installed")


@pytest.mark.parametrize("surface", ["inflight_tile", "job_queue_view", "hud_queue"])
def test_a_surface_showing_work_in_flight_never_reaches_the_job(surface):
    tree = ast.parse((REPO_ROOT / "origenerator" / "gui" / f"{surface}.py").read_text(encoding="utf-8"))
    reached = _modules_imported_by(f"origenerator/gui/{surface}.py")
    reached |= {alias.name for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
                for alias in node.names}

    assert not {name for name in reached
                if name.split(".")[-1] in ("generation_job", "job_queue") or "db" in name.split(".")[-1].split("_")}, (
        "each is handed one record per job, what to draw and how to stop it and go to it, so none "
        "knows where a job came from")


def test_the_drag_of_a_generation_leans_on_no_widget_of_this_app():
    assert _beyond_the_standard_library(
        _modules_imported_by("origenerator/gui/generation_drag.py")) == {"PyQt6.QtCore"}, (
        "in a module of its own so a plain media widget does not have to depend on the item tile "
        "just for the type")


def test_the_job_queues_tiles_are_put_together_with_nothing_that_draws():
    assert _loaded_after_importing("origenerator.gui.inflight_items", "PyQt6.QtGui") is False, (
        "a join over four sources and no rendering at all, which is why they are built outside "
        "the Gallery pane")
