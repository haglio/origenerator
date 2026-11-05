from __future__ import annotations

import pytest

from origenerator import request_settings
from origenerator.request_changes import Prompts, apply_changes
from origenerator.trigger_words import with_trigger_words_swapped
from origenerator.workflows.base import ParamDef, ParamType, story_of

_SIZE = request_settings.settings_to_tell(
    [ParamDef("width", "Width", ParamType.INT, 1280, min_val=512, max_val=2048, step=16),
     ParamDef("height", "Height", ParamType.INT, 720, min_val=512, max_val=2048, step=16)],
    {"width": 1280, "height": 720})


_NO_HAT = 'Couldn\'t find "hat" in the Positive Prompt. Added "hat" to the Negative Prompt.'


def _applied(changes, pair=("a woman on a couch", "blurry"), *, asked=("portrait",),
             settings=_SIZE):
    return apply_changes({"changes": changes}, pair, asked=list(asked), settings=settings)


def test_a_setting_change_is_taken_in_its_own_kind_and_said_with_what_it_was():
    outcome = _applied([{"setting": "width", "to": "720", "for": "portrait"},
                        {"setting": "Height", "to": 1280, "for": "portrait"}])

    assert outcome.settings == {"width": 720, "height": 1280}
    assert (outcome.positive, outcome.negative) == ("a woman on a couch", "blurry")
    assert outcome.line == "Set Width to 720 (was 1280). Set Height to 1280 (was 720)."


def test_a_setting_or_value_the_app_cannot_read_is_said_so_instead_of_vanishing():
    outcome = _applied([{"setting": "steps", "to": 30, "for": "portrait"},
                        {"setting": "width", "to": "wider", "for": "portrait"},
                        {"setting": "width", "to": 1280, "for": "portrait"}])

    assert outcome.settings == {}
    assert outcome.line == 'There is no setting called "steps". Width can\'t be "wider".'


def test_a_change_that_answers_nothing_he_asked_for_is_left_out_without_a_word():
    outcome = _applied([{"setting": "width", "to": 720},
                        {"setting": "height", "to": 1280, "for": "natural lighting"},
                        {"setting": "height", "to": 1280, "for": "Make it portrait"}],
                       asked=("make it portrait, please", "no you didn't"))

    assert outcome.settings == {"height": 1280}
    assert outcome.line == "Set Height to 1280 (was 720)."


def test_words_of_a_prompt_are_replaced_where_they_stand_whatever_their_case():
    outcome = _applied([{"prompt": "positive", "replace": "A Woman", "with": "two women",
                         "for": "two women"},
                        {"prompt": "negative", "replace": "blurry", "with": "(blurry:1.2)",
                         "for": "less blurry"},
                        {"prompt": "positive", "replace": "a cat", "with": "a dog", "for": "dog"}],
                       asked=("two women, less blurry, and a dog",))

    assert (outcome.positive, outcome.negative) == ("two women on a couch", "(blurry:1.2)")
    assert outcome.line == (
        'Replaced "A Woman" with "two women" in the Positive Prompt. Replaced "blurry" with '
        '"(blurry:1.2)" in the Negative Prompt. Couldn\'t find "a cat" in the Positive Prompt.')


def test_words_are_added_after_the_part_they_belong_with_or_at_the_end_and_never_twice():
    outcome = _applied([{"prompt": "positive", "add": "freckles", "after": "a woman", "for": "freckles"},
                        {"prompt": "positive", "add": "soft light", "after": "a beach", "for": "light"},
                        {"prompt": "negative", "add": "Blurry", "for": "blurry"},
                        {"prompt": "negative", "add": "hat", "for": "no hat"}],
                       pair=("a woman on a couch, (smiling:1.2)", "blurry"),
                       asked=("freckles, soft light, less blurry, no hat",))

    assert (outcome.positive, outcome.negative) == (
        "a woman on a couch, freckles, (smiling:1.2), soft light", "(blurry:1.1), hat")
    assert outcome.line == (
        'Added "freckles" to the Positive Prompt. Added "soft light" to the Positive Prompt. '
        'Couldn\'t find "Blurry" in the Positive Prompt. '
        'Replaced "blurry" with "(blurry:1.1)" in the Negative Prompt. '
        'Couldn\'t find "hat" in the Positive Prompt. Added "hat" to the Negative Prompt.')


