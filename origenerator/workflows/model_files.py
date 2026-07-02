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
