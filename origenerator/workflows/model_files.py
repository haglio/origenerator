"""List the model files ComfyUI has on disk, to populate the form's dropdowns.

A workflow's checkpoint/LoRA/etc. picker offers whatever is actually installed
under ``ComfyUI/models/<category>``, so the user chooses from real files rather
than typing a filename. Shared by every workflow that exposes such a dropdown.

A category directory is a folder, not a catalogue — ``checkpoints`` holds WAN and
LTX video models beside the SDXL ones, ``loras`` holds a LoRA for every
architecture at once — so a picker also says what its graph can *run*, and only
those are offered. See :mod:`origenerator.workflows.model_arch` for how a file's
architecture is read.

``accepts`` is keyword-only and has no default on purpose. A workflow added later
cannot list a folder without answering the question — the call fails outright
rather than quietly offering everything, which is the failure this exists to
prevent. :data:`ANY` is the way to say a category genuinely takes anything.
"""

from pathlib import Path

from origenerator import config
from origenerator.workflows import model_arch

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

# ``accepts=ANY``: this category is architecture-neutral, so list all of it. The
# ESRGAN upscalers are the real case — they resample pixels and neither know nor
# care which model made them. Spelled out at the call site so an unfiltered
# picker is a decision on the record, not an omission.
ANY = "any"


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


def _offer(path: Path, accepts, expert: str | None, want_lora: bool) -> bool:
    """Whether *path* belongs in a picker with these terms.

    Each test drops a file only on a positive finding — an architecture that is
    recognized and wrong, a name that names the other expert. A file we could not
    read stays offered: a listed option that errors on submit costs one run,
    where a working model silently missing from the dropdown has no symptom the
    user can act on at all.
    """
    described = model_arch.describe(path)
    if described.is_shard:
        return False
    if described.is_lora != want_lora:
        return False
    if accepts != ANY and described.arch is not None and described.arch not in accepts:
        return False
    return not (expert and described.expert and described.expert != expert)


def _listing(category: str, fallback: list[str], accepts, expert, want_lora) -> list[str]:
    directory = config.COMFYUI_DIR / "models" / category
    found = [
        str(path.relative_to(directory)) for path in _model_paths(directory)
        if _offer(path, accepts, expert, want_lora)
    ]
    return found or list(fallback)


def list_model_files(
    category: str, fallback: list[str], *, accepts, expert: str | None = None,
) -> list[str]:
    """The model files in ``ComfyUI/models/<category>`` this picker can run.

    *accepts* is an architecture from :mod:`~origenerator.workflows.model_arch`,
    a tuple of them, or :data:`ANY`. *expert* is ``"high"`` or ``"low"`` for a
    picker that fills one half of WAN 2.2's expert pair, which drops the files
    whose names claim the other half.

    Names are given relative to the category directory (e.g.
    ``split_files\\diffusion_models\\wan.safetensors``), matching how ComfyUI's
    own loaders reference models in subfolders — so a nested model is selectable
    and the value a run stored round-trips. Falls back to ``fallback`` when the
    directory is missing or nothing in it qualifies, so the dropdown always
    offers at least the workflow's default.
    """
    return _listing(category, fallback, accepts, expert, want_lora=False)


def list_lora_files(
    fallback: list[str], *, accepts, expert: str | None = None,
) -> list[str]:
    """The LoRA picker's options: the "None" sentinel first, then the installed
    LoRAs this picker can run. "None" bypasses the LoRA (see :data:`NO_LORA`), so
    every LoRA picker can opt out of applying one.

    Takes the same *accepts*/*expert* terms as :func:`list_model_files`, against
    the architecture each LoRA was *trained for* — and drops the occasional full
    checkpoint that ends up filed under ``loras``, which no LoraLoader can take.
    """
    return [NO_LORA, *_listing("loras", fallback, accepts, expert, want_lora=True)]


def list_detector_files() -> list[str]:
    """The face/hand detectors installed for the enhance graph's detail pass.

    No fallback, unlike every other picker here: a checkpoint the app names but
    ComfyUI lacks is a rare accident, whereas an install with no detector at all
    is the ordinary starting state — and the Enhance panel has to be able to see
    it, so it can dim the detail pass rather than offer a run that would be
    rejected on submit.

    ``ANY``, and not as a shrug: these are YOLO region detectors, which have no
    diffusion architecture to match against and work the same whatever made the
    image they scan.
    """
    return list_model_files(_DETECTOR_CATEGORY, [], accepts=ANY)


def is_no_lora(value) -> bool:
    """True when a LoRA param names no LoRA: the "None" sentinel, or an empty or
    absent value (an older row, or an import whose graph carried no LoRA node).
    """
    return not value or value == NO_LORA
