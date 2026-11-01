from __future__ import annotations

import hashlib
import io
import json
import struct

import pytest

from origenerator import config
from tools import record_from_civitai


@pytest.fixture(autouse=True)
def _nothing_recorded_yet(worded_loras, recorded_base_models):
    worded_loras({})
    recorded_base_models({})


def _sha256(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _version(path, words, base="") -> dict:
    return {"trainedWords": words, "baseModel": base,
            "files": [{"hashes": {"SHA256": _sha256(path).upper()}}]}


def _recorded() -> dict:
    return json.loads(config.TRIGGER_WORDS_PATH.read_text(encoding="utf-8"))


def _bases() -> dict:
    return json.loads(config.BASE_MODELS_PATH.read_text(encoding="utf-8"))


def test_a_lora_civitai_knows_has_its_base_model_written_down_beside_its_words(installed_models):
    style = installed_models.add("loras", "example_style.safetensors", arch="sdxl", lora=True)

    record_from_civitai.main([], ask=lambda hashes: [_version(style, [], "Example Base 1.0")])

    assert _bases() == {"example_style": "Example Base 1.0"}


def test_a_lora_whose_words_are_written_down_but_not_its_base_model_is_asked_and_keeps_its_words(
        installed_models, worded_loras):
    worded_loras({"home_trained": ["hmtrnd"]})
    trained = installed_models.add("loras", "home_trained.safetensors", arch="sdxl", lora=True)
    asked = []

    def civitai(hashes):
        asked.append(hashes)
        return []

    record_from_civitai.main([], ask=civitai)

    assert asked == [[_sha256(trained)]]
    assert (_recorded(), _bases()) == ({"home_trained": ["hmtrnd"]}, {"home_trained": ""})


def test_a_lora_civitai_knows_is_recorded_with_the_words_it_was_trained_on(
        installed_models):
    style = installed_models.add("loras", "example_style.safetensors", arch="sdxl", lora=True)
    asked = []

    def civitai(hashes):
        asked.append(hashes)
        return [_version(style, ["exmplstyle"])]

    record_from_civitai.main([], ask=civitai)

    assert asked == [[_sha256(style)]]
    assert _recorded() == {"example_style": ["exmplstyle"]}


def test_a_lora_whose_words_and_base_model_are_written_down_is_neither_asked_about_nor_changed(
        installed_models, worded_loras, recorded_base_models):
    worded_loras({"home_trained": ["hmtrnd"]})
    recorded_base_models({"home_trained": ""})
    installed_models.add("loras", "home_trained.safetensors", arch="sdxl", lora=True)
    style = installed_models.add("loras", "example_style.safetensors", arch="flux", lora=True)
    asked = []

    def civitai(hashes):
        asked.append(hashes)
        return []

    record_from_civitai.main([], ask=civitai)

    assert asked == [[_sha256(style)]]
    assert _recorded()["home_trained"] == ["hmtrnd"]


def test_a_lora_civitai_does_not_know_is_written_down_with_no_words_and_not_asked_about_again(
        installed_models):
    installed_models.add("loras", "unlisted_style.safetensors", arch="sdxl", lora=True)
    asked = []

    def civitai(hashes):
        asked.append(hashes)
        return []

    record_from_civitai.main([], ask=civitai)
    record_from_civitai.main([], ask=civitai)

    assert len(asked) == 1
    assert (_recorded(), _bases()) == ({"unlisted_style": []}, {"unlisted_style": ""})


def test_a_fixs_own_lora_is_left_out(installed_models):
    installed_models.add("loras", r"fixes\mouth 2026-10-19 1444.safetensors", arch="sdxl",
                         lora=True)
    asked = []

    def civitai(hashes):
        asked.append(hashes)
        return []

    record_from_civitai.main([], ask=civitai)

    assert asked == []
    assert _recorded() == {}


def test_two_copies_of_one_lora_under_different_names_are_both_written_down(
        installed_models):
    style = installed_models.add("loras", "example_style.safetensors", arch="sdxl", lora=True)
    installed_models.add("loras", r"copies\example_style_copy.safetensors", arch="sdxl",
                         lora=True)
    asked = []

    def civitai(hashes):
        asked.append(hashes)
        return [_version(style, ["exmplstyle"])]

    record_from_civitai.main([], ask=civitai)

    assert asked == [[_sha256(style)]]
    assert _recorded() == {"example_style": ["exmplstyle"],
                           "example_style_copy": ["exmplstyle"]}


def test_a_lora_civitai_also_lists_beside_another_models_own_file_takes_its_own_versions_words(
        installed_models):
    style = installed_models.add("loras", "example_style.safetensors", arch="sdxl", lora=True)
    listed = {"hashes": {"SHA256": _sha256(style).upper()}}
    bundled_with = {"trainedWords": ["othrword"],
                    "files": [{"primary": True, "hashes": {"SHA256": "ab" * 32}},
                              dict(listed, primary=False)]}
    its_own = {"trainedWords": ["exmplstyle"], "files": [dict(listed, primary=True)]}

    record_from_civitai.main([], ask=lambda hashes: [bundled_with, its_own])

    assert _recorded() == {"example_style": ["exmplstyle"]}


def _distinct_lora(installed_models, n: int):
    header = json.dumps({f"distinct{n}.lora_A.weight": {
        "dtype": "F16", "shape": [1], "data_offsets": [0, 2]}}).encode()
    return installed_models.add("loras", f"example_{n:03d}.safetensors",
                                body=struct.pack("<Q", len(header)) + header + b"\x00\x00")


def test_civitai_is_asked_about_at_most_a_hundred_loras_at_a_time(installed_models):
    for n in range(101):
        _distinct_lora(installed_models, n)
    asked = []

    def civitai(hashes):
        asked.append(hashes)
        return []

    record_from_civitai.main([], ask=civitai)

    assert sorted(len(hashes) for hashes in asked) == [1, 100]
    assert len(_recorded()) == 101


def test_it_prints_counts_and_never_a_name_or_a_word(installed_models, capsys):
    worded = installed_models.add("loras", "example_style.safetensors", arch="sdxl", lora=True)
    wordless = installed_models.add("loras", "example_light.safetensors", arch="flux", lora=True)
    installed_models.add("loras", "example_unlisted.safetensors", arch="sd15", lora=True)
    known = installed_models.add("checkpoints", "example_model.safetensors", arch="sdxl")
    installed_models.add("diffusion_models", "example_unlisted_model.safetensors", arch="krea2")

    record_from_civitai.main([], ask=lambda hashes: [_version(worded, ["exmplstyle"]),
                                                      _version(wordless, []),
                                                      _version(known, [], "Example Base")])

    assert capsys.readouterr().out == (
        "Asked Civitai about 3 LoRAs (1 with trigger words, 1 with none, 1 it does not know) "
        "and 2 models (1 it knows).\n")


def test_a_model_has_its_base_model_written_down_and_no_trigger_words(installed_models):
    for category in ("checkpoints", "diffusion_models"):
        model = installed_models.add(category, f"{category}_model.safetensors", arch="krea2")

        record_from_civitai.main([], ask=lambda hashes, model=model: [
            _version(model, ["exmplword"], "Example Base 1.0")])

    assert _bases() == {"checkpoints_model": "Example Base 1.0",
                        "diffusion_models_model": "Example Base 1.0"}
    assert _recorded() == {}


def test_a_model_whose_base_model_is_written_down_is_not_asked_about(
        installed_models, recorded_base_models):
    recorded_base_models({"example_model": "Example Base 1.0"})
    installed_models.add("diffusion_models", "example_model.safetensors", arch="krea2")
    asked = []

    record_from_civitai.main([], ask=lambda hashes: asked.append(hashes) or [])

    assert asked == []


def test_civitai_is_sent_the_hashes_as_a_json_list_and_its_answer_read_back(monkeypatch):
    sent = {}

    def urlopen(request, timeout):
        sent.update(url=request.full_url, method=request.get_method(),
                    hashes=json.loads(request.data), named=bool(request.get_header("User-agent")),
                    timeout=timeout)
        return io.BytesIO(json.dumps([{"trainedWords": ["exmplstyle"]}]).encode())

    monkeypatch.setattr(record_from_civitai.urllib.request, "urlopen", urlopen)

    assert record_from_civitai.ask_civitai(["ab" * 32]) == [{"trainedWords": ["exmplstyle"]}]
    assert sent == {"url": "https://civitai.com/api/v1/model-versions/by-hash",
                    "method": "POST", "hashes": ["ab" * 32], "named": True, "timeout": 60}
