from __future__ import annotations

from origenerator.lora_versions import newest_version, next_version
from origenerator.model_titles import Version


def test_the_next_version_of_a_lora_follows_its_newest_installed_one(installed_models, titled_models):
    titled_models({"example_look": "Example Look 1.0", "example_look_1_1": "Example Look 1.1",
                   "example_style": "Example Style"})
    for name in ("example_look", "looks/example_look_1_1", "example_style"):
        installed_models.add("loras", f"{name}.safetensors", arch="krea2", lora=True)

    assert newest_version("Example Look") == (Version(1, 1), r"looks\example_look_1_1.safetensors")
    assert next_version("Example Look") == Version(1, 2)
    assert newest_version("Nothing Yet") is None
    assert next_version("Nothing Yet") == Version(1, 0)


def test_a_fixs_next_version_follows_its_dated_files_and_its_versioned_ones_alike(
        installed_models, titled_models):
    installed_models.add("loras", "fixes/hands 2026-10-19 0130.safetensors", arch="sdxl", lora=True)
    assert next_version("Hands fix") == Version(1, 1)

    installed_models.add("loras", "fixes/hands 1.1.safetensors", arch="sdxl", lora=True)
    assert next_version("Hands fix") == Version(1, 2)


def test_versions_are_counted_within_one_model_family_keeping_a_lora_of_no_known_family(
        installed_models, titled_models):
    titled_models({"example_look": "Example Look 1.0", "example_look_sdxl": "Example Look 1.1",
                   "example_look_odd": "Example Look 1.2"})
    installed_models.add("loras", "example_look.safetensors", arch="krea2", lora=True)
    installed_models.add("loras", "example_look_sdxl.safetensors", arch="sdxl", lora=True)
    installed_models.add("loras", "example_look_odd.safetensors", lora=True)

    assert newest_version("Example Look", "krea2") == (Version(1, 2), "example_look_odd.safetensors")
    assert next_version("Example Look", "sdxl") == Version(1, 3)
    assert next_version("Example Look", "flux") == Version(1, 3)
