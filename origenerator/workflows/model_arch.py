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
WAN_S2V = "wan_s2v"
WAN_ANIMATE = "wan_animate"
WAN_T2V = "wan_t2v"
WAN_FUN_CONTROL = "wan_fun_control"
LTX = "ltx"
KREA2 = "krea2"

# No real safetensors header comes near this: a longer length means a corrupt or misidentified file,
# and reading that many bytes would pull the whole model into memory.
_MAX_HEADER_BYTES = 32 * 1024 * 1024

# A full-size GGUF model lists thousands of tensor names.
_GGUF_NAMES_ENOUGH_TO_TELL = 400

# Prefixes that wrap an otherwise-normal safetensors state dict. The same WAN model ships both bare
# (``blocks.0.x``) and wrapped (``model.diffusion_model.blocks.0.x``), and a ControlNet wraps the whole net in
# ``control_model.``, so the wrapper is stripped before anything is matched, or half the signatures below would miss.
_WRAPPERS = (
    "model.diffusion_model.", "diffusion_model.", "control_model.",
    "model.", "transformer.",
)

# Tensor-name fragments only a LoRA's safetensors have: the A/B pair of the diffusers form,
# the down/up pair of the kohya form, and kohya's flattened module prefixes.
_LORA_MARKERS = ("lora_A.", "lora_B.", "lora_down.", "lora_up.", "lora_unet_", "lora_te")

# A sharded download (``-00001-of-00006.safetensors``). Each part holds a slice of the tensors and ComfyUI loads
# none on its own, so listing them offers six broken picks in place of one model that isn't selectable at all.
_SHARD = re.compile(r"-\d+-of-\d+\.[^.]+$")

# WAN 2.2 trains a high-noise and a low-noise expert, and which one a file is lives only in its name.
# Anchored so a word merely *containing* the letters can't match: "low" needs a non-letter before it
# (``-low-``, ``_low_``) or a camel-case hump (``t2vLowV30``), since "yellow", "slow" and "flow" name installed LoRAs.
_EXPERT_CAMEL = re.compile(r"(?<=[a-z0-9])(High|Low)")
_EXPERT_BOUNDED = re.compile(r"(?:^|[^A-Za-z])(high|low)", re.IGNORECASE)
_EXPERT_AFTER_PRECISION = re.compile(r"(?:fp|bf)\d+([HL])\.[^.]+$", re.IGNORECASE)
_EXPERT_INITIALS = {"h": "high", "l": "low"}

# What a Krea 2 block holds and a WAN block never does -- wq/wk/wv/wo and a gated
# MLP -- dotted, or flattened as lycoris spells it (`lycoris_blocks_0_attn_wq`).
_KREA2_BLOCK = re.compile(r"blocks[._]\d+[._](?:attn[._]w[qkvo]|mlp[._](?:gate|up|down))")

# kohya's flattened SD UNet, which is how the enhance's fix training writes a LoRA with no text encoder
# in it. SDXL stacks transformer blocks in an attention where SD1.5 has one, so a
# second block tells the two apart without the encoders.
_SD_UNET_LORA = re.compile(r"^lora_unet_(?:input|output|middle)_block")
_SDXL_STACKED_BLOCKS = re.compile(r"transformer_blocks_[1-9]")

_WAN_LATENT_CHANNELS = 16


@dataclass(frozen=True)
class ModelFile:
    arch: str | None
    is_lora: bool
    expert: str | None
    is_shard: bool
    precision: str | None = None


@dataclass(frozen=True)
class _Tensor:
    shape: list[int] | None
    stored_as: str | int
    count: int


_SAFETENSORS_PRECISIONS = {"F16": "fp16", "BF16": "bf16", "F8_E4M3": "fp8", "F8_E5M2": "fp8", "I8": "int8"}
_GGUF_F16, _GGUF_Q8_0, _GGUF_BF16 = 1, 8, 30
_GGUF_PRECISIONS = {_GGUF_F16: "fp16", _GGUF_Q8_0: "Q8", _GGUF_BF16: "bf16"}


# A safetensors or GGUF model is a file of gigabytes to open.
_HEADERS_PATH = config.STATE_DIR / "model_headers.json"
_THIS_READER = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()[:16]


def describe(path: Path) -> ModelFile:
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
    if not isinstance(saved, dict) or _was_taken_by_another_reader(saved):
        return {}
    remembered = {}
    for entry in saved.get("entries", ()):
        try:
            remembered[(entry["path"], entry["size"], entry["mtime_ns"])] = ModelFile(
                arch=entry["arch"], is_lora=entry["is_lora"], expert=entry["expert"],
                is_shard=entry["is_shard"], precision=entry["precision"])
        except (KeyError, TypeError):
            continue
    return remembered


