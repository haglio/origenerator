from __future__ import annotations

from datetime import datetime

from origenerator.model_titles import (
    Version,
    model_title,
    trained_sentence,
    trained_when,
    versioned,
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
        installed_models.add("loras", f"fixes/{name}.safetensors", body=b"")

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

    assert trained_when(finished) == datetime.fromtimestamp(1792851468.891)
    assert trained_when(started) == datetime.fromtimestamp(1792851228.2)
    assert trained_when(undated) is None
    assert trained_when(installed_models.root / "missing.safetensors") is None


def test_a_versioned_loras_training_date_reads_as_a_sentence_of_its_own(
        installed_models, titled_models):
    titled_models({"example_look": "Example Look 1.0", "example_style": "Example Style"})
    for name in ("example_look", "example_style"):
        installed_models.add("loras", f"{name}.safetensors", arch="krea2", lora=True,
                             metadata={"ss_training_finished_at": "1792851468.891"})

    assert trained_sentence("example_look.safetensors") == (
        f"Trained {datetime.fromtimestamp(1792851468.891):%Y-%m-%d %H:%M}.")
    assert trained_sentence("example_style.safetensors") == ""
    assert trained_sentence(r"fixes\hands 1.1.safetensors") == ""
