from __future__ import annotations

import json
import shutil
import string
import struct

import pytest
from tokenizers import pre_tokenizers

from origenerator import config
from origenerator.prompt_tokens import (
    CUT_OFF,
    READ_IN_PIECES,
    READ_WHOLE,
    prompt_length,
    where_reading_stops,
)
from origenerator.workflows import WORKFLOW_REGISTRY
from origenerator.workflows.base import ParamType
from origenerator.workflows.prompt_readers import SOUND_PROMPT_KEYS
from tests.text_readers import clap_reader, word_reader

_UMT5_FILE = "example_umt5.safetensors"


@pytest.fixture
def comfyui(tmp_path, monkeypatch):
    root = tmp_path / "ComfyUI"
    monkeypatch.setattr(config, "COMFYUI_DIR", root)
    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path / "hub"))
    return root


def _clip_reader(root):
    folder = root / "comfy" / "sd1_tokenizer"
    folder.mkdir(parents=True)
    pieces = ["<|startoftext|>", "<|endoftext|>"]
    for char in string.ascii_lowercase + string.digits + ",.:()":
        pieces += [char, f"{char}</w>"]
    pieces += ["ca", "cat</w>"]
    (folder / "vocab.json").write_text(json.dumps({p: i for i, p in enumerate(pieces)}),
                                       encoding="utf-8")
    (folder / "merges.txt").write_text("#version: 0.2\nc a\nca t</w>\n", encoding="utf-8")
    return folder


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


def test_an_sdxl_prompt_is_counted_in_clip_tokens_and_its_weights_are_not(comfyui):
    _clip_reader(comfyui)

    length = prompt_length("sdxl_t2i", {"positive_prompt": "(cat:1.2), dog"}, "positive_prompt")

    assert [scene.tokens for scene in length.scenes] == [5]
    assert (length.reads_well, length.past_it) == (75, READ_IN_PIECES)


def test_an_sdxl_prompt_past_75_tokens_is_read_in_two_pieces(comfyui):
    _clip_reader(comfyui)

    length = prompt_length("sdxl_t2i", {"negative_prompt": _cats(80)}, "negative_prompt")

    assert (length.scenes[0].tokens, length.scenes[0].pieces) == (80, 2)


def test_a_weighted_phrase_too_short_to_split_starts_the_next_piece_whole(comfyui):
    _clip_reader(comfyui)
    phrase = f"({_cats(7)})"
    prompt = f"{_cats(70)} {phrase} {_cats(70)} {phrase} {_cats(70)}"

    length = prompt_length("sdxl_t2i", {"positive_prompt": prompt}, "positive_prompt")

    assert (length.scenes[0].tokens, length.scenes[0].pieces) == (224, 4)


def test_a_line_of_dashes_outside_a_story_is_part_of_the_one_prompt(comfyui):
    _clip_reader(comfyui)

    length = prompt_length("sdxl_t2i", {"positive_prompt": "cat\n---\ncat"}, "positive_prompt")

    assert len(length.scenes) == 1


def test_a_flux_prompt_is_read_whole_by_t5(comfyui):
    word_reader(comfyui / "comfy" / "text_encoders" / "t5_tokenizer" / "tokenizer.json")

    length = prompt_length("flux_t2i_upscaled", {"positive_prompt": "(alpha beta:1.1) gamma"},
                           "positive_prompt")

    assert [scene.tokens for scene in length.scenes] == [3]
    assert (length.reads_well, length.past_it) == (511, READ_WHOLE)


def test_krea_2_reads_weight_marks_as_part_of_the_prompt(comfyui):
    _byte_reader(comfyui)

    length = prompt_length("krea2_t2i", {"positive_prompt": "(ab:1.2)"}, "positive_prompt")

    assert [scene.tokens for scene in length.scenes] == [8]
    assert (length.reads_well, length.past_it) == (507, READ_WHOLE)


def test_a_wan_story_is_counted_scene_by_scene_from_its_own_text_reader_file(comfyui):
    _umt5_reader(comfyui)
    params = {"positive_prompt": "cat cat dog\n---\ncat", "clip_name": _UMT5_FILE}

    length = prompt_length("wan22_i2v", params, "positive_prompt")

    assert [scene.tokens for scene in length.scenes] == [3, 1]
    assert (length.reads_well, length.past_it) == (511, READ_WHOLE)


def test_a_sound_prompt_is_cut_off_after_76_tokens(comfyui, tmp_path):
    clap_reader(tmp_path / "hub")

    length = prompt_length("wan22_i2v", {"audio_prompt": "rain on a tin roof"}, "audio_prompt")

    assert [scene.tokens for scene in length.scenes] == [5]
    assert (length.reads_well, length.past_it) == (76, CUT_OFF)


def test_a_sound_prompt_past_its_cut_off_says_where_its_reader_stops(comfyui, tmp_path):
    clap_reader(tmp_path / "hub")
    read = " ".join(["rain"] * 76)
    params = {"audio_prompt": f"{read} on a tin roof", "audio_negative_prompt": "hiss",
              "positive_prompt": " ".join(["cat"] * 600)}

    assert where_reading_stops("wan22_i2v", params) == {"audio_prompt": len(read) + 1,
                                                        "audio_negative_prompt": None}


def test_a_prompt_whose_text_reader_is_not_installed_is_of_unknown_length(comfyui):
    assert prompt_length("sdxl_t2i", {"positive_prompt": "cat"}, "positive_prompt") is None


def test_a_field_no_text_reader_reads_has_no_length(comfyui):
    _clip_reader(comfyui)

    assert prompt_length("sdxl_t2i", {"seed": "7"}, "seed") is None


def test_a_text_reader_is_read_from_its_files_once(comfyui):
    folder = _clip_reader(comfyui)
    prompt_length("sdxl_t2i", {"positive_prompt": "cat"}, "positive_prompt")
    shutil.rmtree(folder)

    length = prompt_length("sdxl_t2i", {"positive_prompt": "cat dog"}, "positive_prompt")

    assert [scene.tokens for scene in length.scenes] == [4]


@pytest.mark.parametrize("name", sorted(WORKFLOW_REGISTRY))
def test_every_prompt_comfyui_reads_names_its_text_reader(name):
    workflow = WORKFLOW_REGISTRY[name]
    prompts = {key for key in workflow.default_params() if key.endswith("prompt")}

    assert not workflow.generates_here or prompts - set(SOUND_PROMPT_KEYS) <= {
        "positive_prompt", "negative_prompt"}
    assert not workflow.generates_here or workflow.text_reader is not None


@pytest.mark.parametrize("name", sorted(WORKFLOW_REGISTRY))
def test_a_workflow_with_scenes_reads_its_prompts_scene_by_scene(name):
    workflow = WORKFLOW_REGISTRY[name]
    tells_scenes = any(pd.type == ParamType.SCENES for pd in workflow.param_definitions())

    assert bool(workflow.scene_prompt_keys) == tells_scenes
