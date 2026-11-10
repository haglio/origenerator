from __future__ import annotations

import contextlib
import os

from app_support import haglio_settings as _haglio_settings

from origenerator import content as _content
from tests.scratch import give_these_tests_a_state_dir

give_these_tests_a_state_dir(os.environ)

_NONE_IS_REQUIRED_AND_CI_HAS_NONE = ("onnxruntime", "ctranslate2", "torch")
# The voice stack's native DLLs (onnxruntime, ctranslate2, torch) crash with an access violation when first loaded after Qt.
for _voice_module in _NONE_IS_REQUIRED_AND_CI_HAS_NONE:
    with contextlib.suppress(Exception):
        __import__(_voice_module)

os.environ[_haglio_settings.SETTINGS_ENV] = _haglio_settings.THE_EXAMPLE

_content.LOCAL_CONTENT = _content.EXAMPLE_CONTENT
