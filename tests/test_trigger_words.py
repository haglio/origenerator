from __future__ import annotations

from origenerator.trigger_words import missing_words, trigger_words, with_words


def test_a_lora_answers_to_the_words_written_down_for_it(worded_loras):
    worded_loras({"example_style": [" exmplstyle ", ""]})

    assert trigger_words(r"styles\example_style.safetensors") == ("exmplstyle",)


def test_a_lora_with_nothing_written_down_answers_to_no_words(worded_loras):
    worded_loras({})

    assert trigger_words("example_style.safetensors") == ()


def test_a_word_is_in_the_prompt_whatever_its_case_and_whatever_weights_it():
    assert missing_words("a portrait, (Exmplstyle:1.2), soft light", ["exmplstyle"]) == []


def test_a_word_inside_a_longer_word_is_still_missing():
    assert missing_words("an exmplstyled portrait", ["exmplstyle"]) == ["exmplstyle"]


def test_a_phrase_is_in_the_prompt_however_its_words_are_spaced():
    assert missing_words("a portrait in the  example\nstyle", ["example style"]) == []


def test_the_missing_words_come_back_in_the_order_they_were_written_down():
    assert missing_words("a portrait, beta", ["gamma", "beta", "alpha"]) == ["gamma", "alpha"]


def test_a_word_missing_from_any_scene_of_a_story_is_missing():
    assert missing_words("exmplstyle, scene one\n---\nscene two", ["exmplstyle"]) == [
        "exmplstyle"]
    assert missing_words("exmplstyle, scene one\n---\nexmplstyle, scene two",
                         ["exmplstyle"]) == []


def test_a_missing_word_goes_at_the_start_of_the_prompt():
    assert with_words("a portrait, soft light", ["exmplstyle"]) == (
        "exmplstyle, a portrait, soft light")


def test_a_word_added_to_an_empty_prompt_is_the_whole_prompt():
    assert with_words("", ["exmplstyle"]) == "exmplstyle"


def test_a_word_already_in_the_prompt_is_not_added_again():
    assert with_words("a portrait, (Exmplstyle:1.2)", ["exmplstyle"]) == (
        "a portrait, (Exmplstyle:1.2)")


def test_a_word_goes_at_the_start_of_each_scene_of_a_story_missing_it():
    assert with_words("scene one\n---\nexmplstyle, scene two\n---\nscene three",
                      ["exmplstyle"]) == (
        "exmplstyle, scene one\n---\nexmplstyle, scene two\n---\nexmplstyle, scene three")
