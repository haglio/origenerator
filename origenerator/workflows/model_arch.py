"""Read what a model file *is* off its own header, so a picker can offer only
the files the graph behind it can actually run.

``ComfyUI/models/<category>`` is a folder, not a catalogue: ``checkpoints`` holds
SDXL and SD1.5 checkpoints beside WAN and LTX video models, ``diffusion_models``
holds WAN, Flux, Qwen and bare SDXL UNets together, and ``loras`` holds LoRAs
trained against every one of those. Listing a folder verbatim therefore offers
runs that can only error — and, worse, presents them as choices the user is
being asked to make.

Nothing about a file's *name* is dependable here (``gonzalomoXLFluxPony`` is an
SDXL checkpoint), so the architecture is read from the tensor names instead. Both
container formats put those in a header at the front of the file: safetensors
after a u64 length prefix, GGUF after its metadata block. Neither needs the
weights, which is what makes this cheap enough to run on every form build —
measured at a few milliseconds for the whole installed set — rather than caching
a scan that would go stale the moment a model is downloaded.

Unrecognized is not the same as unwanted: an arch of ``None`` means "we could not
tell", and every caller keeps those. Leaving in an option that turns out not to
work costs a failed submit; dropping a model that works hides it with no way for
the user to know why.
"""

import json
import re
import struct
from dataclasses import dataclass
from pathlib import Path

SDXL = "sdxl"
SD15 = "sd15"
FLUX = "flux"
QWEN = "qwen"
WAN = "wan"
LTX = "ltx"

# No real header comes near this (the largest installed is under 500 KB). A
# length past it means a corrupt or misidentified file, and honoring it would
# pull the whole model into memory to answer a question about its index.
_MAX_HEADER_BYTES = 32 * 1024 * 1024

# Enough tensor names to recognize any architecture; a full-size model lists
# thousands, and reading them all would be work for no extra certainty.
_MAX_TENSOR_NAMES = 400

# Prefixes that wrap an otherwise-normal state dict. The same WAN model ships
# both bare (``blocks.0.…``) and wrapped (``model.diffusion_model.blocks.0.…``),
# and a ControlNet wraps the whole net in ``control_model.`` — so the wrapper is
# stripped before anything is matched, or half the signatures below would miss.
_WRAPPERS = (
    "model.diffusion_model.", "diffusion_model.", "control_model.",
    "model.", "transformer.",
)

# Tensor-name fragments only a LoRA has: the A/B pair of the diffusers form, the
# down/up pair of the kohya form, and kohya's flattened module prefixes.
_LORA_MARKERS = ("lora_A.", "lora_B.", "lora_down.", "lora_up.", "lora_unet_", "lora_te")

# A sharded download (``…-00001-of-00006.safetensors``). Each part holds a slice
# of the tensors and none loads on its own, so listing them offers six broken
# picks in place of one model that isn't selectable at all.
_SHARD = re.compile(r"-\d+-of-\d+\.[^.]+$")

# WAN 2.2 trains a high-noise and a low-noise expert, and which one a file is
# lives only in its name. Anchored so a word merely *containing* the letters
# can't match: "low" needs a non-letter before it (``-low-``, ``_low_``) or a
# camel-case hump (``t2vLowV30``). Ordinary words swallow these letters —
# "yellow", "slow", "flow" — and several installed LoRAs are named with them,
# so an unanchored search would file each of those under low-noise.
_EXPERT_CAMEL = re.compile(r"(?<=[a-z0-9])(High|Low)")
_EXPERT_BOUNDED = re.compile(r"(?:^|[^A-Za-z])(high|low)", re.IGNORECASE)


@dataclass(frozen=True)
class ModelFile:
    """What one file on disk turned out to be.

    ``arch`` is ``None`` when the header could not be read or matched no
    signature — the "we could not tell" case every filter treats as a keep.
    """

    arch: str | None
    is_lora: bool
    expert: str | None   # "high" / "low" when the name says so, else None
    is_shard: bool


def describe(path: Path) -> ModelFile:
    """Classify *path* from its header and its name, without loading weights."""
    if _SHARD.search(path.name):
        return ModelFile(arch=None, is_lora=False, expert=None, is_shard=True)
    keys = _tensor_names(path)
    expert = _expert_from_name(path.name)
    if keys is None:
        return ModelFile(arch=None, is_lora=False, expert=expert, is_shard=False)
    return ModelFile(
        arch=_arch_from(_components(keys)),
        is_lora=any(marker in key for key in keys for marker in _LORA_MARKERS),
        expert=expert,
        is_shard=False,
    )


def _expert_from_name(name: str) -> str | None:
    """Which WAN 2.2 expert the filename claims, or ``None`` when it says nothing.

    A name carrying both markers claims nothing usable, so it reads as unmarked
    and stays offered in either slot.
    """
    found = {
        match.group(0).lower().strip("-_. ")
        for match in (*_EXPERT_BOUNDED.finditer(name), *_EXPERT_CAMEL.finditer(name))
    }
    found = {word for word in found if word in ("high", "low")}
    return found.pop() if len(found) == 1 else None


def _components(keys: list[str]) -> set[str]:
    """The leading component of every tensor name, wrappers stripped.

    kohya-form LoRAs flatten a whole module path into one component
    (``lora_unet_double_blocks_0_img_attn_qkv``), so the signatures below test
    these by prefix as well as by equality.
    """
    out = set()
    for key in keys:
        for wrapper in _WRAPPERS:
            if key.startswith(wrapper):
                key = key[len(wrapper):]
                break
        out.add(key.split(".")[0])
    return out