def test_words_are_taken_out_of_a_prompt_and_the_commas_close_over_them():
    outcome = _applied([{"prompt": "positive", "remove": "on a couch", "for": "no couch"},
                        {"prompt": "negative", "remove": "blurry", "for": "blurry is fine"},
                        {"prompt": "negative", "remove": "grain", "for": "grain"}],
                       asked=("no couch, blurry is fine, grain",))

    assert (outcome.positive, outcome.negative) == ("a woman", "")
    assert outcome.line == (
        'Removed "on a couch" from the Positive Prompt. Removed "blurry" from the Negative Prompt. '
        'Nothing in the Negative Prompt works against "grain".')


def test_a_prompt_change_answering_nothing_he_asked_for_is_left_out_too():
    outcome = _applied([{"prompt": "positive", "replace": "a woman", "with": "a grumpy woman"},
                        {"prompt": "negative", "add": "doll", "for": "natural lighting"},
                        {"prompt": "positive", "remove": "on a couch", "for": "natural lighting"}],
                       asked=("use the newer LoRA",))

    assert (outcome.positive, outcome.negative) == ("a woman on a couch", "blurry")
    assert outcome.line == "Nothing changed."


def test_no_change_at_all_says_so_and_nothing_else_the_model_wrote_reaches_him():
    assert _applied([]).line == "Nothing changed."
    assert apply_changes({"changes": [], "note": "The hat was never there, so"}, ("a woman", ""),
                         asked=["no hat"], settings=_SIZE).line == "Nothing changed."


def test_a_replacement_that_changes_nothing_says_nothing():
    same = {"prompt": "positive", "replace": "a woman on a couch", "with": "A woman on a couch",
            "for": "no hat"}

    assert _applied([same], asked=("no hat",)).line == "Nothing changed."
    assert _applied([same, {"prompt": "negative", "add": "hat", "for": "no hat"}],
                    asked=("no hat",)).line == _NO_HAT


@pytest.mark.parametrize("words", ["no hat", "without a hat", "(no hat:1.2)", "No hats"])
def test_words_for_the_positive_prompt_that_say_what_to_leave_out_go_to_the_negative_prompt(words):
    outcome = _applied([{"prompt": "positive", "add": words, "for": "no hat"}],
                       asked=("no hat please",))

    assert outcome.positive == "a woman on a couch"
    assert outcome.negative in ("blurry, hat", "blurry, hats")
    assert outcome.line.startswith('Couldn\'t find "hat')
    assert outcome.line.endswith(' to the Negative Prompt.')


def test_a_replacement_that_tacks_on_what_to_leave_out_sends_it_to_the_negative_prompt():
    outcome = _applied([{"prompt": "positive", "replace": "a woman on a couch",
                         "with": "a woman on a couch, no hat", "for": "no hat"}],
                       asked=("no hat please",))

    assert (outcome.positive, outcome.negative) == ("a woman on a couch", "blurry, hat")
    assert outcome.line == _NO_HAT


def test_a_replacement_keeps_what_it_changed_beside_what_it_sends_to_the_negative_prompt():
    outcome = _applied([{"prompt": "positive", "replace": "a woman on a couch",
                         "with": "two women on a couch, no hat", "for": "two women, no hat"}],
                       asked=("two women, no hat",))

    assert (outcome.positive, outcome.negative) == ("two women on a couch", "blurry, hat")
    assert outcome.line == ('Replaced "a woman on a couch" with "two women on a couch" in the '
                            f"Positive Prompt. {_NO_HAT}")


def test_a_part_already_saying_no_in_the_positive_prompt_stays_where_he_wrote_it():
    outcome = _applied([{"prompt": "positive", "replace": "a woman, no shoes",
                         "with": "two women, no shoes", "for": "two women"}],
                       pair=("a woman, no shoes", "blurry"), asked=("two women",))

    assert (outcome.positive, outcome.negative) == ("two women, no shoes", "blurry")


