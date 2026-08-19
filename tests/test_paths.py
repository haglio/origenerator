import os
import subprocess
import sys
from pathlib import Path

from origenerator.paths import ensure_shared_ui_on_path, projects_root


def test_projects_root_contains_shared_ui():
    root = projects_root()
    assert (root / "shared_ui" / "__init__.py").exists()


def test_ensure_shared_ui_on_path_makes_it_importable_and_is_idempotent():
    ensure_shared_ui_on_path()
    root = str(projects_root())
    assert root in sys.path

    before = list(sys.path)
    ensure_shared_ui_on_path()
    assert sys.path == before  # second call adds nothing

    import shared_ui  # importable now that the root is on the path

    assert shared_ui.__file__ is not None


def test_gui_module_imports_in_fresh_interpreter():
    """A fresh process (real app launch / worktree) must resolve shared_ui on
    its own, without another test having already patched sys.path."""
    pkg_root = Path(__file__).resolve().parents[1]
    code = (
        "import sys;"
        f"sys.path.insert(0, r'{pkg_root}');"
        "import origenerator.gui.main_window as m;"
        "print(m.OrigeneratorWindow.__name__)"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env={k: v for k, v in os.environ.items() if k != "PYTHONPATH"},
    )
    assert result.returncode == 0, result.stderr
    assert "OrigeneratorWindow" in result.stdout


def test_player_core_is_found_the_same_way_and_is_importable():
    # The family's stroke lives there — the waveform and its dials, the console
    # and where the drive readout's parts sit — so this app drives the OSR2 from
    # genau's own model rather than a second copy of it.
    from origenerator.paths import ensure_player_core_on_path, sibling_checkout

    checkout = sibling_checkout("player_core")
    assert (checkout / "player_core" / "__init__.py").exists()
    ensure_player_core_on_path()
    ensure_player_core_on_path()  # idempotent
    import player_core.direct_control  # noqa: F401
    import player_core.drive_layout  # noqa: F401
