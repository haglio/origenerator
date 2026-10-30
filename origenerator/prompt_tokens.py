from __future__ import annotations

import json
import os
import struct
from collections.abc import Callable
from pathlib import Path, PureWindowsPath
from typing import NamedTuple

from tokenizers import Regex, Tokenizer, models, normalizers, pre_tokenizers

from origenerator import config
from origenerator.workflows import WORKFLOW_REGISTRY
from origenerator.workflows.base import scene_prompts
from origenerator.workflows.prompt_readers import CLIP, QWEN3VL, SOUND_PROMPT_KEYS, T5, UMT5

READ_IN_PIECES = "in pieces"
READ_WHOLE = "whole"
CUT_OFF = "cut off"

_CLAP = "clap"
_TEXT_ENCODER_PROMPTS = ("positive_prompt", "negative_prompt")
_CLIP_PIECE = 75
_CLIP_PHRASE_TOO_SHORT_TO_SPLIT = 8
_CLIP_WORDS = Regex(r"""'s|'t|'re|'ve|'m|'ll|'d|[\p{L}]+|[\p{N}]|[^\s\p{L}\p{N}]+""")
_QWEN_WORDS = Regex(r"""(?i:'s|'t|'re|'ve|'m|'ll|'d)|[^\r\n\p{L}\p{N}]?\p{L}+|\p{N}|"""
                    r""" ?[^\s\p{L}\p{N}]+[\r\n]*|\s*[\r\n]+|\s+(?!\S)|\s+""")
_SPIECE_UNKNOWN = 2


class SceneLength(NamedTuple):
    tokens: int
    pieces: int
    stops_at: int | None = None


class PromptLength(NamedTuple):
    scenes: tuple[SceneLength, ...]
    reads_well: int
    past_it: str


class _Reader(NamedTuple):
    files: Callable[[dict], tuple[Path | None, ...]]
    build: Callable[..., Tokenizer | None]
    reads_well: int
    past_it: str
    weighted: bool


_built: dict[tuple, Tokenizer] = {}


def prompt_length(workflow_name: str, params: dict, key: str) -> PromptLength | None:
    workflow = WORKFLOW_REGISTRY.get(workflow_name)
    found = _reader_named(_reader_of(workflow, key), params)
    if found is None:
        return None
    reader, tokenizer = found
    text = str(params.get(key) or "")
    scenes = scene_prompts(text) if key in workflow.scene_prompt_keys else [text]
    return PromptLength(tuple(_scene_length(reader, tokenizer, scene) for scene in scenes),
                        reader.reads_well, reader.past_it)


def where_reading_stops(workflow_name: str, params: dict) -> dict[str, int | None]:
    workflow = WORKFLOW_REGISTRY.get(workflow_name)
    lengths = {key: prompt_length(workflow_name, params, key) for key in params
               if _cuts_off(_reader_of(workflow, key))}
    return {key: length.scenes[0].stops_at for key, length in lengths.items()
            if length is not None}


def _cuts_off(name: str | None) -> bool:
    reader = _READERS.get(name)
    return reader is not None and reader.past_it == CUT_OFF


def _reader_of(workflow, key: str) -> str | None:
    if workflow is None or not workflow.generates_here:
        return None
    if key in SOUND_PROMPT_KEYS:
        return _CLAP
    return workflow.text_reader if key in _TEXT_ENCODER_PROMPTS else None


def _reader_named(name: str | None, params: dict) -> tuple[_Reader, Tokenizer] | None:
    reader = _READERS.get(name)
    if reader is None:
        return None
    files = reader.files(params)
    key = (name, *files)
    if key not in _built:
        if not all(path is not None and path.is_file() for path in files):
            return None
        tokenizer = reader.build(*files)
        if tokenizer is None:
            return None
        _built[key] = tokenizer
    return reader, _built[key]