def test_something_unwanted_the_negative_prompt_already_has_is_made_to_weigh_more_each_time():
    again = [{"prompt": "negative", "add": "hats", "for": "they still have hats"}]
    once = _applied(again, pair=("two women", "blurry, straw hats"), asked=("they still have hats",))
    twice = _applied(again, pair=(once.positive, once.negative), asked=("they still have hats",))

    assert once.negative == "blurry, (straw hats:1.1)"
    assert once.line == ('Couldn\'t find "hats" in the Positive Prompt. '
                         'Replaced "straw hats" with "(straw hats:1.1)" in the Negative Prompt.')
    assert twice.negative == "blurry, (straw hats:1.2)"
    assert twice.line.endswith('Replaced "(straw hats:1.1)" with "(straw hats:1.2)" in the Negative '
                               'Prompt.')


def test_something_wanted_the_positive_prompt_already_has_is_said_to_be_there():
    outcome = _applied([{"prompt": "positive", "add": "a woman", "for": "a woman"}],
                       asked=("a woman",))

    assert outcome.positive == "a woman on a couch"
    assert outcome.line == 'The Positive Prompt already has "a woman".'


def test_a_change_the_app_cannot_read_is_said_so():
    outcome = _applied([{"prompt": "positive", "for": "portrait"}, "portrait", {"mood": "sad"}])

    assert outcome.line == "Couldn't read one of the model's changes."


_LORA_ROW = ParamDef("lora", "LoRA 1", ParamType.DROPDOWN, "None",
                     options=["None", "example_style.safetensors", "example_style_11.safetensors"],
                     folder="loras")


@pytest.fixture
def versioned_style(titled_models, worded_loras):
    titled_models({"example_style": "Example Style 1.0", "example_style_11": "Example Style 1.1"})
    worded_loras({"example_style": ["exmplstyle"], "example_style_11": ["exmplnew"]})


def _lora_switched(picked: str, to: str, positive: str, **how):
    settings = request_settings.settings_to_tell([_LORA_ROW], {"lora": picked})
    return apply_changes({"changes": [{"setting": "lora", "to": to, "for": "newer version"}]},
                         (positive, "blurry"), asked=["use the newer version"], settings=settings,
                         **how)


def test_switching_a_lora_swaps_its_trigger_word_where_it_stands_as_the_warnings_click_does(
        versioned_style):
    prompt = "a woman, (exmplstyle:1.1), soft light, exmplstyle"
    outcome = _lora_switched("example_style.safetensors", "Example Style 1.1", prompt)

    assert outcome.settings == {"lora": "example_style_11.safetensors"}
    assert outcome.positive == "a woman, (exmplnew:1.1), soft light, exmplnew"
    assert outcome.positive == with_trigger_words_swapped(prompt, ("exmplstyle",), ("exmplnew",))
    assert outcome.line == ("Set LoRA 1 to Example Style 1.1 (was Example Style 1.0), and swapped "
                            "its trigger word exmplstyle for exmplnew in the Positive Prompt.")


def test_picking_a_lora_puts_its_trigger_word_in_and_dropping_one_takes_its_word_out(
        versioned_style):
    picked = _lora_switched("None", "Example Style 1.0", "a woman")
    dropped = _lora_switched("example_style_11.safetensors", "None", "exmplnew, a woman")

    assert picked.positive == "exmplstyle, a woman"
    assert picked.line == ("Set LoRA 1 to Example Style 1.0 (was None), and put its trigger word "
                           "exmplstyle in the Positive Prompt.")
    assert dropped.positive == "a woman"
    assert dropped.line == ("Set LoRA 1 to None (was Example Style 1.1), and took its trigger "
                            "word exmplnew out of the Positive Prompt.")


def test_a_trigger_word_already_where_it_belongs_is_left_as_it_is_and_unmentioned(versioned_style):
    outcome = _lora_switched("example_style.safetensors", "Example Style 1.1", "exmplnew, a woman")

    assert outcome.positive == "exmplnew, a woman"
    assert outcome.line == "Set LoRA 1 to Example Style 1.1 (was Example Style 1.0)."


