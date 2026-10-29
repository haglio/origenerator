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


def test_a_lora_is_offered_beside_a_model_unless_civitai_files_the_two_under_two_base_models(
        recorded_base_models):
    recorded_base_models({"raw": "Krea 2", "turbo": "Krea 2 Turbo", "made_for_raw": "Krea 2",
                          "made_for_turbo": "Krea 2 Turbo", "unknown": ""})
    loras = ["None", "made_for_raw.safetensors", "made_for_turbo.safetensors",
             "unknown.safetensors", "never_asked.safetensors"]

    assert loras_offered_beside("turbo.safetensors", loras) == [
        "None", "made_for_turbo.safetensors", "unknown.safetensors", "never_asked.safetensors"]
    assert loras_offered_beside("not_on_civitai.safetensors", loras) == loras
