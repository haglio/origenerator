from __future__ import annotations

from datetime import datetime

import pytest

from origenerator.model_titles import (
    Version,
    model_title,
    precision_help,
    trained_sentence,
    trained_when,
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


def test_when_a_lora_was_trained_is_read_from_its_own_header(installed_models):
    finished = installed_models.add("loras", "finished.safetensors", lora=True, metadata={
        "ss_training_started_at": "1792851228.2", "ss_training_finished_at": "1792851468.891"})
    started = installed_models.add("loras", "started.safetensors", lora=True,
                                   metadata={"ss_training_started_at": "1792851228.2"})
    undated = installed_models.add("loras", "undated.safetensors", lora=True)

    assert trained_when(finished) == datetime.fromtimestamp(1792851468.891).astimezone()
    assert trained_when(started) == datetime.fromtimestamp(1792851228.2).astimezone()
    assert trained_when(undated) is None
    assert trained_when(installed_models.root / "missing.safetensors") is None


def test_a_versioned_loras_training_date_reads_as_a_sentence_of_its_own(
        installed_models, titled_models):
    titled_models({"example_look": "Example Look 1.0", "example_style": "Example Style"})
    for name in ("example_look", "example_style"):
        installed_models.add("loras", f"{name}.safetensors", arch="krea2", lora=True,
                             metadata={"ss_training_finished_at": "1792851468.891"})

    assert trained_sentence("example_look.safetensors") == (
        f"Trained {datetime.fromtimestamp(1792851468.891).astimezone():%Y-%m-%d %H:%M}.")
    assert trained_sentence("example_style.safetensors") == ""
    assert trained_sentence(r"fixes\hands 1.1.safetensors") == ""


def test_a_title_written_for_a_new_file_keeps_every_other_title(titled_models):
    titled_models({"example_model": "Example Model"})

    write_title("example_look_1_1", "Example Look 1.1")

    assert model_title("example_look_1_1.safetensors") == "Example Look 1.1"
    assert model_title("example_model.safetensors") == "Example Model"


@pytest.mark.parametrize(("tag", "words"), [
    ("fp16", "full size"), ("bf16", "full size"), ("fp8", "half size"), ("FP8", "half size"),
    ("int8", "half size, int8"), ("Q8", "half size, packed"),
])
def test_a_titles_precision_is_shown_in_plain_words(titled_models, tag, words):
    titled_models({"example_model": f"Example Model 2.0 (High, {tag})"})

    assert model_title("example_model.safetensors") == f"Example Model 2.0 (High, {words})"


def test_the_precision_shown_is_the_one_inside_the_file_whatever_its_title_says(
        installed_models, titled_models):
    installed_models.add("diffusion_models", "example_model.safetensors")
    titled_models({"example_model": "Example Model (fp8)"})

    assert model_title("example_model.safetensors") == "Example Model (full size)"


def test_a_word_that_only_contains_a_precision_tag_is_left_as_it_is(titled_models):
    titled_models({"example_model": "Example Modelfp8 (bf16x)"})

    assert model_title("example_model.safetensors") == "Example Modelfp8 (bf16x)"


def test_a_titles_precision_is_explained_by_what_its_tag_stands_for_and_what_it_means(titled_models):
    titled_models({"example_model": "Example Model (fp8)"})

    assert precision_help("example_model.safetensors").startswith(
        "fp8: floating point, 8 bits. Half the file of full size, and the fastest")


def test_an_installed_models_explanation_ends_with_its_file_size(installed_models, titled_models):
    installed_models.add_bytes("diffusion_models", "example_model.gguf", b"\x00" * (3 * 2**30 // 2**20))
    titled_models({"example_model": "Example Model (Q8)"})

    assert precision_help("example_model.gguf").endswith("This file is 0.0 GB.")


def test_a_title_naming_no_precision_has_nothing_to_explain(titled_models):
    titled_models({"example_model": "Example Model"})

    assert precision_help("example_model.safetensors") == ""
