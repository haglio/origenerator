"""Shared fixtures — and the overlay pin.

The suite runs against the committed example overlay, never the developer's
git-ignored content.local.json, so a run here matches a public checkout.
pytest imports this before any test module, and the app loads its content at
import, so the pin has to happen here.
"""
# Before anything that can pull PyQt6 in: the voice stack's native DLLs
# (whisper's engine, its VAD, and torch where installed) die with a plain
# access violation when first loaded AFTER Qt — the same crash
# app._warm_voice_runtimes preloads its way past for the app, which took a
# whole pytest run down mid-suite on a machine carrying the voice extra.
# Guarded per module: none is required, and CI has none of them.
for _voice_module in ("onnxruntime", "ctranslate2", "torch"):
    try:
        __import__(_voice_module)
    except Exception:
        pass  # no voice extra (or a broken one): the suite still runs

from origenerator import content as _content

_content.LOCAL_CONTENT = _content.EXAMPLE_CONTENT

import gc
import json
import os
import struct

import pytest
from PyQt6.QtCore import QObject, pyqtSignal

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


# One recognizable tensor name per architecture, matching the signatures in
# origenerator.workflows.model_arch. Fabricated, not lifted from a real file —
# a header is all the pickers read, so a stand-in needs nothing else.
ARCH_TENSOR_NAMES = {
    "sdxl": ["conditioner.embedders.0.transformer.x", "model.diffusion_model.input_blocks.0.y"],
    "sd15": ["cond_stage_model.transformer.x", "model.diffusion_model.input_blocks.0.y"],
    "flux": ["double_blocks.0.img_attn.qkv.weight", "single_blocks.0.linear1.weight"],
    "qwen": ["transformer_blocks.0.attn.to_q.weight", "txt_norm.weight"],
    "wan": ["blocks.0.self_attn.q.weight", "patch_embedding.weight"],
    "ltx": ["patchify_proj.weight", "transformer_blocks.0.attn1.to_q.weight"],
}


class ModelTree:
    """A stand-in ``ComfyUI/models`` tree, written one fake model at a time."""

    def __init__(self, root):
        self.root = root

    def add(self, category, name, *, arch=None, lora=False, body=None):
        """Write ``models/<category>/<name>``, returning its path.

        With *arch*, the file gets a real safetensors header naming that
        architecture's tensors — plus the LoRA suffixes when *lora* — which is
        what the pickers classify it by. With *body*, the raw bytes are written
        instead, for the unreadable-file cases.
        """
        path = self.root / "models" / category / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if body is not None:
            path.write_bytes(body)
            return path
        names = list(ARCH_TENSOR_NAMES[arch]) if arch else ["unknown.weight"]
        if lora:
            names = [f"{name}.lora_A.weight" for name in names]
        header = json.dumps(
            {n: {"dtype": "F16", "shape": [1], "data_offsets": [0, 2]} for n in names}
        ).encode()
        path.write_bytes(struct.pack("<Q", len(header)) + header + b"\x00\x00")
        return path


@pytest.fixture
def installed_models(tmp_path, monkeypatch):
    """An empty stand-in models tree, with ``config.COMFYUI_DIR`` pointed at it."""
    from origenerator import config

    monkeypatch.setattr(config, "COMFYUI_DIR", tmp_path)
    return ModelTree(tmp_path)


