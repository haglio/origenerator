"""Shared fixtures — the overlay pin, and the state directory of the suite's own.

The suite runs against the committed example overlay, never the developer's
git-ignored content.local.json, so a run here matches a public checkout.
pytest imports this before any test module, and the app loads its content at
import, so the pin has to happen here.

The same goes for where the app keeps its state: config binds STATE_DIR at
import and every module that reads it binds its own copy, so the one place a
run can be pointed at a directory of its own is the environment, before the
first origenerator import.  A run used to leave a log, arrow PNGs, thumbnails,
trash and a real recording in the checkout's live state/, and what one run
left behind decided what the next one drew.
"""
import atexit
import os
import shutil
import tempfile

if "ORIGENERATOR_STATE_DIR" not in os.environ:
    _suite_state_dir = tempfile.mkdtemp(prefix="origenerator-suite-")
    os.environ["ORIGENERATOR_STATE_DIR"] = _suite_state_dir
    atexit.register(shutil.rmtree, _suite_state_dir, True)

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
import random
import struct

import pytest
from PyQt6.QtCore import QCoreApplication, QEvent, QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication


@pytest.fixture(autouse=True)
def _unscaled_between_tests():
    """No test leaves this process drawing at another size than it found it.

    QT_SCALE_FACTOR is read by Qt per widget, and it is an ENVIRONMENT variable
    -- process-global, outliving whatever set it. A test that runs the hosted
    launch (main(["--fun-time", ...]), which scales the app on purpose) would
    otherwise hand every later test in the session a scaled Qt, and the tests
    that assert a window landed on the rect it was given fail hundreds of cases
    downstream of the one that actually set it.
    """
    before = os.environ.get("QT_SCALE_FACTOR")
    try:
        yield
    finally:
        if before is None:
            os.environ.pop("QT_SCALE_FACTOR", None)
        else:
            os.environ["QT_SCALE_FACTOR"] = before

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


def pytest_collection_modifyitems(items):
    """Collect in a different order when asked, so a test that leans on the ones
    beside it fails on the commit that introduces the lean.

    ``TEST_COLLECTION_ORDER=reverse`` collects back to front;
    ``TEST_COLLECTION_ORDER=shuffle`` shuffles with ``TEST_COLLECTION_SEED`` (0
    unless given), so a red run can be repeated exactly.  Unset leaves the order
    alone; anything else is a typo, and a typo that silently ran forward would
    make the gate's second leg a green that proves nothing.
    """
    order = os.environ.get("TEST_COLLECTION_ORDER")
    if order is None:
        return
    if order == "reverse":
        items.reverse()
    elif order == "shuffle":
        random.Random(int(os.environ.get("TEST_COLLECTION_SEED", "0"))).shuffle(items)
    else:
        raise pytest.UsageError(
            f"TEST_COLLECTION_ORDER={order!r}: expected 'reverse' or 'shuffle'"
        )


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
    ``speak_command`` one either matcher recognizes, and ``speak`` one fed
    through the real request dictation.
    """

    error = pyqtSignal(str)
    heard = pyqtSignal(str)
    edited = pyqtSignal(str)
    request = pyqtSignal(object)

    def __init__(self, *, command_matcher=None, bare_matcher=None, dictation=None,
                 transcribe_bias=None):
        super().__init__()
        self.started = False
        self.stopped = False
        self.commands_on = False
        self._matcher = command_matcher
        self._bare_matcher = bare_matcher
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
        """One spoken utterance while commands are armed: matched → executed.

        Both vocabularies, bare one first — the order the live steering uses."""
        if not self.commands_on:
            return None
        matched = self._bare_matcher(text) if self._bare_matcher else None
        if matched is None and self._matcher is not None:
            matched = self._matcher(text)
        if matched is not None:
            self._execute(matched)
        return matched

    def bare_command(self, text):
        """The whole-utterance command *text* is, asked first of a phrase the
        hosting session heard -- the live steering's own method, mirrored."""
        collecting = self._dictation is not None and self._dictation.listening
        if collecting or self._bare_matcher is None:
            return None
        return self._bare_matcher(text)

    def speak(self, text):
        """One utterance through the real dictation, as the mic would feed it.

        The live routing, in its own order: a whole-utterance command outranks
        an opening request (and nothing else does), then an open dictation
        swallows what it hears, then the looser matcher gets what is left.
        """
        collecting = self._dictation is not None and self._dictation.listening
        if not collecting and self.commands_on and self._bare_matcher is not None:
            bare = self._bare_matcher(text)
            if bare is not None:
                self._execute(bare)
                return bare
        spoken = self.push_dictation(text)
        if spoken is not None:
            self.request.emit(spoken)
            return spoken
        return self.speak_command(text)

    def push_dictation(self, text):
        """The same dictation, fed from somewhere other than the mic — the
        hosting session's channel, which is where the words of a request arrive
        while this app is hosted and its own mic is shut."""
        return self._dictation.push(text) if self._dictation is not None else None


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
    from origenerator.gui import osr2_driver, osr2_stroke_driver, stroke_panel

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
    # And off the broker's serial stamps, which the console reads to say whether
    # the device is answering: those are live files whose freshness depends on
    # whether the OSR2 happens to be switched on right now, so a suite reading
    # them would pass or fail with the hardware. The stand-in says it is there —
    # the console's own state before it could tell — and the tests about the
    # device being off inject their own.
    monkeypatch.setattr(stroke_panel.osr2, "device_on", lambda **_kw: True)


