from __future__ import annotations

import json
import os
import re
import struct
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import NamedTuple

from tokenizers import Regex, Tokenizer, models, normalizers, pre_tokenizers

from origenerator import config
from origenerator.box_breaks import flowed
from origenerator.workflows import WORKFLOW_REGISTRY
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
_EMBEDDING = "embedding:"
_AN_EMBEDDING = re.compile(r"(?<=\s)embedding:")
_ESCAPED = {"\0\1": ")", "\0\2": "("}


class _Reader(NamedTuple):
    files: Callable[[dict], tuple[Path | None, ...]]
    build: Callable[..., Tokenizer | None]
    reads_well: int
    past_it: str
    weighted: bool


_built: dict[tuple, Tokenizer] = {}


@dataclass(frozen=True)
class PromptReading:
    reads_well: int
    past_it: str
    weighted: bool
    tokenizer: Tokenizer

    def tokens(self, text: str) -> int:
        return sum(len(group) for group in self._groups(text))

    def pieces(self, text: str) -> list[tuple[int, int]]:
        if self.past_it != READ_IN_PIECES:
            return [(0, self.tokens(text))]
        starts, counts = [0], [0]
        for group in self._groups(text):
            splits = len(group) >= _CLIP_PHRASE_TOO_SHORT_TO_SPLIT
            while group:
                if counts[-1] + len(group) <= _CLIP_PIECE:
                    counts[-1] += len(group)
                    group = []
                    continue
                if splits:
                    room = _CLIP_PIECE - counts[-1]
                    counts[-1] += room
                    group = group[room:]
                starts.append(_opening_brackets_before(text, group[0]))
                counts.append(0)
        return list(zip(starts, counts))

    def flow(self, texts: list[str], *, start: int = 0, caret: tuple[int, int] | None = None
             ) -> tuple[list[str], tuple[int, int] | None]:
        return flowed(texts, self.tokens, limit=self.reads_well, start=start, caret=caret)

    def stops_at(self, text: str) -> int | None:
        if self.past_it != CUT_OFF:
            return None
        offsets = self.tokenizer.encode(text, add_special_tokens=False).offsets
        return offsets[self.reads_well][0] if len(offsets) > self.reads_well else None

    def _groups(self, text: str) -> list[list[int]]:
        if not self.weighted:
            return [self._token_starts(text, list(range(len(text))))]
        escaped = text.replace("\\)", "\0\1").replace("\\(", "\0\2")
        groups = []
        for segment, start in _weighted_segments(escaped, 0):
            plain, places = _unescaped(segment, start)
            for word, at in _words(plain):
                groups.append(self._token_starts(word, places[at:at + len(word)]))
        return [group for group in groups if group]

    def _token_starts(self, text: str, places: list[int]) -> list[int]:
        return [places[start] for start, _end in
                self.tokenizer.encode(text, add_special_tokens=False).offsets]


def prompt_reading(workflow_name: str, params: dict, key: str) -> PromptReading | None:
    found = _reader_named(_reader_of(WORKFLOW_REGISTRY.get(workflow_name), key), params)
    if found is None:
        return None
    reader, tokenizer = found
    return PromptReading(reader.reads_well, reader.past_it, reader.weighted, tokenizer)


def prompt_readings(workflow_name: str, params: dict) -> dict[str, PromptReading | None]:
    return {key: prompt_reading(workflow_name, params, key)
            for key in (*_TEXT_ENCODER_PROMPTS, *SOUND_PROMPT_KEYS)}


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


def _opening_brackets_before(text: str, position: int) -> int:
    while position > 0 and text[position - 1] == "(" and not text[:position - 1].endswith("\\"):
        position -= 1
    return position


def _weighted_segments(string: str, offset: int) -> list[tuple[str, int]]:
    segments = []
    for item, start in _bracketed(string, offset):
        if len(item) >= 2 and item[0] == "(" and item[-1] == ")":
            inner = item[1:-1]
            colon = inner.rfind(":")
            if colon > 0:
                try:
                    float(inner[colon + 1:])
                    inner = inner[:colon]
                except ValueError:
                    pass
            segments += _weighted_segments(inner, start + 1)
        else:
            segments.append((item, start))
    return segments


def _bracketed(string: str, offset: int) -> list[tuple[str, int]]:
    items, current, start, depth = [], "", offset, 0
    for index, char in enumerate(string, start=offset):
        if char == "(" and depth == 0:
            if current:
                items.append((current, start))
            current, start = "(", index
        elif char == ")" and depth == 1:
            items.append((current + ")", start))
            current = ""
        else:
            if not current:
                start = index
            current += char
        depth += {"(": 1, ")": -1}.get(char, 0)
    if current:
        items.append((current, start))
    return items


def _unescaped(segment: str, start: int) -> tuple[str, list[int]]:
    plain, places, index = [], [], 0
    while index < len(segment):
        pair = segment[index:index + 2]
        plain.append(_ESCAPED.get(pair, segment[index]))
        places.append(start + index)
        index += 2 if pair in _ESCAPED else 1
    return "".join(plain), places


def _words(plain: str) -> list[tuple[str, int]]:
    bounds = [0, *(found.start() for found in _AN_EMBEDDING.finditer(plain)), len(plain)]
    return [(plain[at:end], at) for at, end in zip(bounds, bounds[1:])
            if plain[at:end] and not plain[at:end].startswith(_EMBEDDING)]


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