def _arch_from(components: set[str]) -> str | None:
    """The architecture these tensor names belong to, or ``None`` if unrecognized.

    Order is load-bearing: several families share a component name and are told
    apart only by a marker one of them also has, so the more specific signature
    has to be asked first. Each rule below says which collision it settles.
    """
    def has(*names: str) -> bool:
        return any(name in components for name in names)

    def starts(*prefixes: str) -> bool:
        return any(c.startswith(p) for c in components for p in prefixes)

    # SDXL first: its two text encoders show up as `conditioner.` in a
    # checkpoint, as the extra size/pooled conditioning (`label_emb`,
    # `add_embedding`) in a bare UNet or ControlNet, and as the paired
    # `lora_te1_`/`lora_te2_` in a LoRA — where SD1.5's single `lora_te_` would
    # otherwise claim it below.
    if has("conditioner", "label_emb", "add_embedding") or starts("lora_te1_", "lora_te2_"):
        return SDXL
    # Flux before Qwen and LTX: its diffusers-form LoRAs carry plain
    # `transformer_blocks` too, and only the `single_` twin separates them.
    if (has("double_blocks", "single_blocks", "single_transformer_blocks", "guidance_in")
            or starts("lora_unet_double_blocks", "lora_unet_single_blocks")):
        return FLUX
    # LTX before Qwen, same reason: it is a `transformer_blocks` model as well,
    # and these three names are what is only ever LTX.
    if has("patchify_proj", "adaln_single", "caption_projection"):
        return LTX
    if has("transformer_blocks"):
        return QWEN
    # WAN: bare `blocks.N` (never `input_blocks`/`double_blocks`, which is why
    # this is safe after the families above), the patch/text/time embeddings
    # around them, VACE's parallel stack, or a kohya LoRA's flattened form.
    if (has("blocks", "patch_embedding", "text_embedding", "time_projection", "vace_blocks")
            or starts("lora_unet_blocks_")):
        return WAN
    # SD1.5 last, as the family defined by lacking SDXL's additions: its
    # checkpoint marker, its single-text-encoder LoRA marker, and the original
    # ControlNet shape, which is SD1.5's only because no SDXL marker fired.
    if has("cond_stage_model", "zero_convs", "input_hint_block") or starts("lora_te_"):
        return SD15
    return None


def _tensor_names(path: Path) -> list[str] | None:
    """The tensor names in *path*, or ``None`` when they can't be read.

    ``None`` covers every "we could not tell" case — a format with no readable
    index (``.ckpt``, ``.pt``), a truncated or corrupt file, a header too large
    to be a header — and callers keep those rather than judging them.
    """
    try:
        if path.suffix == ".safetensors":
            return _safetensors_names(path)
        if path.suffix == ".gguf":
            return _gguf_names(path)
    except (OSError, struct.error, UnicodeDecodeError, ValueError, KeyError):
        return None   # KeyError: a GGUF metadata value of a type we don't know
    return None


def _safetensors_names(path: Path) -> list[str] | None:
    """safetensors: a little-endian u64 byte length, then that much JSON."""
    with path.open("rb") as handle:
        (length,) = struct.unpack("<Q", handle.read(8))
        if length > _MAX_HEADER_BYTES:
            return None
        header = handle.read(length)
    if len(header) < length:
        return None   # truncated: never saw the index we would be judging
    return [key for key in json.loads(header) if key != "__metadata__"]


# GGUF's metadata values are typed; every type but string and array is a fixed
# width, so skipping the metadata block to reach the tensor index is a matter of
# stepping over the right number of bytes per value.
_GGUF_FIXED_WIDTHS = {0: 1, 1: 1, 2: 2, 3: 2, 4: 4, 5: 4, 6: 4, 7: 1, 10: 8, 11: 8, 12: 8}
_GGUF_STRING = 8
_GGUF_ARRAY = 9


def _gguf_names(path: Path) -> list[str] | None:
    """GGUF: magic and counts, then a metadata block, then the tensor index."""
    with path.open("rb") as handle:
        if handle.read(4) != b"GGUF":
            return None
        handle.read(4)   # format version — the layout below is stable across 2/3
        tensor_count, kv_count = struct.unpack("<QQ", handle.read(16))
        for _ in range(kv_count):
            (key_length,) = struct.unpack("<Q", handle.read(8))
            handle.read(key_length)
            (value_type,) = struct.unpack("<I", handle.read(4))
            _gguf_skip(handle, value_type)
        names = []
        for _ in range(min(tensor_count, _MAX_TENSOR_NAMES)):
            (name_length,) = struct.unpack("<Q", handle.read(8))
            names.append(handle.read(name_length).decode("utf-8"))
            (dimensions,) = struct.unpack("<I", handle.read(4))
            handle.read(8 * dimensions + 12)   # the dims, the ggml type, the offset
    return names


def _gguf_skip(handle, value_type: int) -> None:
    """Step over one metadata value without decoding it."""
    if value_type == _GGUF_STRING:
        (length,) = struct.unpack("<Q", handle.read(8))
        handle.read(length)
    elif value_type == _GGUF_ARRAY:
        (element_type,) = struct.unpack("<I", handle.read(4))
        (count,) = struct.unpack("<Q", handle.read(8))
        for _ in range(count):
            _gguf_skip(handle, element_type)
    else:
        handle.read(_GGUF_FIXED_WIDTHS[value_type])
