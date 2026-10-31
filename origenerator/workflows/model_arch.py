"""Read what a model file *is* off its own header, so a picker can offer only
the files the graph under it can actually run -- never off its name, and never
guessing: an unrecognized file reads as ``None``, which every picker keeps.
"""
from __future__ import annotations

import hashlib
import json
import re
import struct
from dataclasses import asdict, dataclass
from functools import cache
from pathlib import Path

from origenerator import config

SDXL = "sdxl"
SD15 = "sd15"
FLUX = "flux"
QWEN = "qwen"
WAN = "wan"
# WAN 2.2's speech-to-video model: the WAN layout plus the audio injector that
# lets it lip-sync, and a family of its own because it is one -- an i2v dropdown
# that took it would run without the audio it needs, and the speech dropdown must
# not offer the i2v experts, which have no ear.
WAN_S2V = "wan_s2v"
# WAN 2.2 Animate: WAN with the pose embedding that follows a video's person.
WAN_ANIMATE = "wan_animate"
WAN_T2V = "wan_t2v"
WAN_FUN_CONTROL = "wan_fun_control"
LTX = "ltx"
KREA2 = "krea2"

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
_EXPERT_AFTER_PRECISION = re.compile(r"(?:fp|bf)\d+([HL])\.[^.]+$", re.IGNORECASE)
_EXPERT_INITIALS = {"h": "high", "l": "low"}

# What a Krea 2 block holds and a WAN block never does -- wq/wk/wv/wo and a gated
# MLP -- dotted, or flattened as lycoris spells it (`lycoris_blocks_0_attn_wq`).
_KREA2_BLOCK = re.compile(r"blocks[._]\d+[._](?:attn[._]w[qkvo]|mlp[._](?:gate|up|down))")

# kohya's flattened SD UNet, which is how the enhance's fix training writes a
# LoRA with no text encoder in it. SDXL stacks transformer blocks in an attention
# where SD1.5 has one, so a second block tells the two apart without the encoders.
_SD_UNET_LORA = re.compile(r"^lora_unet_(?:input|output|middle)_block")
_SDXL_STACKED_BLOCKS = re.compile(r"transformer_blocks_[1-9]")

_WAN_LATENT_CHANNELS = 16


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


# What each model file turned out to be, kept between launches: a header is a
# file of gigabytes opened, and a file unchanged in size and time reads the same.
_HEADERS_PATH = config.STATE_DIR / "model_headers.json"
_READER_DIGEST = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()[:16]


def describe(path: Path) -> ModelFile:
    """Classify *path* from its header and its name, without loading weights."""
    try:
        stat = path.stat()
    except OSError:
        return _describe(path)
    key = (str(path), stat.st_size, stat.st_mtime_ns)
    remembered = _remembered()
    if key not in remembered:
        remembered[key] = _describe(path)
        _remember(remembered)
    return remembered[key]


@cache
def _remembered() -> dict[tuple[str, int, int], ModelFile]:
    return _read_remembered(_HEADERS_PATH)


def _read_remembered(path: Path) -> dict[tuple[str, int, int], ModelFile]:
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(saved, dict) or saved.get("reader") != _READER_DIGEST:
        return {}
    remembered = {}
    for entry in saved.get("entries", ()):
        try:
            remembered[(entry["path"], entry["size"], entry["mtime_ns"])] = ModelFile(
                arch=entry["arch"], is_lora=entry["is_lora"], expert=entry["expert"],
                is_shard=entry["is_shard"])
        except (KeyError, TypeError):
            continue
    return remembered


def _remember(described: dict[tuple[str, int, int], ModelFile]) -> None:
    entries = [{"path": path, "size": size, "mtime_ns": mtime_ns, **asdict(file)}
               for (path, size, mtime_ns), file in described.items()]
    try:
        _HEADERS_PATH.parent.mkdir(parents=True, exist_ok=True)
        written = _HEADERS_PATH.with_name(_HEADERS_PATH.name + ".tmp")
        written.write_text(json.dumps({"reader": _READER_DIGEST, "entries": entries}),
                           encoding="utf-8")
        written.replace(_HEADERS_PATH)
    except OSError:
        return  # a launch that cannot write its state reads the headers again


def _describe(path: Path) -> ModelFile:
    if _SHARD.search(path.name):
        return ModelFile(arch=None, is_lora=False, expert=None, is_shard=True)
    shapes = _tensor_shapes(path)
    expert = _expert_from_name(path.name)
    if shapes is None:
        return ModelFile(arch=None, is_lora=False, expert=expert, is_shard=False)
    return ModelFile(
        arch=_arch_from(shapes),
        is_lora=any(marker in key for key in shapes for marker in _LORA_MARKERS),
        expert=expert,
        is_shard=False,
    )


