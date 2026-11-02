from __future__ import annotations

import contextlib
import os
import tempfile
from pathlib import Path

from app_support import haglio_settings as _haglio_settings

from origenerator import content as _content
from tests.scratch import remove_at_exit

if "ORIGENERATOR_STATE_DIR" not in os.environ:
    _suite_state_dir = tempfile.mkdtemp(prefix="origenerator-suite-")
    os.environ["ORIGENERATOR_STATE_DIR"] = _suite_state_dir
    remove_at_exit(Path(_suite_state_dir))

# The voice stack's native DLLs (onnxruntime, ctranslate2, torch) crash with an access violation when first loaded after Qt.
for _voice_module in ("onnxruntime", "ctranslate2", "torch"):
    with contextlib.suppress(Exception):
        __import__(_voice_module)

os.environ[_haglio_settings.SETTINGS_ENV] = _haglio_settings.THE_EXAMPLE

_content.LOCAL_CONTENT = _content.EXAMPLE_CONTENT
