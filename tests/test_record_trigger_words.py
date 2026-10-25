from __future__ import annotations

import hashlib
import io
import json
import struct

from origenerator import config
from tools import record_trigger_words


def _sha256(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _version(path, words) -> dict:
    return {"trainedWords": words, "files": [{"hashes": {"SHA256": _sha256(path).upper()}}]}


def _recorded() -> dict:
    return json.loads(config.TRIGGER_WORDS_PATH.read_text(encoding="utf-8"))


def test_a_lora_civitai_knows_is_recorded_with_the_words_it_was_trained_on(
        installed_models, worded_loras):
    worded_loras({})
    style = installed_models.add("loras", "example_style.safetensors", arch="sdxl", lora=True)
    asked = []

    def civitai(hashes):
        asked.append(hashes)
        return [_version(style, ["exmplstyle"])]

    record_trigger_words.main([], ask=civitai)

    assert asked == [[_sha256(style)]]
    assert _recorded() == {"example_style": ["exmplstyle"]}


def test_a_lora_whose_words_are_written_down_already_is_neither_asked_about_nor_changed(
        installed_models, worded_loras):
    worded_loras({"home_trained": ["hmtrnd"]})
    installed_models.add("loras", "home_trained.safetensors", arch="sdxl", lora=True)
    style = installed_models.add("loras", "example_style.safetensors", arch="flux", lora=True)
    asked = []

    def civitai(hashes):
        asked.append(hashes)
        return []

    record_trigger_words.main([], ask=civitai)

    assert asked == [[_sha256(style)]]
    assert _recorded()["home_trained"] == ["hmtrnd"]


def test_a_lora_civitai_does_not_know_is_written_down_with_no_words_and_not_asked_about_again(
        installed_models, worded_loras):
    worded_loras({})
    installed_models.add("loras", "unlisted_style.safetensors", arch="sdxl", lora=True)
    asked = []

    def civitai(hashes):
        asked.append(hashes)
        return []

    record_trigger_words.main([], ask=civitai)
    record_trigger_words.main([], ask=civitai)

    assert len(asked) == 1
    assert _recorded() == {"unlisted_style": []}


def test_a_fixs_own_lora_is_left_out(installed_models, worded_loras):
    worded_loras({})
    installed_models.add("loras", r"fixes\mouth 2026-10-19 1444.safetensors", arch="sdxl",
                         lora=True)
    asked = []

    def civitai(hashes):
        asked.append(hashes)
        return []

    record_trigger_words.main([], ask=civitai)

    assert asked == []
    assert _recorded() == {}


def test_two_copies_of_one_lora_under_different_names_are_both_written_down(
        installed_models, worded_loras):
    worded_loras({})
    style = installed_models.add("loras", "example_style.safetensors", arch="sdxl", lora=True)
    installed_models.add("loras", r"copies\example_style_copy.safetensors", arch="sdxl",
                         lora=True)
    asked = []

    def civitai(hashes):
        asked.append(hashes)
        return [_version(style, ["exmplstyle"])]

    record_trigger_words.main([], ask=civitai)

    assert asked == [[_sha256(style)]]
    assert _recorded() == {"example_style": ["exmplstyle"],
                           "example_style_copy": ["exmplstyle"]}


def _distinct_lora(installed_models, n: int):
    header = json.dumps({f"distinct{n}.lora_A.weight": {
        "dtype": "F16", "shape": [1], "data_offsets": [0, 2]}}).encode()
    return installed_models.add("loras", f"example_{n:03d}.safetensors",
                                body=struct.pack("<Q", len(header)) + header + b"\x00\x00")


def test_civitai_is_asked_about_at_most_a_hundred_loras_at_a_time(installed_models, worded_loras):
    worded_loras({})
    for n in range(101):
        _distinct_lora(installed_models, n)
    asked = []

    def civitai(hashes):
        asked.append(hashes)
        return []

    record_trigger_words.main([], ask=civitai)

    assert sorted(len(hashes) for hashes in asked) == [1, 100]
    assert len(_recorded()) == 101


def test_it_prints_counts_and_never_a_name_or_a_word(installed_models, worded_loras, capsys):
    worded_loras({})
    worded = installed_models.add("loras", "example_style.safetensors", arch="sdxl", lora=True)
    wordless = installed_models.add("loras", "example_light.safetensors", arch="flux", lora=True)
    installed_models.add("loras", "example_unlisted.safetensors", arch="sd15", lora=True)

    record_trigger_words.main([], ask=lambda hashes: [_version(worded, ["exmplstyle"]),
                                                      _version(wordless, [])])

    assert capsys.readouterr().out == (
        "Asked Civitai about 3 LoRAs: 1 with trigger words, 1 with none, 1 it does not know.\n")


def test_civitai_is_sent_the_hashes_as_a_json_list_and_its_answer_read_back(monkeypatch):
    sent = {}

    def urlopen(request, timeout):
        sent.update(url=request.full_url, method=request.get_method(),
                    hashes=json.loads(request.data), named=bool(request.get_header("User-agent")),
                    timeout=timeout)
        return io.BytesIO(json.dumps([{"trainedWords": ["exmplstyle"]}]).encode())

    monkeypatch.setattr(record_trigger_words.urllib.request, "urlopen", urlopen)

    assert record_trigger_words.ask_civitai(["ab" * 32]) == [{"trainedWords": ["exmplstyle"]}]
    assert sent == {"url": "https://civitai.com/api/v1/model-versions/by-hash",
                    "method": "POST", "hashes": ["ab" * 32], "named": True, "timeout": 60}
