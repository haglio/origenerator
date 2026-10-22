"""The spoken vocabulary is text matching, and costs no widgets to import."""
from __future__ import annotations

from tests.children import run_python


def _modules_loaded_by(module: str) -> set[str]:
    # In a fresh interpreter: the suite has already imported half the app, so
    # asking this one's sys.modules would answer about the suite, not the import.
    probe = (
        f"import importlib, sys; importlib.import_module({module!r}); "
        "print(' '.join(sorted(sys.modules)))"
    )
    done = run_python(["-c", probe], check=True)
    return set(done.stdout.split())


def test_the_vocabulary_pulls_in_no_widgets():
    # It takes a transcription and returns a NamedTuple. Reaching into the
    # widget package for the collection names pulled the whole of Qt along with them,
    # and inverted the layering every other module here keeps.
    loaded = _modules_loaded_by("origenerator.voice.commands")
    assert not [name for name in loaded if name.startswith("PyQt6")]
    assert not [name for name in loaded if name.startswith("origenerator.gui")]
