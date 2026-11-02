from __future__ import annotations

from tests.children import run_python


def _modules_loaded_by(module: str) -> set[str]:
    probe = (
        f"import importlib, sys; importlib.import_module({module!r}); "
        "print(' '.join(sorted(sys.modules)))"
    )
    done = run_python(["-c", probe], check=True)
    return set(done.stdout.split())


def test_the_vocabulary_pulls_in_no_widgets():
    loaded = _modules_loaded_by("origenerator.voice.commands")
    assert not [name for name in loaded if name.startswith("PyQt6")]
    assert not [name for name in loaded if name.startswith("origenerator.gui")]
