from __future__ import annotations

import contextlib
import os
from pathlib import Path

from app_support import haglio_settings as _haglio_settings

from origenerator import content as _content
from tests.scratch import give_these_tests_a_state_dir

give_these_tests_a_state_dir(os.environ)

_OPTIONAL_VOICE_LIBRARIES = ("onnxruntime", "ctranslate2", "torch")
# The voice stack's native DLLs (onnxruntime, ctranslate2, torch) crash with an access violation when first loaded after Qt.
for _voice_module in _OPTIONAL_VOICE_LIBRARIES:
    with contextlib.suppress(Exception):
        __import__(_voice_module)

_ORIGENERATORS_OWN_FOLDERS = ("origenerator_images_dir", "origenerator_videos_dir",
                              "origenerator_scripts_dir", "origenerator_audio_dir")


def _the_suites_settings(state_dir: Path) -> dict:
    settings = {name: value for name, value in _haglio_settings.example_inside(state_dir).items()
                if name not in _ORIGENERATORS_OWN_FOLDERS}
    settings["comfyui_output_dir"] = str(state_dir / "comfyui" / "output")
    return settings


_STATE = Path(os.environ["ORIGENERATOR_STATE_DIR"])
_haglio_settings.run_on(_the_suites_settings(_STATE), _STATE, os.environ)

_content.LOCAL_CONTENT = _content.EXAMPLE_CONTENT
