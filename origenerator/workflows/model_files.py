"""List the model files ComfyUI has on disk, to populate the form's dropdowns.

A workflow's checkpoint/LoRA/etc. picker offers whatever is actually installed
under ``ComfyUI/models/<category>``, so the user chooses from real files rather
than typing a filename. Shared by every workflow that exposes such a dropdown.
"""

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
    if not directory.exists():
        return list(fallback)
    found = sorted(
        str(f.relative_to(directory)) for f in directory.rglob("*")
        if f.is_file() and f.suffix in _MODEL_SUFFIXES
    )
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
