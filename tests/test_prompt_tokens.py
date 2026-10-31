from __future__ import annotations

import json
import shutil
import struct

import pytest
from tokenizers import pre_tokenizers

from origenerator import config
from origenerator.box_breaks import BOX_BREAK
from origenerator.prompt_tokens import (
    CUT_OFF,
    READ_IN_PIECES,
    READ_WHOLE,
    boxed_as_typed,
    prompt_reading,
    prompt_readings,
)
from origenerator.workflows import WORKFLOW_REGISTRY
from origenerator.workflows.prompt_readers import SOUND_PROMPT_KEYS
from tests.text_readers import clap_reader, clip_reader, word_reader

_UMT5_FILE = "example_umt5.safetensors"


@pytest.fixture
def comfyui(tmp_path, monkeypatch):
    root = tmp_path / "ComfyUI"
    monkeypatch.setattr(config, "COMFYUI_DIR", root)
    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path / "hub"))
    return root


def _byte_reader(root):
    folder = root / "comfy" / "text_encoders" / "qwen25_tokenizer"
    folder.mkdir(parents=True)
    alphabet = pre_tokenizers.ByteLevel.alphabet()
    (folder / "vocab.json").write_text(json.dumps({c: i for i, c in enumerate(sorted(alphabet))}),
                                       encoding="utf-8")
    (folder / "merges.txt").write_text("#version: 0.2\n", encoding="utf-8")


def _varint(value: int) -> bytes:
    out = bytearray()
    while True:
        low, value = value & 0x7F, value >> 7
        out.append(low | (0x80 if value else 0))
        if not value:
            return bytes(out)


def _field(number: int, payload: bytes) -> bytes:
    return _varint(number << 3 | 2) + _varint(len(payload)) + payload


def _piece(text: str, score: float, kind: int) -> bytes:
    return (_field(1, text.encode())
            + _varint(2 << 3 | 5) + struct.pack("<f", score)
            + _varint(3 << 3) + _varint(kind))


def _umt5_reader(root):
    pieces = [("<pad>", 0.0, 3), ("</s>", 0.0, 3), ("<unk>", 0.0, 2), ("▁cat", -1.0, 1),
              ("▁dog", -1.0, 1), ("▁", -2.0, 1)]
    pieces += [(char, -3.0, 1) for char in "catdog"]
    proto = b"".join(_field(1, _piece(*piece)) for piece in pieces)
    header = json.dumps({"spiece_model": {"dtype": "U8", "shape": [len(proto)],
                                          "data_offsets": [0, len(proto)]}}).encode()
    path = root / "models" / "text_encoders" / _UMT5_FILE
    path.parent.mkdir(parents=True)
    path.write_bytes(struct.pack("<Q", len(header)) + header + proto)


def _cats(count: int) -> str:
    return " ".join(["cat"] * count)


def _clip(comfyui):
    clip_reader(comfyui)
    return prompt_reading("sdxl_t2i", {}, "positive_prompt")


def test_an_sdxl_prompt_is_counted_in_clip_tokens_and_its_weights_are_not(comfyui):
    reading = _clip(comfyui)

    assert reading.tokens("(cat:1.2), dog") == 5
    assert (reading.reads_well, reading.past_it) == (75, READ_IN_PIECES)


def test_an_sdxl_prompt_of_75_tokens_or_fewer_is_read_in_one_piece(comfyui):
    assert _clip(comfyui).pieces(_cats(75)) == [(0, 75)]


def test_an_sdxl_prompt_past_75_tokens_is_cut_where_comfyui_cuts_it(comfyui):
    text = _cats(80)

    assert _clip(comfyui).pieces(text) == [(0, 75), (text.index("cat", 75 * 4), 5)]


def test_a_word_running_past_75_tokens_is_cut_in_the_middle_as_comfyui_cuts_it(comfyui):
    text = f"{_cats(74)} dog"

    assert _clip(comfyui).pieces(text) == [(0, 75), (text.index("dog") + 1, 2)]


def test_a_weighted_phrase_too_short_to_split_starts_the_next_piece_whole(comfyui):
    phrase = f"({_cats(7)})"
    text = f"{_cats(70)} {phrase} {_cats(70)}"

    assert _clip(comfyui).pieces(text) == [(0, 70), (text.index(phrase), 75), (
        text.index(phrase) + len(phrase) + 1 + 4 * 68, 2)]


def test_a_line_of_dashes_outside_a_story_is_part_of_the_one_prompt(comfyui):
    reading = _clip(comfyui)
    text = f"{_cats(40)}\n---\n{_cats(40)}"

    assert [tokens for _start, tokens in reading.pieces(text)] == [75, reading.tokens(text) - 75]