def test_a_storys_scenes_each_get_the_trigger_word_swapped(versioned_style):
    outcome = _lora_switched("example_style.safetensors", "Example Style 1.1",
                             story_of(["exmplstyle, a dog", "a cat"]), prompts=Prompts(in_scenes=True))

    assert outcome.positive == story_of(["exmplnew, a dog", "exmplnew, a cat"])


def test_an_edit_riding_inside_a_replacement_he_asked_for_is_left_out_without_a_word():
    outcome = _applied(
        [{"prompt": "positive", "replace": "exmplstyle, two women on a couch, soft light",
          "with": "(exmplstyle:1.2), one woman on a couch, soft light, natural lighting",
          "for": "have only one woman"}],
        pair=("exmplstyle, two women on a couch, soft light", "blurry"),
        asked=("please make it portrait and have only one woman",))

    assert outcome.positive == "exmplstyle, one woman on a couch, soft light"
    assert outcome.line == 'Replaced "two women" with "one woman" in the Positive Prompt.'


def test_a_replacement_in_words_that_are_not_his_at_all_is_the_models_to_make_whole():
    outcome = _applied([{"prompt": "positive", "replace": "silver ear studs, a necklace",
                         "with": "bare ears, a bare neck", "for": "no jewelry"}],
                       pair=("a woman, silver ear studs, a necklace", "blurry"),
                       asked=("no jewelry",))

    assert outcome.positive == "a woman, bare ears, a bare neck"
    assert outcome.line == ('Replaced "silver ear studs, a necklace" with "bare ears, a bare neck" '
                            "in the Positive Prompt.")


def test_several_parts_he_never_named_are_not_taken_out_together():
    whole = "a woman on a couch, soft light, a window"
    outcome = _applied([{"prompt": "positive", "remove": whole, "for": "no hat"},
                        {"prompt": "positive", "replace": whole, "with": "", "for": "no hat"},
                        {"prompt": "positive", "replace": whole, "with": "a woman on a sofa",
                         "for": "no hat"}],
                       pair=(whole, "blurry"), asked=("no hat please",))

    assert outcome.positive == "a woman on a sofa, soft light, a window"
    assert outcome.line == 'Replaced "couch" with "sofa" in the Positive Prompt.'


def test_of_several_parts_taken_out_together_only_the_ones_he_named_go():
    outcome = _applied([{"prompt": "positive", "remove": "a straw hat, soft light", "for": "no hat"}],
                       pair=("a woman, a straw hat, soft light", "blurry"), asked=("no hat please",))

    assert outcome.positive == "a woman, soft light"
    assert outcome.line == 'Removed "a straw hat" from the Positive Prompt.'


def test_words_to_add_that_carry_what_to_leave_out_send_only_that_part_to_the_negative_prompt():
    outcome = _applied([{"prompt": "positive", "add": "freckles, no hat", "after": "a woman",
                         "for": "freckles and no hat"}], asked=("freckles and no hat",))

    assert (outcome.positive, outcome.negative) == ("a woman on a couch, freckles", "blurry, hat")
    assert outcome.line == f'{_NO_HAT} Added "freckles" to the Positive Prompt.'


def test_a_part_the_replacement_drops_without_his_asking_stays_without_a_word():
    outcome = _applied([{"prompt": "positive", "replace": "a woman, a hat, soft light",
                         "with": "two women, soft light", "for": "two women"}],
                       pair=("a woman, a hat, soft light", "blurry"), asked=("two women",))

    assert outcome.positive == "two women, a hat, soft light"
    assert outcome.line == 'Replaced "a woman" with "two women" in the Positive Prompt.'


def test_each_part_of_a_replacement_he_asked_for_is_said_as_what_it_was():
    outcome = _applied([{"prompt": "positive", "replace": "a red hat, a dog, grass",
                         "with": "a blue hat, grass, a cat", "for": "a blue hat"}],
                       pair=("a red hat, a dog, grass", "blurry"),
                       asked=("a blue hat, no dog, add a cat",))

    assert outcome.positive == "a blue hat, grass, a cat"
    assert outcome.line == (
        'Replaced "red" with "blue" in the Positive Prompt. Removed "a dog" from the Positive '
        'Prompt. Added "a cat" to the Positive Prompt.')