class FakeVoiceSteering(QObject):
    """Stands in for VoiceSteering so no test ever opens a real microphone.

    Suite-wide rather than per-module, so a module that builds a gallery for
    some other reason can never inherit a device grab and a speech-model
    download from the one that does.

    ``say`` simulates a heard-and-rewritten utterance steering a loop's prompt,
    ``speak_command`` one the matcher recognizes, and ``speak`` one fed through
    the real request dictation.
    """

    error = pyqtSignal(str)
    heard = pyqtSignal(str)
    edited = pyqtSignal(str)
    request = pyqtSignal(object)

    def __init__(self, *, command_matcher=None, dictation=None, transcribe_bias=None):
        super().__init__()
        self.started = False
        self.stopped = False
        self.commands_on = False
        self._matcher = command_matcher
        self._dictation = dictation
        self._execute = None
        self._set = None

    def start(self, get_prompt, set_prompt):
        self.started = True
        self._set = set_prompt

    def stop(self):
        self.stopped = True

    def start_commands(self, execute):
        self.commands_on = True
        self._execute = execute

    def stop_commands(self):
        self.commands_on = False
        self._execute = None

    def say(self, new_prompt):
        self._set(new_prompt)

    def speak_command(self, text):
        """One spoken utterance while commands are armed: matched → executed."""
        matched = self._matcher(text) if self.commands_on and self._matcher else None
        if matched is not None:
            self._execute(matched)
        return matched

    def speak(self, text):
        """One utterance through the real dictation, as the mic would feed it:
        part of a request is re-emitted, anything else falls through to the
        command matcher exactly as the live steering routes it."""
        spoken = self._dictation.push(text) if self._dictation is not None else None
        if spoken is not None:
            self.request.emit(spoken)
            return spoken
        return self.speak_command(text)


@pytest.fixture(autouse=True)
def _no_real_mic(monkeypatch):
    """Point every gallery's voice steering at the inert stand-in above."""
    from origenerator.gui import gallery_view

    monkeypatch.setattr(gallery_view, "VoiceSteering", FakeVoiceSteering)


@pytest.fixture(autouse=True)
def _never_take_the_real_device(monkeypatch):
    """Keep the suite off the OSR2 and off genau's state file.

    A test that builds a gallery gets real drive controllers, and the one OSR2
    switch now *drives* the moment it goes on — a stroke when there's no
    funscript to follow — where it used to arm and wait. So turning it on in a
    test would open a socket at the broker's port, spin the 40 Hz clock, and
    write "0" into the sibling app's ``genau_enabled.txt``, which is a live file
    on this machine. Both drivers take an injectable broker, and every test that
    exercises one for its own sake injects its own; this only replaces the
    default, so nothing is left reaching the hardware by accident.
    """
    from origenerator.gui import osr2_driver, osr2_stroke_driver

    class _NoDevice:
        def pause_genau(self): pass
        def restore_genau(self): pass
        def park(self): pass
        def send_position(self, pos, interval_ms): pass
        def close(self): pass

    class _NoTicker:
        def __init__(self, tick, interval_s, **_kw): pass
        def start(self): pass
        def stop(self): pass

    monkeypatch.setattr(osr2_driver, "Osr2Broker", lambda *a, **k: _NoDevice())
    monkeypatch.setattr(osr2_stroke_driver, "Osr2Broker", lambda *a, **k: _NoDevice())
    monkeypatch.setattr(osr2_stroke_driver, "_TickThread", _NoTicker)


@pytest.fixture(autouse=True)
def _collect_widgets_between_tests():
    """Reap each test's widgets before the next one builds its own.

    The GUI widgets (a config panel's param form, the gallery's panes) form Python
    reference cycles — a widget owns a signal whose slot closes back over it — so
    their C++ objects linger until Python's cyclic collector runs. Left to chance,
    hundreds of galleries' worth pile up across a full run and eventually corrupt
    the Qt heap. Collecting after each test keeps the live object count flat.
    """
    yield
    gc.collect()


@pytest.fixture(autouse=True)
def _recipe_match_runs_inline(monkeypatch):
    """Let the gallery's off-thread work run straight through.

    The recipe match is asked on a pool thread in the app, because the model it
    asks thinks for several seconds and the window must stay alive. A test wants
    the opposite: launch and inspect in one call, with no event loop to pump. One
    test exercises the real hop (test_gallery_view) by putting this back.
    """
    from origenerator.gui.gallery_view import GalleryView

    monkeypatch.setattr(GalleryView, "_run_off_thread",
                        lambda self, work, done: done(work()))


@pytest.fixture(autouse=True)
def _previews_start_running():
    """Leave the app-wide preview freeze off between tests.

    The freeze is module state (origenerator.gui.looping_preview), which is
    exactly what makes it reach a preview built after it was set — and exactly
    what would otherwise let a test that pauses hand the next test a gallery of
    still thumbnails it never asked for.
    """
    from origenerator.gui.looping_preview import set_previews_paused

    set_previews_paused(False)
    yield
    set_previews_paused(False)
