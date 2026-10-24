from __future__ import annotations

from origenerator.model_titles import model_title


def test_a_model_file_is_shown_by_its_title(titled_models):
    titled_models({"example_model": "Example Model v2"})

    assert model_title("example_model.safetensors") == "Example Model v2"


def test_a_model_file_with_no_title_is_shown_by_its_name_without_its_extension(titled_models):
    titled_models({"example_model": "Example Model v2"})

    assert model_title(r"loras\example_style.safetensors") == "example_style"


def test_with_no_titles_written_at_all_each_file_is_shown_by_its_name(titled_models):
    assert model_title("example_model.gguf") == "example_model"


def test_a_fixs_lora_is_shown_as_that_fix_and_when_it_was_trained(titled_models):
    assert model_title(r"fixes\mouth 2026-10-19 1444.safetensors") == (
        "Mouth fix (2026-10-19 14:44)")


def test_a_title_written_while_the_app_runs_is_shown_from_then_on(titled_models):
    titled_models({})
    assert model_title("example_model.gguf") == "example_model"

    titled_models({"example_model": "Example Model"})

    assert model_title("example_model.gguf") == "Example Model"