def _scene_length(reader: _Reader, tokenizer: Tokenizer, text: str) -> SceneLength:
    if reader.past_it == CUT_OFF:
        offsets = tokenizer.encode(text, add_special_tokens=False).offsets
        past_it = len(offsets) > reader.reads_well
        return SceneLength(len(offsets), 1, offsets[reader.reads_well][0] if past_it else None)
    phrases = _unweighted_phrases(text) if reader.weighted else [text]
    sizes = [len(tokenizer.encode(phrase, add_special_tokens=False).ids)
             for phrase in phrases if phrase]
    pieces = _clip_pieces(sizes) if reader.past_it == READ_IN_PIECES else 1
    return SceneLength(sum(sizes), pieces)


def _clip_pieces(sizes: list[int]) -> int:
    pieces, used = 1, 0
    for size in sizes:
        splits = size >= _CLIP_PHRASE_TOO_SHORT_TO_SPLIT
        while size:
            if used + size > _CLIP_PIECE:
                if splits:
                    size -= _CLIP_PIECE - used
                pieces, used = pieces + 1, 0
            else:
                used, size = used + size, 0
    return pieces


def _unweighted_phrases(text: str) -> list[str]:
    hidden = text.replace("\\)", "\0\1").replace("\\(", "\0\2")
    return [phrase.replace("\0\1", ")").replace("\0\2", "(") for phrase in _phrases(hidden)]


def _phrases(text: str) -> list[str]:
    phrases = []
    for part in _parenthesized(text):
        if len(part) >= 2 and part[0] == "(" and part[-1] == ")":
            phrases += _phrases(_without_weight(part[1:-1]))
        else:
            phrases.append(part)
    return phrases


def _without_weight(text: str) -> str:
    colon = text.rfind(":")
    if colon > 0:
        try:
            float(text[colon + 1:])
        except ValueError:
            return text
        return text[:colon]
    return text


def _parenthesized(text: str) -> list[str]:
    parts, current, depth = [], "", 0
    for char in text:
        if char == "(":
            if depth == 0:
                if current:
                    parts.append(current)
                current = "("
            else:
                current += char
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                parts.append(current + ")")
                current = ""
            else:
                current += char
        else:
            current += char
    if current:
        parts.append(current)
    return parts


def _shipped_with_comfyui(*parts: str) -> Path:
    return config.COMFYUI_DIR.joinpath("comfy", *parts)


def _vocab_and_merges(folder: Path) -> tuple[Path, Path]:
    return folder / "vocab.json", folder / "merges.txt"


def _clip(vocab: Path, merges: Path) -> Tokenizer:
    words, pairs = models.BPE.read_file(str(vocab), str(merges))
    tokenizer = Tokenizer(models.BPE(words, pairs, unk_token="<|endoftext|>",
                                     continuing_subword_prefix="", end_of_word_suffix="</w>",
                                     fuse_unk=False))
    tokenizer.normalizer = normalizers.Sequence([
        normalizers.NFC(), normalizers.Replace(Regex(r"\s+"), " "), normalizers.Lowercase()])
    tokenizer.pre_tokenizer = pre_tokenizers.Sequence([
        pre_tokenizers.Split(_CLIP_WORDS, behavior="removed", invert=True),
        pre_tokenizers.ByteLevel(add_prefix_space=False)])
    return tokenizer


def _qwen(vocab: Path, merges: Path) -> Tokenizer:
    words, pairs = models.BPE.read_file(str(vocab), str(merges))
    tokenizer = Tokenizer(models.BPE(words, pairs, continuing_subword_prefix="",
                                     end_of_word_suffix="", fuse_unk=False))
    tokenizer.normalizer = normalizers.NFC()
    tokenizer.pre_tokenizer = pre_tokenizers.Sequence([
        pre_tokenizers.Split(_QWEN_WORDS, behavior="isolated", invert=False),
        pre_tokenizers.ByteLevel(add_prefix_space=False, use_regex=False)])
    return tokenizer


def _from_file(path: Path) -> Tokenizer:
    return Tokenizer.from_file(str(path))


