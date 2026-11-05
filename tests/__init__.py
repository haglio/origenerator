from __future__ import annotations

import contextlib
import os

from app_support import haglio_settings as _haglio_settings

from origenerator import content as _content
from tests.scratch import give_these_tests_a_state_dir

give_these_tests_a_state_dir(os.environ)

# The voice stack's native DLLs (onnxruntime, ctranslate2, torch) crash with an access violation when first loaded after Qt.
for _voice_module in ("onnxruntime", "ctranslate2", "torch"):
    with contextlib.suppress(Exception):
        __import__(_voice_module)

os.environ[_haglio_settings.SETTINGS_ENV] = _haglio_settings.THE_EXAMPLE

_content.LOCAL_CONTENT = _content.EXAMPLE_CONTENT
