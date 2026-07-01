"""List the model files ComfyUI has on disk, to populate the form's dropdowns.

A workflow's checkpoint/LoRA/etc. picker offers whatever is actually installed
under ``ComfyUI/models/<category>``, so the user chooses from real files rather
than typing a filename. Shared by every workflow that exposes such a dropdown.
"""

from origenerator import config

# The suffixes ComfyUI loads as models — LoRAs and checkpoints alike live under
# these, so one set serves every category.
_MODEL_SUFFIXES = (".safetensors", ".ckpt", ".pt")


def list_model_files(category: str, fallback: list[str]) -> list[str]:
    """Sorted names of the model files in ``ComfyUI/models/<category>``.

    Falls back to ``fallback`` when that directory is missing or holds no model
    files, so the dropdown always offers at least the workflow's default. Scans
    the category's top level only (matching how ComfyUI's own pickers behave for
    bare filenames), skipping subfolders and non-model files.
    """
    directory = config.COMFYUI_DIR / "models" / category
    if not directory.exists():
        return list(fallback)
    found = sorted(
        f.name for f in directory.iterdir()
        if f.is_file() and f.suffix in _MODEL_SUFFIXES
    )
    return found or list(fallback)