def test_a_switch_away_from_a_lora_the_row_no_longer_offers_still_swaps_its_word(versioned_style):
    row = ParamDef("lora", "LoRA 1", ParamType.DROPDOWN, "None",
                   options=["None", "example_style_11.safetensors"], folder="loras")
    settings = request_settings.settings_to_tell([row], {"lora": "example_style.safetensors"})

    outcome = apply_changes(
        {"changes": [{"setting": "lora", "to": "Example Style 1.1", "for": "newer version"}]},
        ("(exmplstyle:1.2), a woman", "blurry"), asked=["use the newer version"],
        settings=settings)

    assert outcome.settings == {"lora": "example_style_11.safetensors"}
    assert outcome.positive == "(exmplnew:1.2), a woman"
    assert outcome.line == ("Set LoRA 1 to Example Style 1.1 (was Example Style 1.0), and swapped "
                            "its trigger word exmplstyle for exmplnew in the Positive Prompt.")


def test_a_long_prompt_rewritten_whole_is_answered_with_what_changed_and_nothing_else():
    kept = [f"detail {number}" for number in range(1, 41)]
    prompt = ", ".join(["one woman on a couch", *kept])
    outcome = _applied([{"prompt": "positive", "replace": prompt,
                         "with": "two women on a couch, waving", "for": "two women"}],
                       pair=(prompt, "blurry"), asked=("two women, waving at each other",))

    assert outcome.positive == ", ".join(["two women on a couch", "waving", *kept])
    assert outcome.line == ('Replaced "one woman" with "two women" in the Positive Prompt. Added '
                            '"waving" to the Positive Prompt.')


def test_one_part_replaced_by_words_quite_unlike_it_is_still_one_replacement():
    outcome = _applied([{"prompt": "positive", "replace": "a street, sunny afternoon, cars",
                         "with": "a street, at night, cars", "for": "at night"}],
                       pair=("a street, sunny afternoon, cars", "blurry"), asked=("at night",))

    assert outcome.positive == "a street, at night, cars"
    assert outcome.line == ('Replaced "a street, sunny afternoon, cars" with "a street, at night, cars" '
                            "in the Positive Prompt.")


@pytest.mark.parametrize("reason", [
    "she shouldn't have a hat", "she should not have a hat", "no hat", "remove the hat", "hat"])
def test_a_reason_that_rewords_what_he_asked_still_answers_him(reason):
    outcome = _applied([{"prompt": "negative", "add": "hat", "for": reason}],
                       asked=("her scarf should be plainer, and she shouldn't have a hat",))

    assert outcome.negative == "blurry, hat"
    assert outcome.line == _NO_HAT


def test_a_reworded_reason_for_something_already_kept_out_makes_it_weigh_more():
    outcome = _applied([{"prompt": "negative", "add": "hat", "for": "she should not have a hat"}],
                       pair=("a woman", "blurry, hat"), asked=("she shouldn't have a hat",))

    assert outcome.line == ('Couldn\'t find "hat" in the Positive Prompt. '
                            'Replaced "hat" with "(hat:1.1)" in the Negative Prompt.')


@pytest.mark.parametrize("reason", ["natural lighting", "", "please", "it should be"])
def test_a_reason_sharing_no_word_that_names_anything_with_what_he_asked_answers_nothing(reason):
    outcome = _applied([{"prompt": "positive", "add": "natural lighting", "for": reason}],
                       asked=("please, it should be her scarf that is plainer",))

    assert outcome.positive == "a woman on a couch"
    assert outcome.line == "Nothing changed."


def test_what_is_already_so_is_said_only_when_it_is_the_whole_answer():
    freckles = {"prompt": "positive", "add": "freckles", "for": "freckles"}
    square = [{"setting": "width", "to": 1280, "for": "square"},
              {"setting": "height", "to": 1280, "for": "square"}]

    assert _applied([freckles, freckles], asked=("freckles",)).line == (
        'Added "freckles" to the Positive Prompt.')
    assert _applied(square, asked=("square",)).line == "Set Height to 1280 (was 720)."
    assert _applied(square[:1], asked=("square",)).line == "Width is already 1280."


