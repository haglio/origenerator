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


def test_a_replacement_that_puts_the_whole_prompt_in_the_plural_keeps_every_part_it_changed():
    one = "one woman in a red dress, she smiles at the camera, her hand on a railing, a city street"
    two = "two women in red dresses, they smile at the camera, their hands on a railing, a city street"

    outcome = _applied([{"prompt": "positive", "replace": one, "with": two, "for": "two women"}],
                       pair=(one, "blurry"), asked=("two women",))

    assert outcome.positive == two


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


def test_a_weight_written_around_some_words_of_a_part_comes_off_where_prompts_take_none():
    outcome = apply_changes(
        {"changes": [{"prompt": "positive", "replace": "a woman",
                      "with": "a (tall:0.8) woman, ((freckles)), (soft (warm:1.2) light:1.1)",
                      "for": "taller"}]},
        ("a woman on a couch", "blurry"), asked=["taller"], settings=_SIZE,
        prompts=Prompts(take_weights=False))

    assert outcome.positive == "a tall woman, freckles, soft warm light on a couch"


_THE_WORD_VINTAGE = ('maybe the word "vintage" is throwing the colors off?',)
_A_VINTAGE_PHOTO = ("vintage photo of a woman on a couch, soft light", "blurry")


def test_a_word_he_quoted_is_taken_out_alone_whatever_else_the_model_takes_with_it():
    outcome = _applied([{"prompt": "positive", "remove": "vintage photo of", "for": "vintage"}],
                       pair=_A_VINTAGE_PHOTO, asked=_THE_WORD_VINTAGE)

    assert outcome.positive == "photo of a woman on a couch, soft light"
    assert outcome.line == 'Removed "vintage" from the Positive Prompt.'


def test_new_words_put_where_the_word_he_quoted_stood_are_the_models_to_write():
    outcome = _applied([{"prompt": "positive", "replace": "vintage photo of", "with": "painting of",
                         "for": "vintage"}],
                       pair=_A_VINTAGE_PHOTO, asked=_THE_WORD_VINTAGE)

    assert outcome.positive == "painting of a woman on a couch, soft light"


def test_words_he_never_quoted_go_whole_as_the_model_took_them():
    outcome = _applied([{"prompt": "positive", "remove": "vintage photo of", "for": "vintage"}],
                       pair=_A_VINTAGE_PHOTO, asked=("no vintage photo please",))

    assert outcome.positive == "a woman on a couch, soft light"


@pytest.mark.parametrize("request_", [
    "take out the word vintage",
    "is “vintage” throwing the colors off?",
    "she's too brown. is 'vintage' doing that?",
])
def test_a_word_is_his_to_name_with_or_without_quotation_marks(request_):
    outcome = _applied([{"prompt": "positive", "remove": "vintage photo of", "for": "vintage"}],
                       pair=_A_VINTAGE_PHOTO, asked=(request_,))

    assert outcome.positive == "photo of a woman on a couch, soft light"


def test_a_replacement_that_only_takes_words_out_takes_out_the_one_he_quoted():
    outcome = _applied([{"prompt": "positive", "replace": "vintage photo of a woman",
                         "with": "a woman", "for": "vintage"}],
                       pair=_A_VINTAGE_PHOTO, asked=_THE_WORD_VINTAGE)

    assert outcome.positive == "photo of a woman on a couch, soft light"
    assert outcome.line == 'Removed "vintage" from the Positive Prompt.'


_MORE_COUCH = ("a woman on a velvet couch, soft light", "blurry, bare floor")
_NOTHING_ELSE_TO_DO = ('"a velvet couch" was already in the Positive Prompt, and its opposite already '
                       "in the Negative Prompt, so I couldn't figure out anything else to do.")


_NO_WEIGHTS = Prompts(take_weights=False)


def _one(change, pair, asked, prompts=_NO_WEIGHTS):
    return apply_changes({"changes": [change]}, pair, asked=list(asked), settings=_SIZE, prompts=prompts)


def test_more_of_something_puts_his_stronger_words_in_moves_it_first_and_keeps_its_opposite_out():
    outcome = _one({"more": "a small necklace", "stronger": "a large pendant necklace",
                    "opposite": "bare neck", "for": "more necklace"},
                   ("a woman on a couch, a small necklace, soft light", "blurry"), ("more necklace",),
                   prompts=Prompts(take_weights=False, his_words=frozenset({"large", "pendant"})))

    assert outcome.positive == "a large pendant necklace, a woman on a couch, soft light"
    assert outcome.negative == "blurry, bare neck"
    assert outcome.line == (
        'Replaced "a small necklace" with "a large pendant necklace" in the Positive Prompt. '
        'Moved "a large pendant necklace" earlier in the Positive Prompt. '
        'Added "bare neck" to the Negative Prompt.')


