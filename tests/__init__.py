from __future__ import annotations

import contextlib
import json
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


def _the_suites_settings(state_dir: Path) -> Path:
    settings = {name: value for name, value in _haglio_settings.EXAMPLE.items()
                if name not in _ORIGENERATORS_OWN_FOLDERS}
    settings["comfyui_output_dir"] = str(state_dir / "comfyui" / "output")
    state_dir.mkdir(parents=True, exist_ok=True)
    written = state_dir / "haglio_settings.json"
    written.write_text(json.dumps(settings), encoding="utf-8")
    return written


os.environ[_haglio_settings.SETTINGS_ENV] = str(
    _the_suites_settings(Path(os.environ["ORIGENERATOR_STATE_DIR"])))

_content.LOCAL_CONTENT = _content.EXAMPLE_CONTENT
