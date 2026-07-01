import os

# Render Qt offscreen for the whole suite. Agents run these GUI tests on every
# commit; without this, each test that shows a widget throws a real window onto
# the screen for a few milliseconds, so a run flashes a burst of windows. Must
# be set before any QApplication is created (i.e. before pytest-qt's qapp
# fixture); setdefault lets a developer override it to watch a test on a real
# display.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from origenerator.paths import ensure_shared_ui_on_path

# Make shared_ui importable for tests regardless of checkout depth.
ensure_shared_ui_on_path()