def _expert_from_name(name: str) -> str | None:
    """Which WAN 2.2 expert the filename claims, or ``None`` when it says nothing.

    A name carrying both markers claims nothing usable, so it reads as unmarked
    and stays offered in either dropdown.
    """
    found = {
        match.group(0).lower().strip("-_. ")
        for match in (*_EXPERT_BOUNDED.finditer(name), *_EXPERT_CAMEL.finditer(name))
    }
    found = {word for word in found if word in ("high", "low")}
    found |= {_EXPERT_INITIALS[match.group(1).lower()]
              for match in _EXPERT_AFTER_PRECISION.finditer(name)}
    return found.pop() if len(found) == 1 else None


def _components(keys: list[str]) -> set[str]:
    """The leading component of every tensor name, wrappers stripped.

    kohya-form LoRAs flatten a whole module path into one component
    (``lora_unet_double_blocks_0_img_attn_qkv``), so the signatures below test
    these by prefix as well as by equality.
    """
    return {_unwrapped(key).split(".")[0] for key in keys}


def _unwrapped(key: str) -> str:
    for wrapper in _WRAPPERS:
        if key.startswith(wrapper):
            return key[len(wrapper):]
    return key


def _wan_kind(shapes: dict[str, list[int] | None]) -> str:
    if any(_unwrapped(key).startswith("ref_conv.") for key in shapes):
        return WAN_FUN_CONTROL
    patches = next((shape for key, shape in shapes.items()
                    if _unwrapped(key) == "patch_embedding.weight"), None)
    takes_the_latent_alone = bool(patches) and len(patches) > 1 and (
        patches[1] == _WAN_LATENT_CHANNELS)
    return WAN_T2V if takes_the_latent_alone else WAN


def _arch_from(shapes: dict[str, list[int] | None]) -> str | None:
    """The architecture these tensor names belong to, or ``None`` if unrecognized.

    Order is load-bearing: several families share a component name and are told
    apart only by a marker one of them also has, so the more specific signature
    has to be asked first. Each rule below says which collision it settles.
    """
    keys = list(shapes)
    components = _components(keys)

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
    if any(_SD_UNET_LORA.match(key) for key in keys):
        return SDXL if any(_SDXL_STACKED_BLOCKS.search(key) for key in keys) else SD15
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
    # Krea 2 before WAN: its single-stream `blocks.N` would read as WAN's. The
    # text-fusion adapter beside them is what only it has, and a LoRA trained
    # on the blocks alone shows what only its blocks hold.
    if has("txtfusion") or any(_KREA2_BLOCK.search(key) for key in keys):
        return KREA2
    # WAN S2V and WAN Animate before WAN: each is WAN's `blocks.N` with one
    # thing beside them only it has -- the audio injector, the pose embedding.
    if has("audio_injector"):
        return WAN_S2V
    if has("pose_patch_embedding", "face_adapter"):
        return WAN_ANIMATE
    # WAN: bare `blocks.N` (never `input_blocks`/`double_blocks`, which is why
    # this is safe after the families above), the patch/text/time embeddings
    # around them, VACE's parallel stack, or a kohya LoRA's flattened form.
    if (has("blocks", "patch_embedding", "text_embedding", "time_projection", "vace_blocks")
            or starts("lora_unet_blocks_")):
        return _wan_kind(shapes)
    # SD1.5 last, as the family defined by lacking SDXL's additions: its
    # checkpoint marker, its single-text-encoder LoRA marker, and the original
    # ControlNet shape, which is SD1.5's only because no SDXL marker fired.
    if has("cond_stage_model", "zero_convs", "input_hint_block") or starts("lora_te_"):
        return SD15
    return None


def _tensor_shapes(path: Path) -> dict[str, list[int] | None] | None:
    """Each tensor name in *path* and its shape, or ``None`` when they can't be read.

    ``None`` covers every "we could not tell" case — a format with no readable
    index (``.ckpt``, ``.pt``), a truncated or corrupt file, a header too large
    to be a header — and callers keep those rather than judging them.
    """
    try:
        if path.suffix == ".safetensors":
            return _safetensors_shapes(path)
        if path.suffix == ".gguf":
            names = _gguf_names(path)
            return None if names is None else dict.fromkeys(names)
    except (OSError, struct.error, UnicodeDecodeError, ValueError, KeyError):
        return None   # KeyError: a GGUF metadata value of a type we don't know
    return None


def _safetensors_header(path: Path) -> dict | None:
    """safetensors: a little-endian u64 byte length, then that much JSON."""
    with path.open("rb") as handle:
        (length,) = struct.unpack("<Q", handle.read(8))
        if length > _MAX_HEADER_BYTES:
            return None
        header = handle.read(length)
    if len(header) < length:
        return None   # truncated: never saw the index we would be judging
    return json.loads(header)


def _safetensors_shapes(path: Path) -> dict[str, list[int] | None] | None:
    index = _safetensors_header(path)
    if not isinstance(index, dict):
        return None
    return {key: entry.get("shape") if isinstance(entry, dict) else None
            for key, entry in index.items() if key != "__metadata__"}


def safetensors_metadata(path: Path) -> dict:
    try:
        header = _safetensors_header(path)
    except (OSError, struct.error, UnicodeDecodeError, ValueError):
        return {}
    metadata = header.get("__metadata__") if isinstance(header, dict) else None
    return metadata if isinstance(metadata, dict) else {}


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
