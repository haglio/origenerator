from __future__ import annotations

from origenerator.base_models import loras_offered_beside, made_for_text_to_video


def test_a_file_civitai_files_under_a_text_to_video_base_model_is_made_for_text_to_video(
        recorded_base_models):
    recorded_base_models({"two_two": "Wan Video 2.2 T2V-A14B", "two_one": "Wan Video 14B t2v"})

    assert made_for_text_to_video(r"styles\two_two.safetensors")
    assert made_for_text_to_video("two_one.safetensors")


def test_an_image_to_video_base_model_or_none_written_down_is_not_text_to_video(
        recorded_base_models):
    recorded_base_models({"two_two": "Wan Video 2.2 I2V-A14B", "two_one": "Wan Video 14B i2v 720p",
                          "unknown": ""})

    assert not any(made_for_text_to_video(f"{stem}.safetensors")
                   for stem in ("two_two", "two_one", "unknown", "never_asked"))


def test_a_lora_is_offered_beside_a_model_unless_the_two_are_filed_under_two_base_models(
        recorded_base_models):
    recorded_base_models({"one": "Alpha 1", "other": "Beta 2", "made_for_one": "Alpha 1",
                          "made_for_other": "Beta 2", "unknown": ""})
    loras = ["None", "made_for_one.safetensors", "made_for_other.safetensors",
             "unknown.safetensors", "never_asked.safetensors"]

    assert loras_offered_beside("other.safetensors", loras) == [
        "None", "made_for_other.safetensors", "unknown.safetensors", "never_asked.safetensors"]
    assert loras_offered_beside("not_on_civitai.safetensors", loras) == loras


_KREA_2_RECORDS = {"raw": "Krea 2", "turbo": "Krea 2 Turbo", "made_for_krea_2": "Krea 2",
                   "made_for_turbo": "Krea 2 Turbo", "made_for_raw_alone": "Krea 2 Raw"}
_KREA_2_LORAS = ["None", "made_for_krea_2.safetensors", "made_for_turbo.safetensors",
                 "made_for_raw_alone.safetensors"]


def test_a_lora_made_for_krea_2_is_offered_beside_its_turbo_models_too(recorded_base_models):
    recorded_base_models(_KREA_2_RECORDS)

    assert "made_for_krea_2.safetensors" in loras_offered_beside("turbo.safetensors",
                                                                 _KREA_2_LORAS)


def test_a_lora_made_for_krea_2_raw_alone_leaves_the_turbo_models_rows(recorded_base_models):
    recorded_base_models(_KREA_2_RECORDS)

    assert loras_offered_beside("raw.safetensors", _KREA_2_LORAS) == _KREA_2_LORAS
    assert loras_offered_beside("turbo.safetensors", _KREA_2_LORAS) == [
        "None", "made_for_krea_2.safetensors", "made_for_turbo.safetensors"]
