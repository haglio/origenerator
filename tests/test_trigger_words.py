from __future__ import annotations

from origenerator.trigger_words import lacks_trigger_word, trigger_words, with_trigger_word


def test_a_lora_answers_to_the_words_written_down_for_it(worded_loras):
    worded_loras({"example_style": [" exmplstyle ", ""]})

    assert trigger_words(r"styles\example_style.safetensors") == ("exmplstyle",)


def test_a_lora_with_nothing_written_down_answers_to_no_words(worded_loras):
    worded_loras({})

    assert trigger_words("example_style.safetensors") == ()


def test_a_word_is_in_the_prompt_whatever_its_case_and_whatever_weights_it():
    assert not lacks_trigger_word("a portrait, (Exmplstyle:1.2), soft light", ["exmplstyle"])


def test_a_word_inside_a_longer_word_is_still_missing():
    assert lacks_trigger_word("an exmplstyled portrait", ["exmplstyle"])


def test_a_phrase_is_in_the_prompt_however_its_words_are_spaced():
    assert not lacks_trigger_word("a portrait in the  example\nstyle", ["example style"])


def test_any_one_of_a_loras_words_is_enough_and_none_of_them_is_missing():
    assert not lacks_trigger_word("a portrait, beta", ["gamma", "beta", "alpha"])
    assert lacks_trigger_word("a portrait, delta", ["gamma", "beta", "alpha"])


def test_a_word_missing_from_any_scene_of_a_story_is_missing():
    assert lacks_trigger_word("exmplstyle, scene one\n---\nscene two", ["exmplstyle"])
    assert not lacks_trigger_word("exmplstyle, scene one\n---\nexmplstyle, scene two",
                                  ["exmplstyle"])


def test_a_missing_word_goes_at_the_start_of_the_prompt():
    assert with_trigger_word("a portrait, soft light", ["exmplstyle"]) == (
        "exmplstyle, a portrait, soft light")


def test_a_word_added_to_an_empty_prompt_is_the_whole_prompt():
    assert with_trigger_word("", ["exmplstyle"]) == "exmplstyle"


def test_a_word_already_in_the_prompt_is_not_added_again():
    assert with_trigger_word("a portrait, (Exmplstyle:1.2)", ["exmplstyle"]) == (
        "a portrait, (Exmplstyle:1.2)")


def test_of_several_words_the_first_written_down_is_the_one_added():
    assert with_trigger_word("a portrait", ["gamma", "beta"]) == "gamma, a portrait"


def test_a_prompt_holding_any_one_of_the_words_has_none_added():
    assert with_trigger_word("a portrait, beta", ["gamma", "beta"]) == "a portrait, beta"


def test_a_word_goes_at_the_start_of_each_scene_of_a_story_missing_it():
    assert with_trigger_word("scene one\n---\nexmplstyle, scene two\n---\nscene three",
                             ["exmplstyle"]) == (
        "exmplstyle, scene one\n---\nexmplstyle, scene two\n---\nexmplstyle, scene three")