@pytest.fixture(autouse=True)
def _no_dialog_nobody_can_answer(monkeypatch):
    """Fail on a modal the test never arranged to answer, rather than hang on it.

    A message box or input dialog raised in an offscreen run has nobody to click
    it: it spins a nested event loop that nothing ever ends, so the test stops
    dead and holds the merge gate open until GitHub's six-hour limit, with no
    output naming which test it was. That is worse than the wrong answer in every
    way, and it is one mis-wired menu entry away at all times — a "Rename…"
    pointed at the delete's handler asks for confirmation, and there the run
    stops. Every test that means to reach a dialog answers it with a monkeypatch
    of its own, which lands over this one.
    """
    from PyQt6.QtWidgets import QInputDialog, QMessageBox

    def refuse(name):
        def blocked(*_args, **_kwargs):
            raise AssertionError(
                f"{name} was raised with nothing to answer it. If the dialog is "
                "the behaviour under test, monkeypatch it in the test."
            )
        return staticmethod(blocked)

    for name in ("question", "warning", "information", "critical", "about"):
        monkeypatch.setattr(QMessageBox, name, refuse(f"QMessageBox.{name}"))
    for name in ("getText", "getInt", "getDouble", "getItem", "getMultiLineText"):
        monkeypatch.setattr(QInputDialog, name, refuse(f"QInputDialog.{name}"))


def pytest_collection_finish(session):
    """Take the import graph out of every collection the reap below runs.

    That reap is a full ``gc.collect()`` after each of ~3,280 tests, and nearly
    everything it walks is import graph — pytest, PyQt6, origenerator and the
    test modules themselves — which is permanently live and never garbage.
    ``gc.freeze`` moves it to the permanent generation, which no collection
    traverses, so each reap costs what the test allocated instead of what the
    interpreter holds.

    Nothing about reaping changes for what tests build afterwards: a cycle
    created post-freeze is still promoted through the generations and still
    reaped by a full collect. Collection-finish is the last moment before any
    test runs — every test module is imported by then, and pytest-qt's
    QApplication does not exist yet, so no widget can be frozen alive.
    """
    gc.collect()
    gc.freeze()


# The suite's standing tail of deliberately long-lived widgets: measured at
# 26-27 at the end of identical full runs. Growth past double that is
# accumulation — the pile-up the per-test reap below exists to prevent —
# well before the hundreds it takes to hurt.
_WIDGET_TAIL_ALLOWANCE = 50


def _deliver_the_deletions_already_scheduled():
    """Carry out Qt's pending ``deleteLater`` deletions now.

    pytest-qt hands each test's registered widgets a ``deleteLater`` at
    teardown, but a posted DeferredDelete is only delivered once an event loop
    spins — which a test that never pumps one leaves undone. Until then the C++
    widget is still allocated and still connected, so the deletion has to be
    driven rather than waited for: a lone ``pytest tests/test_gallery_view.py``
    otherwise ends holding 1,048 widgets that are already condemned, and every
    one of them goes when this runs.
    """
    if QApplication.instance() is None:
        return
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


@pytest.fixture(autouse=True, scope="session")
def _the_live_widget_count_stays_flat():
    """The per-test reap's acceptance criterion, asserted: widgets from the
    run's thousands of built-and-discarded panels must not accumulate.

    Sampled after the pending deletions are delivered and the cycles collected,
    so what it counts is what something still *holds* — a widget already
    condemned is not a leak, and a widget nothing can reach is not one either.
    """
    before = len(QApplication.allWidgets()) if QApplication.instance() else 0
    yield
    if QApplication.instance() is None:
        return
    _deliver_the_deletions_already_scheduled()
    gc.collect()
    grown = len(QApplication.allWidgets()) - before
    assert grown <= _WIDGET_TAIL_ALLOWANCE, (
        f"{grown} more live widgets at session end than at start: the "
        f"per-test reap is no longer keeping the live object count flat"
    )


@pytest.fixture(autouse=True)
def _collect_widgets_between_tests():
    """Reap each test's widgets before the next one builds its own.

    The GUI widgets (a config panel's param form, the gallery's panes) form Python
    reference cycles — a widget owns a signal whose slot closes back over it — so
    their C++ objects linger until Python's cyclic collector runs. Left to chance,
    hundreds of galleries' worth pile up across a full run and eventually corrupt
    the Qt heap. Collecting after each test keeps the live object count flat.

    The collector releases what Python was holding; delivering the deletions then
    finishes what Qt was asked to do with it, so each test pays for its own
    leavings rather than handing them to the next one that runs an event loop —
    which is what the suite's one flake was (tests/test_deferred_deletes.py).
    """
    yield
    gc.collect()
    _deliver_the_deletions_already_scheduled()


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
    # The same deal for the beat the combine's Generate waits out so its stand-in
    # queue row reaches the screen before the launch blocks the thread.
    monkeypatch.setattr(GalleryView, "_after_painting", lambda self, work: work())


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