def test_leaving_out_something_the_positive_prompt_never_named_says_it_was_not_found_there():
    outcome = _applied([{"prompt": "positive", "remove": "a tall feathered hat", "for": "no hat"},
                        {"prompt": "positive", "replace": "a feathered hat", "with": "", "for": "no hat"},
                        {"prompt": "negative", "add": "hat", "for": "no hat"}], asked=("no hat",))

    assert outcome.line == _NO_HAT


def test_leaving_out_something_the_positive_prompt_names_says_only_what_changed():
    pair = ("a woman, a straw hat", "blurry")
    kept_out = {"prompt": "negative", "add": "hats", "for": "no hats"}
    taken_out = {"prompt": "positive", "remove": "a straw hat", "for": "no hats"}

    assert _applied([kept_out], pair=pair, asked=("no hats",)).line == (
        'Added "hats" to the Negative Prompt.')
    assert _applied([taken_out, kept_out], pair=pair, asked=("no hats",)).line == (
        'Removed "a straw hat" from the Positive Prompt. Added "hats" to the Negative Prompt.')


def test_looking_in_the_negative_prompt_for_something_wanted_that_is_not_there_says_so_once():
    outcome = _applied([{"prompt": "positive", "add": "freckles", "for": "freckles"},
                        {"prompt": "negative", "remove": "freckles", "for": "freckles"},
                        {"prompt": "negative", "replace": "freckles", "with": "", "for": "freckles"}],
                       asked=("freckles",))

    assert outcome.line == ('Added "freckles" to the Positive Prompt. '
                            'Nothing in the Negative Prompt works against "freckles".')


def test_prompts_that_take_no_weights_get_none_from_a_request():
    outcome = apply_changes(
        {"changes": [{"prompt": "positive", "replace": "a woman", "with": "(a tall woman:1.3)",
                      "for": "taller"},
                     {"prompt": "positive", "add": "((freckles))", "for": "freckles"},
                     {"prompt": "negative", "add": "blurry", "for": "less blurry"}]},
        ("a woman on a couch", "blurry"), asked=["taller, freckles, less blurry"], settings=_SIZE,
        prompts=Prompts(take_weights=False))

    assert (outcome.positive, outcome.negative) == ("a tall woman on a couch, freckles", "blurry")
    assert outcome.line == ('Replaced "a woman" with "a tall woman" in the Positive Prompt. '
                            'Added "freckles" to the Positive Prompt.')


def test_where_prompts_take_no_weights_something_already_kept_out_is_said_to_be_there():
    outcome = apply_changes({"changes": [{"prompt": "negative", "add": "hat", "for": "no hat"}]},
                            ("a woman", "blurry, hat"), asked=["no hat"], settings=_SIZE,
                            prompts=Prompts(take_weights=False))

    assert outcome.negative == "blurry, hat"
    assert outcome.line == ("Couldn't find \"hat\" in the Positive Prompt. "
                            'The Negative Prompt already has "hat".')


def test_a_change_to_something_he_named_answers_him_whatever_reason_it_gives():
    outcome = _applied([{"prompt": "positive", "replace": "a couch", "with": "a velvet couch",
                         "for": "more of it"},
                        {"setting": "height", "to": 1280, "for": "that"}],
                       asked=("I can't see the couch. more of it please, and a height of 1280",))

    assert outcome.positive == "a woman on a velvet couch"
    assert outcome.settings == {"height": 1280}


def test_words_to_add_that_come_wrapped_in_commas_go_in_without_them():
    outcome = _applied([{"prompt": "positive", "add": ", freckles, soft light, ", "for": "freckles"}],
                       asked=("freckles",))

    assert outcome.positive == "a woman on a couch, freckles, soft light"
    assert outcome.line == 'Added "freckles, soft light" to the Positive Prompt.'


def test_words_quoted_with_a_space_missing_or_added_are_still_found_where_they_stand():
    outcome = _applied([{"prompt": "positive", "replace": "on acouch", "with": "on a couch, freckles",
                         "for": "freckles"},
                        {"prompt": "negative", "remove": "blur ry", "for": "blurry is fine"}],
                       asked=("freckles, and blurry is fine",))

    assert (outcome.positive, outcome.negative) == ("a woman on a couch, freckles", "")
