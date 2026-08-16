"""Shared fixtures — and the overlay pin.

The suite runs against the committed example overlay, never the developer's
git-ignored content.local.json, so a run here matches a public checkout.
pytest imports this before any test module, and the app loads its content at
import, so the pin has to happen here.
"""
from origenerator import content as _content

_content.LOCAL_CONTENT = _content.EXAMPLE_CONTENT

import gc
import json
import os
import struct

import pytest

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