def test_an_escaped_bracket_is_read_as_a_bracket_where_the_pieces_are_cut(comfyui):
    text = _cats(74) + r" \(cat\) cat"

    pieces = _clip(comfyui).pieces(text)

    assert pieces[0] == (0, 75) and text[pieces[1][0]:].startswith("cat")


def test_a_flux_prompt_is_read_whole_by_t5(comfyui):
    word_reader(comfyui / "comfy" / "text_encoders" / "t5_tokenizer" / "tokenizer.json")

    reading = prompt_reading("flux_t2i_upscaled", {}, "positive_prompt")

    assert reading.tokens("(alpha beta:1.1) gamma") == 3
    assert (reading.reads_well, reading.past_it) == (511, READ_WHOLE)


def test_krea_2_reads_weight_marks_as_part_of_the_prompt(comfyui):
    _byte_reader(comfyui)

    reading = prompt_reading("krea2_t2i", {}, "positive_prompt")

    assert reading.tokens("(ab:1.2)") == 8
    assert (reading.reads_well, reading.past_it) == (507, READ_WHOLE)


def test_a_wan_prompt_is_counted_by_its_own_text_reader_file(comfyui):
    _umt5_reader(comfyui)

    reading = prompt_reading("wan22_i2v", {"clip_name": _UMT5_FILE}, "positive_prompt")

    assert reading.tokens("cat cat dog") == 3
    assert (reading.reads_well, reading.past_it) == (511, READ_WHOLE)


def test_a_sound_prompt_is_cut_off_after_76_tokens(comfyui, tmp_path):
    clap_reader(tmp_path / "hub")

    reading = prompt_reading("wan22_i2v", {}, "audio_prompt")

    assert reading.tokens("rain on a tin roof") == 5
    assert (reading.reads_well, reading.past_it) == (76, CUT_OFF)


def test_a_sound_prompt_past_its_cut_off_says_where_its_reader_stops(comfyui, tmp_path):
    clap_reader(tmp_path / "hub")
    read = " ".join(["rain"] * 76)
    reading = prompt_reading("wan22_i2v", {}, "audio_prompt")

    assert (reading.stops_at(f"{read} on a tin roof"), reading.stops_at("hiss")) == (
        len(read) + 1, None)


def test_a_form_hears_how_each_of_its_prompts_is_read(comfyui, tmp_path):
    clap_reader(tmp_path / "hub")
    _umt5_reader(comfyui)

    readings = prompt_readings("wan22_i2v", {"clip_name": _UMT5_FILE})

    assert {key: (reading.reads_well, reading.past_it) for key, reading in readings.items()} == {
        "positive_prompt": (511, READ_WHOLE), "negative_prompt": (511, READ_WHOLE),
        **dict.fromkeys(SOUND_PROMPT_KEYS, (76, CUT_OFF))}


def test_a_prompt_whose_text_reader_is_not_installed_is_of_unknown_length(comfyui):
    assert prompt_reading("sdxl_t2i", {}, "positive_prompt") is None


def test_a_field_no_text_reader_reads_has_no_length(comfyui):
    clip_reader(comfyui)

    assert prompt_reading("sdxl_t2i", {}, "seed") is None


def test_a_text_reader_is_read_from_its_files_once(comfyui):
    folder = clip_reader(comfyui)
    prompt_reading("sdxl_t2i", {}, "positive_prompt")
    shutil.rmtree(folder)

    assert prompt_reading("sdxl_t2i", {}, "positive_prompt").tokens("cat dog") == 4


@pytest.mark.parametrize("name", sorted(WORKFLOW_REGISTRY))
def test_every_prompt_comfyui_reads_names_its_text_reader(name):
    workflow = WORKFLOW_REGISTRY[name]
    prompts = {key for key in workflow.default_params() if key.endswith("prompt")}

    assert not workflow.generates_here or prompts - set(SOUND_PROMPT_KEYS) <= {
        "positive_prompt", "negative_prompt"}
    assert not workflow.generates_here or workflow.text_reader is not None


def test_a_new_sdxl_prompt_is_flowed_into_boxes_of_whole_words(comfyui):
    clip_reader(comfyui)

    assert boxed_as_typed("sdxl_t2i", {}, "positive_prompt", f"{_cats(74)} dog cat") == (
        f"{_cats(74)}{BOX_BREAK}dog cat")


def test_a_prompt_read_whole_is_never_flowed_into_boxes(comfyui):
    word_reader(comfyui / "comfy" / "text_encoders" / "t5_tokenizer" / "tokenizer.json")
    text = " ".join(["alpha"] * 600)

    assert boxed_as_typed("flux_t2i_upscaled", {}, "positive_prompt", text) == text


def test_a_new_prompt_whose_reader_is_not_installed_is_left_as_it_is(comfyui):
    assert boxed_as_typed("sdxl_t2i", {}, "positive_prompt", _cats(80)) == _cats(80)