def _was_taken_by_another_reader(saved: dict) -> bool:
    return saved.get("reader") != _THIS_READER


def _remember(described: dict[tuple[str, int, int], ModelFile]) -> None:
    entries = [{"path": path, "size": size, "mtime_ns": mtime_ns, **asdict(file)}
               for (path, size, mtime_ns), file in described.items()]
    try:
        _HEADERS_PATH.parent.mkdir(parents=True, exist_ok=True)
        written = _HEADERS_PATH.with_name(_HEADERS_PATH.name + ".tmp")
        written.write_text(json.dumps({"reader": _THIS_READER, "entries": entries}),
                           encoding="utf-8")
        written.replace(_HEADERS_PATH)
    except OSError:
        return


def _describe(path: Path) -> ModelFile:
    if _SHARD.search(path.name):
        return ModelFile(arch=None, is_lora=False, expert=None, is_shard=True)
    tensors = _tensor_index(path)
    expert = _expert_from_name(path.name)
    if tensors is None:
        return ModelFile(arch=None, is_lora=False, expert=expert, is_shard=False)
    return ModelFile(
        arch=_arch_from({name: tensor.shape for name, tensor in tensors.items()}),
        is_lora=any(marker in key for key in tensors for marker in _LORA_MARKERS),
        expert=expert,
        is_shard=False,
        precision=_precision_of(tensors, path.suffix),
    )


def _precision_of(tensors: dict[str, _Tensor], suffix: str) -> str | None:
    counted: dict[str | int, int] = {}
    for tensor in tensors.values():
        counted[tensor.stored_as] = counted.get(tensor.stored_as, 0) + tensor.count
    if not counted:
        return None
    most = max(counted, key=counted.__getitem__)
    return (_GGUF_PRECISIONS if suffix == ".gguf" else _SAFETENSORS_PRECISIONS).get(most)


def _expert_from_name(name: str) -> str | None:
    found = {
        match.group(0).lower().strip("-_. ")
        for match in (*_EXPERT_BOUNDED.finditer(name), *_EXPERT_CAMEL.finditer(name))
    }
    found = {word for word in found if word in ("high", "low")}
    found |= {_EXPERT_INITIALS[match.group(1).lower()]
              for match in _EXPERT_AFTER_PRECISION.finditer(name)}
    return found.pop() if len(found) == 1 else None


def _components(keys: list[str]) -> set[str]:
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
    keys = list(shapes)
    components = _components(keys)

    def has(*names: str) -> bool:
        return any(name in components for name in names)

    def starts(*prefixes: str) -> bool:
        return any(c.startswith(p) for c in components for p in prefixes)

    # SDXL first: its files show the two text encoders as `conditioner.` in a checkpoint, as the extra
    # size/pooled conditioning (`label_emb`, `add_embedding`) in a bare UNet or ControlNet, and as the paired
    # `lora_te1_`/`lora_te2_` in a LoRA, where SD1.5's single `lora_te_` would otherwise claim it below.
    if has("conditioner", "label_emb", "add_embedding") or starts("lora_te1_", "lora_te2_"):
        return SDXL
    if any(_SD_UNET_LORA.match(key) for key in keys):
        return SDXL if any(_SDXL_STACKED_BLOCKS.search(key) for key in keys) else SD15
    # Flux before Qwen and LTX: diffusers-form Flux LoRAs carry plain
    # `transformer_blocks` too, and only the `single_` twin separates them.
    if (has("double_blocks", "single_blocks", "single_transformer_blocks", "guidance_in")
            or starts("lora_unet_double_blocks", "lora_unet_single_blocks")):
        return FLUX
    # LTX before Qwen, same reason: its files hold `transformer_blocks` as well,
    # and these three names are what is only ever LTX.
    if has("patchify_proj", "adaln_single", "caption_projection"):
        return LTX
    if has("transformer_blocks"):
        return QWEN
    return _arch_after_the_transformer_families(shapes, keys, has, starts)