def test_stronger_words_that_his_prompts_never_use_leave_the_part_as_it_is():
    his = Prompts(take_weights=False, his_words=frozenset({"wide", "brimmed"}))
    pair = ("photo of a woman, a small straw hat, beach", "blurry")

    invented = _one({"more": "a small straw hat", "stronger": "an enormous straw hat",
                     "opposite": "bare head", "for": "bigger hat"}, pair, ("bigger hat",), prompts=his)
    in_his_words = _one({"more": "a small straw hat", "stronger": "a wide brimmed straw hat",
                         "opposite": "bare head", "for": "bigger hat"}, pair, ("bigger hat",), prompts=his)

    assert invented.positive == "a small straw hat, photo of a woman, beach"
    assert invented.line == ('Moved "a small straw hat" earlier in the Positive Prompt. '
                             'Added "bare head" to the Negative Prompt.')
    assert in_his_words.positive == "a wide brimmed straw hat, photo of a woman, beach"


def test_more_of_something_where_the_prompts_take_weights_weighs_it_and_its_opposite_more():
    outcome = _one({"more": "a velvet couch", "stronger": "a velvet couch", "opposite": "bare floor",
                    "for": "more couch"}, _MORE_COUCH, ("more couch",), prompts=Prompts())

    assert outcome.positive == "(a woman on a velvet couch:1.1), soft light"
    assert outcome.negative == "blurry, (bare floor:1.1)"
    assert outcome.line == (
        'Replaced "a woman on a velvet couch" with "(a woman on a velvet couch:1.1)" in the Positive '
        'Prompt. Replaced "bare floor" with "(bare floor:1.1)" in the Negative Prompt.')


def test_more_of_something_already_first_in_his_words_with_its_opposite_kept_out_says_so():
    outcome = _one({"more": "a velvet couch", "stronger": "a velvet couch", "opposite": "bare floor",
                    "for": "even more couch"}, _MORE_COUCH, ("even more couch",))

    assert (outcome.positive, outcome.negative) == _MORE_COUCH
    assert outcome.line == _NOTHING_ELSE_TO_DO


def test_more_of_something_the_positive_prompt_lacks_puts_it_first_with_its_opposite_kept_out():
    outcome = _one({"more": "", "stronger": "freckles", "opposite": "clear skin", "for": "more freckles"},
                   ("a woman on a couch", "blurry"), ("more freckles",))

    assert (outcome.positive, outcome.negative) == ("freckles, a woman on a couch", "blurry, clear skin")
    assert outcome.line == ('Added "freckles" to the Positive Prompt. '
                            'Added "clear skin" to the Negative Prompt.')


def test_more_of_something_he_never_asked_about_is_left_out_without_a_word():
    outcome = _one({"more": "soft light", "stronger": "bright light", "opposite": "dark", "for": "light"},
                   _MORE_COUCH, ("more couch",))

    assert (outcome.positive, outcome.negative) == _MORE_COUCH
    assert outcome.line == "Nothing changed."


def test_something_gone_gives_its_place_to_what_shows_instead_and_is_kept_out():
    outcome = _one({"gone": "raincoat", "in_positive": "a woman in a yellow raincoat",
                    "instead": "a woman in a sundress", "for": "remove her raincoat"},
                   ("a woman in a yellow raincoat, a pier at noon", "blurry"), ("remove her raincoat",))

    assert (outcome.positive, outcome.negative) == ("a woman in a sundress, a pier at noon",
                                                    "blurry, raincoat")
    assert outcome.line == ('Replaced "a woman in a yellow raincoat" with "a woman in a sundress" in '
                            'the Positive Prompt. Added "raincoat" to the Negative Prompt.')


def test_something_gone_in_several_kinds_takes_every_kind_out():
    outcome = _one({"gone": "hat", "in_positive": "a straw hat, a cap", "instead": "", "for": "no hats"},
                   ("a woman, a straw hat, a cap, a beach", "blurry"), ("no hats",))

    assert (outcome.positive, outcome.negative) == ("a woman, a beach", "blurry, hat")
    assert outcome.line == ('Removed "a straw hat" from the Positive Prompt. '
                            'Removed "a cap" from the Positive Prompt. Added "hat" to the Negative Prompt.')


def test_something_gone_that_is_already_out_and_kept_out_says_so():
    outcome = _one({"gone": "raincoat", "in_positive": "", "instead": "",
                    "for": "try harder to get rid of the raincoat"},
                   ("a woman on a pier", "blurry, raincoat"), ("try harder to get rid of the raincoat",))

    assert (outcome.positive, outcome.negative) == ("a woman on a pier", "blurry, raincoat")
    assert outcome.line == ('"raincoat" was already out of the Positive Prompt and in the Negative '
                            "Prompt, so I couldn't figure out anything else to do.")


def test_something_gone_that_is_already_kept_out_where_the_prompts_take_weights_is_kept_out_harder():
    outcome = _one({"gone": "raincoat", "in_positive": "", "instead": "", "for": "no raincoat"},
                   ("a woman on a pier", "blurry, raincoat"), ("no raincoat",), prompts=Prompts())

    assert outcome.negative == "blurry, (raincoat:1.1)"
    assert outcome.line == 'Replaced "raincoat" with "(raincoat:1.1)" in the Negative Prompt.'


