from __future__ import annotations

from origenerator.model_titles import (
    Version,
    model_title,
    versioned,
    write_title,
)


def test_a_model_file_is_shown_by_its_title(titled_models):
    titled_models({"example_model": "Example Model v2"})

    assert model_title("example_model.safetensors") == "Example Model v2"


def test_a_model_file_with_no_title_is_shown_by_its_name_without_its_extension(titled_models):
    titled_models({"example_model": "Example Model v2"})

    assert model_title(r"loras\example_style.safetensors") == "example_style"


def test_with_no_titles_written_at_all_each_file_is_shown_by_its_name(titled_models):
    assert model_title("example_model.gguf") == "example_model"


def test_a_fixs_lora_named_by_date_is_shown_as_that_fix_and_its_rank_among_its_dated_files(
        installed_models, titled_models):
    assert model_title(r"fixes\mouth 2026-10-19 1444.safetensors") == "Mouth fix 1.0"

    for name in ("hands 2026-10-19 0130", "hands 2026-10-21 1500", "mouth 2026-10-19 1444"):
        installed_models.add_bytes("loras", f"fixes/{name}.safetensors", b"")

    assert model_title(r"fixes\hands 2026-10-19 0130.safetensors") == "Hands fix 1.0"
    assert model_title(r"fixes\hands 2026-10-21 1500.safetensors") == "Hands fix 1.1"
    assert model_title(r"fixes\mouth 2026-10-19 1444.safetensors") == "Mouth fix 1.0"


def test_a_title_written_while_the_app_runs_is_shown_from_then_on(titled_models):
    titled_models({})
    assert model_title("example_model.gguf") == "example_model"

    titled_models({"example_model": "Example Model"})

    assert model_title("example_model.gguf") == "Example Model"


def test_a_title_ending_in_a_version_number_names_its_base_and_version():
    assert versioned("Example Look 1.0") == ("Example Look", Version(1, 0))
    assert versioned("Example Model v2") is None


def test_a_fixs_lora_named_by_its_version_is_shown_as_that_fix_and_version(titled_models):
    assert model_title(r"fixes\hands 1.1.safetensors") == "Hands fix 1.1"


def test_a_title_written_for_a_new_file_keeps_every_other_title(titled_models):
    titled_models({"example_model": "Example Model"})

    write_title("example_look_1_1", "Example Look 1.1")

    assert model_title("example_look_1_1.safetensors") == "Example Look 1.1"
    assert model_title("example_model.safetensors") == "Example Model"