def _arch_after_the_transformer_families(shapes, keys, has, starts) -> str | None:
    # Krea 2 before WAN: its single-stream `blocks.N` would read as WAN's. The text-fusion
    # adapter beside them is what only it has, and a LoRA trained on the blocks alone shows what only its blocks hold.
    if has("txtfusion") or any(_KREA2_BLOCK.search(key) for key in keys):
        return KREA2
    # WAN S2V and WAN Animate before WAN: each is WAN's `blocks.N` with one thing beside them only it has
    # -- the audio injector, the pose embedding.
    if has("audio_injector"):
        return WAN_S2V
    if has("pose_patch_embedding", "face_adapter"):
        return WAN_ANIMATE
    # WAN: bare `blocks.N` (never `input_blocks`/`double_blocks`, which is why this is safe after the
    # families above), the patch/text/time embeddings around them, VACE's parallel stack, or a kohya LoRA's flattened form.
    if (has("blocks", "patch_embedding", "text_embedding", "time_projection", "vace_blocks")
            or starts("lora_unet_blocks_")):
        return _wan_kind(shapes)
    # SD1.5 last, as the family defined by lacking SDXL's additions: its checkpoint marker, its
    # single-text-encoder LoRA marker, and the original ControlNet shape.
    if has("cond_stage_model", "zero_convs", "input_hint_block") or starts("lora_te_"):
        return SD15
    return None


def _tensor_index(path: Path) -> dict[str, _Tensor] | None:
    try:
        if path.suffix == ".safetensors":
            return _safetensors_tensors(path)
        if path.suffix == ".gguf":
            return _gguf_tensors(path)
    except (OSError, struct.error, UnicodeDecodeError, ValueError, KeyError):
        return None
    return None


def _safetensors_header(path: Path) -> dict | None:
    with path.open("rb") as handle:
        (length,) = struct.unpack("<Q", handle.read(8))
        if length > _MAX_HEADER_BYTES:
            return None
        header = handle.read(length)
    if len(header) < length:
        return None
    return json.loads(header)


def _safetensors_tensors(path: Path) -> dict[str, _Tensor] | None:
    index = _safetensors_header(path)
    if not isinstance(index, dict):
        return None
    return {key: _safetensors_tensor(entry) for key, entry in index.items() if key != "__metadata__"}


def _safetensors_tensor(entry) -> _Tensor:
    if not isinstance(entry, dict):
        return _Tensor(shape=None, stored_as="", count=0)
    shape = entry.get("shape")
    return _Tensor(shape=shape, stored_as=str(entry.get("dtype", "")), count=_count(shape or ()))


def _count(dimensions) -> int:
    count = 1
    for dimension in dimensions:
        count *= int(dimension)
    return count


def safetensors_metadata(path: Path) -> dict:
    try:
        header = _safetensors_header(path)
    except (OSError, struct.error, UnicodeDecodeError, ValueError):
        return {}
    metadata = header.get("__metadata__") if isinstance(header, dict) else None
    return metadata if isinstance(metadata, dict) else {}


# GGUF's metadata values are typed; every type but string and array is a fixed width, so skipping the metadata to reach the
# tensor index is a matter of stepping over the right number of bytes per value.
_GGUF_FIXED_WIDTHS = {0: 1, 1: 1, 2: 2, 3: 2, 4: 4, 5: 4, 6: 4, 7: 1, 10: 8, 11: 8, 12: 8}
_GGUF_STRING = 8
_GGUF_ARRAY = 9
# GGUF lays out everything read here the same way in its versions 2 and 3.
_GGUF_VERSION_WIDTH = 4
_GGUF_DIMENSION_WIDTH = 8
_GGUF_TENSOR_TYPE_WIDTH = 4
_GGUF_TENSOR_OFFSET_WIDTH = 8


def _gguf_tensors(path: Path) -> dict[str, _Tensor] | None:
    with path.open("rb") as handle:
        if handle.read(4) != b"GGUF":
            return None
        handle.read(_GGUF_VERSION_WIDTH)
        tensor_count, kv_count = struct.unpack("<QQ", handle.read(16))
        for _ in range(kv_count):
            (key_length,) = struct.unpack("<Q", handle.read(8))
            handle.read(key_length)
            (value_type,) = struct.unpack("<I", handle.read(4))
            _gguf_skip(handle, value_type)
        tensors = {}
        for _ in range(min(tensor_count, _GGUF_NAMES_ENOUGH_TO_TELL)):
            (name_length,) = struct.unpack("<Q", handle.read(8))
            name = handle.read(name_length).decode("utf-8")
            (dimensions,) = struct.unpack("<I", handle.read(4))
            shape = struct.unpack(f"<{dimensions}Q", handle.read(_GGUF_DIMENSION_WIDTH * dimensions))
            (stored_as,) = struct.unpack("<I", handle.read(_GGUF_TENSOR_TYPE_WIDTH))
            handle.read(_GGUF_TENSOR_OFFSET_WIDTH)
            tensors[name] = _Tensor(shape=None, stored_as=stored_as, count=_count(shape))
    return tensors


def _gguf_skip(handle, value_type: int) -> None:
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