def test_what_the_positive_prompt_never_had_is_not_said_missing_when_he_names_the_negative_prompt():
    outcome = _applied([{"prompt": "negative", "add": "hat", "for": "put hat back"}],
                       asked=("put hat back into the Negative Prompt",))

    assert outcome.line == 'Added "hat" to the Negative Prompt.'


def test_an_opposite_kept_out_to_bring_out_what_he_asked_for_is_said_only_as_added():
    outcome = _applied([{"prompt": "negative", "add": "bare floor", "for": "more of the couch"}],
                       asked=("more of the couch",))

    assert outcome.negative == "blurry, bare floor"
    assert outcome.line == 'Added "bare floor" to the Negative Prompt.'


def test_a_weight_raised_on_several_words_is_said_with_its_parentheses_whole():
    outcome = _applied([{"prompt": "positive", "replace": "(a velvet couch:1.3)",
                         "with": "(a velvet couch:1.5), couch cushions", "for": "more couch"}],
                       pair=("a woman, (a velvet couch:1.3)", "blurry"), asked=("more couch",))

    assert outcome.line == ('Replaced "(a velvet couch:1.3)" with "(a velvet couch:1.5)" '
                            'in the Positive Prompt. Added "couch cushions" to the Positive Prompt.')


_COUCH_LAST = ("a woman, soft light, a velvet couch", "blurry")


def _moved_by_one_replacement(new):
    return _applied([{"prompt": "positive", "replace": _COUCH_LAST[0], "with": new, "for": "more couch"}],
                    pair=_COUCH_LAST, asked=("more couch",))


def test_a_part_a_replacement_puts_earlier_is_said_as_moved():
    outcome = _moved_by_one_replacement("a velvet couch, a woman, soft light")

    assert outcome.positive == "a velvet couch, a woman, soft light"
    assert outcome.line == 'Moved "a velvet couch" earlier in the Positive Prompt.'


def test_a_part_reworded_as_it_is_moved_is_said_as_replaced_and_then_moved():
    outcome = _moved_by_one_replacement("a wide velvet couch, a woman, soft light")

    assert outcome.positive == "a wide velvet couch, a woman, soft light"
    assert outcome.line == ('Replaced "a velvet couch" with "a wide velvet couch" in the Positive Prompt. '
                            'Moved "a wide velvet couch" earlier in the Positive Prompt.')


def test_a_part_put_later_is_said_as_moved_later():
    outcome = _applied([{"prompt": "positive", "replace": "a velvet couch, a woman, soft light",
                         "with": "a woman, soft light, a velvet couch", "for": "less couch"}],
                       pair=("a velvet couch, a woman, soft light", "blurry"), asked=("less couch",))

    assert outcome.line == 'Moved "a velvet couch" later in the Positive Prompt.'


def test_a_change_quoting_the_prompt_as_it_stood_before_the_change_ahead_of_it_is_still_found():
    outcome = _applied([{"prompt": "positive", "replace": "a velvet couch", "with": "a wide velvet couch",
                         "for": "more couch"},
                        {"prompt": "positive", "replace": _COUCH_LAST[0],
                         "with": "a wide velvet couch, a woman, soft light", "for": "more couch"}],
                       pair=_COUCH_LAST, asked=("more couch",))

    assert outcome.positive == "a wide velvet couch, a woman, soft light"
    assert outcome.line == ('Replaced "a velvet couch" with "a wide velvet couch" in the Positive Prompt. '
                            'Moved "a wide velvet couch" earlier in the Positive Prompt.')


def test_what_the_positive_prompt_calls_for_is_never_kept_out_as_no_of_it():
    outcome = _applied([{"prompt": "negative", "add": "bare floor, no couch", "for": "more couch"},
                        {"prompt": "negative", "add": "without a couch", "for": "more couch"}],
                       pair=_COUCH_LAST, asked=("more couch",))

    assert outcome.negative == "blurry, bare floor"
    assert outcome.line == 'Added "bare floor" to the Negative Prompt.'


def test_something_to_leave_out_written_into_the_negative_prompt_as_no_of_it_goes_in_bare():
    outcome = _applied([{"prompt": "negative", "add": "no hat", "for": "no hat"}], asked=("no hat",))

    assert outcome.negative == "blurry, hat"
    assert outcome.line == _NO_HAT


def test_words_a_part_already_had_stay_when_its_rewording_puts_a_comma_before_them():
    outcome = _applied([{"prompt": "positive", "replace": "a velvet couch with a wide carved frame",
                         "with": "a velvet couch with a huge, carved frame", "for": "more couch"}],
                       pair=("a woman, a velvet couch with a wide carved frame", "blurry"),
                       asked=("more couch",))

    assert outcome.positive == "a woman, a velvet couch with a huge, carved frame"
    assert outcome.line == ('Replaced "a velvet couch with a wide carved frame" with "a velvet couch '
                            'with a huge, carved frame" in the Positive Prompt.')
