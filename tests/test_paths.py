import os
import subprocess
import sys
from pathlib import Path

from origenerator.paths import ensure_shared_ui_on_path, sibling_checkout


def test_the_shared_ui_checkout_holds_the_package_of_the_same_name():
    checkout = sibling_checkout("shared_ui")
    assert (checkout / "shared_ui" / "__init__.py").exists()


def test_ensure_shared_ui_on_path_makes_it_importable_and_is_idempotent():
    ensure_shared_ui_on_path()
    root = str(sibling_checkout("shared_ui"))
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


def test_every_module_importing_a_sibling_puts_it_on_the_path_itself():
    """`shared_ui` and `player_core` are not installed -- each module that
    imports one calls the matching `ensure_*_on_path()` above the import and
    marks it `# noqa: E402`.

    Not a style rule. A module that leaves the call out imports today only
    because some earlier import in the same file did it as a side effect, so an
    isort or ruff pass that groups the sibling imports away from the
    `origenerator.gui` ones turns it into an ImportError at launch.
    """
    package = Path(__file__).resolve().parents[1] / "origenerator"
    missing = []
    for path in sorted(package.rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        for sibling, ensure in (("shared_ui", "ensure_shared_ui_on_path"),
                                ("player_core", "ensure_player_core_on_path")):
            imports = f"\nfrom {sibling}" in source or f"\nimport {sibling}" in source
            if imports and f"{ensure}()" not in source:
                missing.append(f"{path.relative_to(package.parent)} -> {sibling}")

    assert not missing, (
        "imports a sibling checkout without putting it on sys.path first:\n  "
        + "\n  ".join(missing))