def _text_encoder_file(name) -> Path | None:
    if not name:
        return None
    relative = Path(*PureWindowsPath(str(name)).parts)
    folders = [config.COMFYUI_DIR / "models" / folder for folder in ("text_encoders", "clip")]
    return next((folder / relative for folder in folders if (folder / relative).is_file()), None)


def _umt5(encoder: Path) -> Tokenizer | None:
    proto = _spiece_model(encoder)
    if proto is None:
        return None
    pieces, unknown, charsmap = [], 0, b""
    for number, value in _proto_fields(proto):
        if number == 1:
            text, score, kind = _spiece_piece(value)
            if kind == _SPIECE_UNKNOWN:
                unknown = len(pieces)
            pieces.append((text, score))
        elif number == 3:
            charsmap = dict(_proto_fields(value)).get(2, b"")
    tokenizer = Tokenizer(models.Unigram(pieces, unknown, False))
    steps = [normalizers.Precompiled(charsmap)] if charsmap else []
    tokenizer.normalizer = normalizers.Sequence([*steps, normalizers.Replace(Regex(" {2,}"), " ")])
    tokenizer.pre_tokenizer = pre_tokenizers.Metaspace(replacement="▁",
                                                       prepend_scheme="always")
    return tokenizer


def _spiece_model(encoder: Path) -> bytes | None:
    with encoder.open("rb") as handle:
        (size,) = struct.unpack("<Q", handle.read(8))
        entry = json.loads(handle.read(size)).get("spiece_model")
        if entry is None:
            return None
        start, end = entry["data_offsets"]
        handle.seek(8 + size + start)
        return handle.read(end - start)


def _spiece_piece(proto: bytes) -> tuple[str, float, int]:
    fields = dict(_proto_fields(proto))
    score = struct.unpack("<f", fields[2])[0] if 2 in fields else 0.0
    return fields.get(1, b"").decode("utf-8"), score, fields.get(3, 1)


def _proto_fields(data: bytes) -> list[tuple[int, object]]:
    fields, at = [], 0
    while at < len(data):
        key, at = _varint(data, at)
        number, wire = key >> 3, key & 7
        if wire == 0:
            value, at = _varint(data, at)
        elif wire == 1:
            value, at = data[at:at + 8], at + 8
        elif wire == 2:
            length, at = _varint(data, at)
            value, at = data[at:at + length], at + length
        else:
            value, at = data[at:at + 4], at + 4
        fields.append((number, value))
    return fields


def _varint(data: bytes, at: int) -> tuple[int, int]:
    value = shift = 0
    while True:
        byte = data[at]
        at += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, at
        shift += 7


def _hub_file(repo: str, name: str) -> Path | None:
    home = Path(os.environ.get("HF_HOME") or Path.home() / ".cache" / "huggingface")
    folder = Path(os.environ.get("HF_HUB_CACHE") or home / "hub") / f"models--{repo.replace('/', '--')}"
    try:
        revision = (folder / "refs" / "main").read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return folder / "snapshots" / revision / name


_READERS = {
    CLIP: _Reader(lambda _params: _vocab_and_merges(_shipped_with_comfyui("sd1_tokenizer")),
                  _clip, _CLIP_PIECE, READ_IN_PIECES, weighted=True),
    T5: _Reader(lambda _params: (_shipped_with_comfyui("text_encoders", "t5_tokenizer",
                                                         "tokenizer.json"),),
                _from_file, 511, READ_WHOLE, weighted=True),
    QWEN3VL: _Reader(lambda _params: _vocab_and_merges(
        _shipped_with_comfyui("text_encoders", "qwen25_tokenizer")),
        _qwen, 507, READ_WHOLE, weighted=False),
    UMT5: _Reader(lambda params: (_text_encoder_file(params.get("clip_name")),),
                  _umt5, 511, READ_WHOLE, weighted=True),
    _CLAP: _Reader(lambda _params: (_hub_file("laion/larger_clap_general", "tokenizer.json"),),
                   _from_file, 76, CUT_OFF, weighted=False),
}
