"""List the model files ComfyUI has on disk, to populate the form's dropdowns.

A workflow's checkpoint/LoRA/etc. picker offers whatever is actually installed
under ``ComfyUI/models/<category>``, so the user chooses from real files rather
than typing a filename. Shared by every workflow that exposes such a dropdown.
"""

import struct
from pathlib import Path

from origenerator import config

# The suffixes ComfyUI loads as models — LoRAs and checkpoints alike live under
# these, so one set serves every category. ``.gguf`` covers the quantized Flux
# diffusion models UnetLoaderGGUF loads.
_MODEL_SUFFIXES = (".safetensors", ".ckpt", ".pt", ".gguf")

# Where the enhance graph's detail pass finds its face/hand detectors: the
# directory the Impact Subpack's ``UltralyticsDetectorProvider`` scans, so a
# model dropped in for ComfyUI is the same one this app offers.
_DETECTOR_CATEGORY = "ultralytics/bbox"

# The picker option that means "no LoRA": choosing it builds the graph with no
# LoraLoader for that slot (see the workflows' ``build_api_payload``), so the
# base model runs unmodified. Never a real filename — a file's option always
# carries its extension — so it is safe as a sentinel.
NO_LORA = "None"

# The tensor-name prefixes a checkpoint's own text encoder sits under: SDXL keeps
# its two CLIPs beneath ``conditioner.``, SD1.5 its single one beneath
# ``cond_stage_model.``, and some repackaged checkpoints use ``text_encoders.``.
# Matched against the raw JSON header, where every tensor name is a quoted key —
# hence the leading quote, so a prefix can't match mid-name.
_TEXT_ENCODER_KEYS = (b'"conditioner.', b'"cond_stage_model.', b'"text_encoders.')

# No real header comes near this (the largest installed here is under 500 KB). A
# length past it means a corrupt or non-safetensors file, and honoring it would
# pull the whole model into memory to answer a question about its index.
_MAX_HEADER_BYTES = 32 * 1024 * 1024


def _model_paths(directory: Path) -> list[Path]:
    """The model files under *directory*, subfolders included, in picker order.

    Sorted by the name the picker shows (the path relative to the category dir),
    not by the absolute path, so a nested model sorts where it is listed.
    """
    if not directory.exists():
        return []
    return sorted(
        (f for f in directory.rglob("*") if f.is_file() and f.suffix in _MODEL_SUFFIXES),
        key=lambda f: str(f.relative_to(directory)),
    )


def list_model_files(category: str, fallback: list[str]) -> list[str]:
    """Sorted model files in ``ComfyUI/models/<category>``, subfolders included.

    Names are given relative to the category directory (e.g.
    ``split_files\\diffusion_models\\wan.safetensors``), matching how ComfyUI's
    own loaders reference models in subfolders — so a nested model is selectable
    and the value a run stored round-trips. Falls back to ``fallback`` when the
    directory is missing or holds no model files, so the dropdown always offers
    at least the workflow's default.
    """
    directory = config.COMFYUI_DIR / "models" / category
    found = [str(path.relative_to(directory)) for path in _model_paths(directory)]
    return found or list(fallback)


def _has_text_encoder(path: Path) -> bool:
    """Whether *path* ships its own text encoder, read from its header alone.

    A safetensors file opens with a little-endian u64 giving the byte length of a
    JSON header of tensor names, so the question is settled by a few hundred KB
    off the front of each file — no weights loaded, a couple of milliseconds for
    a whole folder, which is why the picker can afford to ask on every form
    build rather than caching a scan that would then go stale.

    Anything the header can't be read from — a ``.ckpt``, a truncated or
    malformed file — counts as a yes. Leaving an option in that turns out not to
    work is the harmless direction to be wrong in; dropping a checkpoint that
    works is not.
    """
    if path.suffix != ".safetensors":
        return True
    try:
        with path.open("rb") as handle:
            (length,) = struct.unpack("<Q", handle.read(8))
            if length > _MAX_HEADER_BYTES:
                return True
            header = handle.read(length)
    except (OSError, struct.error):
        return True
    if len(header) < length:
        return True  # truncated: we never saw the index we would be judging
    return any(key in header for key in _TEXT_ENCODER_KEYS)


def list_checkpoint_files(fallback: list[str]) -> list[str]:
    """The checkpoint picker's options, minus the files that cannot work.

    ``models/checkpoints`` is a mixed folder: alongside the SD1.5/SDXL
    checkpoints it collects diffusion-only files — WAN 2.2's high/low expert
    pairs, LTX — that carry no text encoder of their own. Every graph reading
    this picker wires ``CLIPTextEncode`` to the checkpoint loader's CLIP output,
    which such a file leaves empty, so listing them offers runs that can only
    error. The WAN pairs are the worse half of it: they read as a choice the
    user is being asked to make (High or Low?) when neither half belongs in an
    SDXL form at all.

    Falls back like :func:`list_model_files`, so a folder of nothing but
    diffusion-only files still offers the workflow's default.
    """
    directory = config.COMFYUI_DIR / "models" / "checkpoints"
    found = [
        str(path.relative_to(directory)) for path in _model_paths(directory)
        if _has_text_encoder(path)
    ]
    return found or list(fallback)


def list_lora_files(fallback: list[str]) -> list[str]:
    """The LoRA picker's options: the "None" sentinel first, then the installed
    LoRAs from the ``loras`` scan. "None" bypasses the LoRA (see
    :data:`NO_LORA`), so every LoRA picker can opt out of applying one.
    """
    return [NO_LORA, *list_model_files("loras", fallback)]


def list_detector_files() -> list[str]:
    """The face/hand detectors installed for the enhance graph's detail pass.

    No fallback, unlike every other picker here: a checkpoint the app names but
    ComfyUI lacks is a rare accident, whereas an install with no detector at all
    is the ordinary starting state — and the Enhance panel has to be able to see
    it, so it can dim the detail pass rather than offer a run that would be
    rejected on submit.
    """
    return list_model_files(_DETECTOR_CATEGORY, [])


def is_no_lora(value) -> bool:
    """True when a LoRA param names no LoRA: the "None" sentinel, or an empty or
    absent value (an older row, or an import whose graph carried no LoRA node).
    """
    return not value or value == NO_LORA
