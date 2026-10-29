from __future__ import annotations

import pytest

import origenerator.setting_advice as advice_module
from origenerator.setting_advice import (
    STRENGTH_BELOW_ONE,
    fix_lora_model_advice,
    fresh_settings,
    not_installed,
    not_installed_advice,
    recommendations,
    recommended_choices,
    setting_advice,
    trigger_word_advice,
)
from origenerator.workflows.base import ParamDef, ParamType
from origenerator.workflows.lora_rows import lora_strength

MODELS = {
    "example_model.safetensors": {
        "name": "Example Model",
        "samplers": {"euler_ancestral": ["normal", "simple"], "dpmpp_2m": ["karras"]},
        "steps": [20, 40],
        "cfg": [3, 6],
        "start": {"sampler_name": "euler_ancestral", "scheduler": "normal", "steps": 30,
                  "cfg": 4},
    },
}
LORAS = {
    "example_speed_high.safetensors": {"name": "Example Speed", "strength": [1, 1],
                                       "cfg": [1, 1], "steps": [4, 8], "shift": [5, 5]},
    "example_speed_low.safetensors": {"name": "Example Speed", "strength": [1, 1],
                                      "cfg": [1, 1], "steps": [4, 8], "shift": [5, 5]},
}


@pytest.fixture(autouse=True)
def _recommendations(monkeypatch):
    monkeypatch.setattr(advice_module, "model_recommendations", lambda: MODELS)
    monkeypatch.setattr(advice_module, "lora_recommendations", lambda: LORAS)


def _image(**changes):
    return {"checkpoint": "example_model.safetensors", "sampler_name": "euler_ancestral",
            "scheduler": "normal", "steps": 30, "cfg": 4.0, **changes}


def _said(params):
    return {key: advice.text for key, advice in setting_advice(params).items()}


def test_an_image_on_its_models_recommended_settings_gets_no_advice():
    assert _said(_image()) == {}


def test_a_sampler_the_models_page_does_not_name_is_advised_against():
    advice = _said(_image(sampler_name="heun"))
    assert advice == {"sampler_name": "Example Model's page recommends euler_ancestral "
                                      "or dpmpp_2m."}


def test_a_step_spacing_the_models_page_does_not_pair_with_its_sampler_is_advised_against():
    advice = _said(_image(sampler_name="dpmpp_2m", scheduler="normal"))
    assert advice == {"scheduler": "Example Model's page pairs dpmpp_2m with karras."}


def test_a_sampler_the_models_page_names_without_a_step_spacing_takes_any_good_one(monkeypatch):
    page = dict(MODELS["example_model.safetensors"], samplers={"euler_ancestral": [],
                                                               "dpmpp_sde": ["karras"]})
    monkeypatch.setattr(advice_module, "model_recommendations",
                        lambda: {"example_model.safetensors": page})

    assert _said(_image(scheduler="karras")) == {}


def test_steps_and_prompt_strength_outside_the_models_range_are_advised_against():
    advice = _said(_image(steps=50, cfg=7.5))
    assert advice == {"steps": "Example Model's page recommends 20–40 steps.",
                      "cfg": "Example Model's page recommends 3–6."}


def test_a_model_with_no_page_gets_only_the_step_spacing_its_sampler_wants():
    unknown = _image(checkpoint="another_model.safetensors", sampler_name="dpmpp_2m",
                     steps=80, cfg=12.0)
    assert _said(unknown) == {"scheduler": "dpmpp_2m works best with karras or "
                                                    "exponential."}


def test_euler_takes_any_step_spacing():
    assert _said(_image(checkpoint="another.safetensors", sampler_name="euler",
                                   scheduler="karras")) == {}


def test_a_speed_lora_on_both_passes_asks_for_its_own_settings():
    video = {"lora_high": "example_speed_high.safetensors",
             "lora_low": "example_speed_low.safetensors", "lora_strength_high": 0.8,
             "lora_strength_low": 1.0, "steps": 20, "cfg_high": 3.5, "cfg_low": 1.0,
             "shift_high": 8.0}
    assert _said(video) == {
        "lora_strength_high": "Example Speed's page recommends a strength of 1.",
        "steps": "With the Example Speed LoRA, its page recommends 4–8 steps.",
        "cfg_high": "With the Example Speed LoRA, its page recommends 1.",
        "shift_high": "With the Example Speed LoRA, its page recommends 5.",
    }


def test_a_speed_lora_on_one_pass_leaves_the_shared_settings_alone():
    video = {"lora_high": "None", "lora_low": "example_speed_low.safetensors",
             "lora_strength_low": 1.0, "steps": 20, "cfg_high": 3.5, "cfg_low": 1.0,
             "shift_high": 8.0}
    assert _said(video) == {}


def test_a_known_model_starts_a_fresh_image_on_its_recommended_settings():
    defaults = {"checkpoint": "example_model.safetensors", "sampler_name": "euler",
                "scheduler": "normal", "steps": 50, "cfg": 7.5, "seed": 0}
    assert fresh_settings(defaults, "example_model.safetensors") == {
        **defaults, "sampler_name": "euler_ancestral", "steps": 30, "cfg": 4}
    assert fresh_settings(defaults, "another_model.safetensors") == defaults


def test_a_models_samplers_and_the_spacings_its_page_pairs_are_its_recommended_choices():
    assert recommended_choices(_image(sampler_name="dpmpp_2m")) == {
        "sampler_name": ("euler_ancestral", "dpmpp_2m"), "scheduler": ("karras",)}


def test_without_a_page_only_the_spacing_its_sampler_wants_is_recommended():
    unknown = _image(checkpoint="another_model.safetensors", sampler_name="dpmpp_2m")
    assert recommended_choices(unknown) == {"sampler_name": (),
                                            "scheduler": ("karras", "exponential")}
    assert recommended_choices(dict(unknown, sampler_name="euler")) == {"sampler_name": (),
                                                                       "scheduler": ()}


def test_a_sampler_off_the_page_still_hears_which_step_spacing_it_wants():
    advice = _said(_image(sampler_name="dpmpp_sde", scheduler="normal"))
    assert advice == {
        "sampler_name": "Example Model's page recommends euler_ancestral or dpmpp_2m.",
        "scheduler": "dpmpp_sde works best with karras."}


def test_a_number_outside_its_models_range_is_set_to_the_nearer_end():
    advice = setting_advice(_image(steps=50, cfg=2.5))
    assert (advice["steps"].fix, advice["cfg"].fix) == (40, 3)


def test_a_dropdown_off_its_recommendation_is_set_to_the_nearest_recommended_choice():
    assert setting_advice(_image(sampler_name="heun"))["sampler_name"].fix == "euler_ancestral"
    assert setting_advice(_image(sampler_name="dpmpp_2m_sde"))["sampler_name"].fix == "dpmpp_2m"
    assert setting_advice(_image(scheduler="beta"))["scheduler"].fix == "simple"


def test_a_speed_loras_settings_are_set_to_what_its_page_recommends():
    video = {"lora_high": "example_speed_high.safetensors",
             "lora_low": "example_speed_low.safetensors", "lora_strength_high": 0.8,
             "lora_strength_low": 1.0, "steps": 20, "cfg_high": 3.5, "cfg_low": 1.0,
             "shift_high": 8.0}
    fixes = {key: advice.fix for key, advice in setting_advice(video).items()}
    assert fixes == {"lora_strength_high": 1, "steps": 8, "cfg_high": 1, "shift_high": 5}


def test_a_number_outside_its_definitions_good_range_is_advised_against():
    steps = ParamDef("steps", "Steps", ParamType.INT, 30, good=(20, 40))
    advice = setting_advice({"steps": 50}, [steps])
    assert (advice["steps"].text, advice["steps"].fix) == ("Good range: 20–40.", 40)


def test_a_prompt_strength_below_one_is_warned_about_before_its_good_range():
    cfg = ParamDef("cfg", "Prompt Strength", ParamType.FLOAT, 7.5, good=(3, 8))
    found = setting_advice({"cfg": 0.5}, [cfg])["cfg"]
    assert (found.text, found.fix) == (f"{STRENGTH_BELOW_ONE} Good range: 3–8.", 3)


def test_a_prompt_strength_of_exactly_one_gets_no_warning():
    cfg = ParamDef("cfg", "Prompt Strength", ParamType.FLOAT, 1.0, good=(1.0, 3.5))
    assert setting_advice({"cfg": 1.0}, [cfg]) == {}


def test_only_the_pass_whose_strength_is_below_one_is_warned_about():
    passes = [
        ParamDef("cfg_high", "Prompt Strength (First Pass)", ParamType.FLOAT, 3.5, good=(3, 4)),
        ParamDef("cfg_low", "Prompt Strength (Second Pass)", ParamType.FLOAT, 3.5, good=(3, 4)),
    ]
    advice = setting_advice({"cfg_high": 0.5, "cfg_low": 3.0}, passes)
    assert {key: (found.text, found.fix) for key, found in advice.items()} == {
        "cfg_high": (f"{STRENGTH_BELOW_ONE} Good range: 3–4.", 3)}


def test_a_prompt_strength_below_one_is_warned_about_even_with_no_range_to_hold_it_to():
    found = setting_advice({"cfg": 0.5})["cfg"]
    assert (found.text, found.value, found.fix) == (STRENGTH_BELOW_ONE, 0.5, 1.0)


def test_a_number_its_models_page_judges_is_not_held_to_its_definitions_range():
    cfg = ParamDef("cfg", "Prompt Strength", ParamType.FLOAT, 4.0, good=(3, 4))
    assert setting_advice(_image(cfg=5.5), [cfg]) == {}
    assert setting_advice(_image(cfg=7.5), [cfg])["cfg"].text == (
        "Example Model's page recommends 3–6.")


def test_a_number_a_speed_loras_page_judges_is_not_held_to_its_definitions_range():
    steps = ParamDef("steps", "Steps", ParamType.INT, 20, good=(20, 30))
    video = {"lora_high": "example_speed_high.safetensors",
             "lora_low": "example_speed_low.safetensors", "lora_strength_high": 1.0,
             "lora_strength_low": 1.0, "steps": 6, "cfg_high": 1.0, "cfg_low": 1.0,
             "shift_high": 5.0}
    assert setting_advice(video, [steps]) == {}


def test_a_models_page_is_quoted_for_every_setting_it_speaks_for_even_when_followed():
    assert recommendations(_image(sampler_name="dpmpp_2m", scheduler="karras")) == {
        "sampler_name": "Example Model's page recommends euler_ancestral or dpmpp_2m.",
        "scheduler": "Example Model's page pairs dpmpp_2m with karras.",
        "steps": "Example Model's page recommends 20–40 steps.",
        "cfg": "Example Model's page recommends 3–6.",
    }


def test_a_speed_loras_page_is_quoted_for_every_setting_it_speaks_for():
    video = {"lora_high": "example_speed_high.safetensors",
             "lora_low": "example_speed_low.safetensors", "lora_strength_high": 1.0,
             "lora_strength_low": 1.0, "steps": 6, "cfg_high": 1.0, "cfg_low": 1.0,
             "shift_high": 5.0}
    assert recommendations(video) == {
        "lora_strength_high": "Example Speed's page recommends a strength of 1.",
        "lora_strength_low": "Example Speed's page recommends a strength of 1.",
        "cfg_high": "With the Example Speed LoRA, its page recommends 1.",
        "cfg_low": "With the Example Speed LoRA, its page recommends 1.",
        "steps": "With the Example Speed LoRA, its page recommends 4–8 steps.",
        "shift_high": "With the Example Speed LoRA, its page recommends 5.",
    }


def test_with_no_page_only_the_step_spacing_its_sampler_wants_is_quoted():
    unknown = _image(checkpoint="another_model.safetensors", sampler_name="dpmpp_2m")
    assert recommendations(unknown) == {
        "scheduler": "dpmpp_2m works best with karras or exponential."}


_DURATION = ParamDef("frame_count", "Duration", ParamType.INT, 81, min_val=5, max_val=161,
                     step=4, unit="s", rate=16, good=(81, 161))


def test_a_durations_fix_is_shown_in_seconds():
    found = setting_advice({"frame_count": 201}, [_DURATION])["frame_count"]
    assert (found.fix, found.fix_shown) == (161, "10 s")


def test_an_advice_says_the_value_it_advises_against_the_way_it_says_its_fix():
    advice = setting_advice(_image(sampler_name="heun", steps=50, cfg=7.5, frame_count=201),
                            [_DURATION])
    assert {key: found.value_shown for key, found in advice.items()} == {
        "sampler_name": "heun", "steps": "50", "cfg": "7.5", "frame_count": "12.6 s"}


_PICKERS = [
    ParamDef("checkpoint", "Model", ParamType.COMBO, "installed_a.safetensors",
             options=["installed_a.safetensors", "installed_b.safetensors"]),
    ParamDef("lora_high", "LoRA", ParamType.COMBO, "None",
             options=["None", "installed_lora.safetensors"]),
    ParamDef("vae", "VAE", ParamType.STR, ""),
]
_FILE_KEYS = ("checkpoint", "lora_high", "vae")


def test_a_chosen_model_its_dropdown_does_not_offer_is_not_installed():
    params = {"checkpoint": "gone.safetensors", "lora_high": "None", "vae": "any.safetensors"}

    assert not_installed(params, _PICKERS, _FILE_KEYS) == {"checkpoint": "gone.safetensors"}


def test_a_lora_left_on_none_is_never_called_not_installed():
    params = {"checkpoint": "installed_a.safetensors", "lora_high": "None"}

    assert not_installed(params, _PICKERS, _FILE_KEYS) == {}


def test_a_key_not_asked_about_is_never_called_not_installed():
    params = {"checkpoint": "gone.safetensors", "lora_high": "gone_lora.safetensors"}

    assert not_installed(params, _PICKERS, ("lora_high",)) == {"lora_high": "gone_lora.safetensors"}


def test_a_missing_model_is_answered_with_the_workflows_own_default():
    found = not_installed_advice({"checkpoint": "gone.safetensors"}, _PICKERS,
                                 {"checkpoint": "installed_b.safetensors"})

    assert found["checkpoint"].fix == "installed_b.safetensors"
    assert found["checkpoint"].text == "Not installed anymore, so nothing can be made with it."
    assert (found["checkpoint"].value_shown, found["checkpoint"].fix_shown) == (
        "gone", "installed_b")


def test_a_missing_model_whose_default_is_gone_too_is_answered_with_the_first_installed_one():
    found = not_installed_advice({"checkpoint": "gone.safetensors"}, _PICKERS,
                                 {"checkpoint": "also_gone.safetensors"})

    assert found["checkpoint"].fix == "installed_a.safetensors"


_STRENGTHS_ON_AN_IMAGE = [lora_strength(key, 1.0)
                           for key in ("lora_strength", "lora_strength_2", "lora_strength_3")]


def test_a_strength_takes_a_lower_good_range_while_another_lora_is_picked():
    image = {"lora": "first_look.safetensors", "lora_strength": 1.0,
               "lora_2": "second_look.safetensors", "lora_strength_2": 0.7,
               "lora_3": "None", "lora_strength_3": 1.0}

    advice = setting_advice(image, _STRENGTHS_ON_AN_IMAGE)

    assert {key: (found.text, found.fix) for key, found in advice.items()} == {
        "lora_strength": ("Good range while another LoRA is picked: 0.6–0.8.", 0.8)}


def test_the_tooltip_of_every_picked_strength_gives_the_range_while_loras_share_an_image():
    image = {"lora": "first_look.safetensors", "lora_strength": 1.0,
               "lora_2": "None", "lora_strength_2": 1.0,
               "lora_3": "second_look.safetensors", "lora_strength_3": 0.7}

    assert recommendations(image) == {
        "lora_strength": "Good range while another LoRA is picked: 0.6–0.8.",
        "lora_strength_3": "Good range while another LoRA is picked: 0.6–0.8."}
    assert recommendations(image | {"lora_3": "None"}) == {}


def test_loras_share_a_video_pass_by_pass():
    video = {"lora_high": "a_look_high.safetensors", "lora_strength_high": 1.0,
             "lora_high_2": "another_look_high.safetensors", "lora_strength_high_2": 1.0,
             "lora_low": "a_look_low.safetensors", "lora_strength_low": 1.0}

    assert recommendations(video) == {
        "lora_strength_high": "Good range while another LoRA is picked for this pass: 0.6–0.8.",
        "lora_strength_high_2": "Good range while another LoRA is picked for this pass: 0.6–0.8."}


def test_a_loras_page_holds_its_strength_in_any_row_even_while_loras_share_its_pass():
    video = {"lora_high": "a_look_high.safetensors", "lora_strength_high": 1.0,
             "lora_low": "a_look_low.safetensors", "lora_strength_low": 1.0,
             "lora_low_2": "example_speed_low.safetensors", "lora_strength_low_2": 0.8}

    advice = setting_advice(video)

    assert (advice["lora_strength_low_2"].text, advice["lora_strength_low_2"].fix) == (
        "Example Speed's page recommends a strength of 1.", 1)
    assert advice["lora_strength_low"].text == (
        "Good range while another LoRA is picked for this pass: 0.6–0.8.")


_STYLE = "example_style.safetensors"
_STYLE_SAID = ("Example Style 1.0's trigger word, exmplstyle, isn't in the Positive Prompt. "
               "Click to add it.")


@pytest.fixture
def worded_style(worded_loras, titled_models):
    worded_loras({"example_style": ["exmplstyle"]})
    titled_models({"example_style": "Example Style 1.0"})


def test_a_picked_lora_whose_trigger_word_the_prompt_lacks_says_so_by_its_title(worded_style):
    found = trigger_word_advice({"positive_prompt": "a portrait", "lora": _STYLE}, ("lora",))

    assert (found["lora"].said, found["lora"].value_shown) == (_STYLE_SAID, "Example Style 1.0")


def test_the_click_on_a_missing_trigger_word_puts_it_at_the_start_of_the_positive_prompt(
        worded_style):
    found = trigger_word_advice({"positive_prompt": "a portrait", "lora": _STYLE}, ("lora",))

    assert found["lora"].writes == "positive_prompt"
    assert found["lora"].fixed("a portrait, soft light") == "exmplstyle, a portrait, soft light"


def test_a_lora_whose_trigger_word_the_prompt_holds_gets_no_warning(worded_style):
    params = {"positive_prompt": "(Exmplstyle:1.1), a portrait", "lora": _STYLE}

    assert trigger_word_advice(params, ("lora",)) == {}


def test_a_lora_row_on_none_or_a_lora_with_no_word_written_down_gets_no_warning(worded_style):
    params = {"positive_prompt": "a portrait", "lora": "None",
              "lora_low": "example_plain.safetensors"}

    assert trigger_word_advice(params, ("lora", "lora_low")) == {}


def test_only_the_lora_rows_asked_about_are_checked(worded_style):
    params = {"positive_prompt": "a portrait", "lora": _STYLE, "lora_low": _STYLE}

    assert set(trigger_word_advice(params, ("lora_low",))) == {"lora_low"}


@pytest.fixture
def worded_acts(worded_loras, titled_models):
    worded_loras({"example_acts": ["alpha", "beta", "gamma", "delta"]})
    titled_models({"example_acts": "Example Acts 1.0"})


def test_a_lora_with_several_trigger_words_names_them_all_and_its_click_adds_the_first(
        worded_acts):
    found = trigger_word_advice({"positive_prompt": "a portrait",
                                 "lora": "example_acts.safetensors"}, ("lora",))["lora"]

    assert found.said == ("Example Acts 1.0's trigger words, alpha, beta, gamma and delta, "
                          "aren't in the Positive Prompt. Click to add alpha.")
    assert found.fixed("a portrait") == "alpha, a portrait"


def test_a_lora_with_several_trigger_words_warns_only_while_none_of_them_is_in_the_prompt(
        worded_acts):
    params = {"positive_prompt": "a portrait, gamma", "lora": "example_acts.safetensors"}

    assert trigger_word_advice(params, ("lora",)) == {}


def test_an_entry_longer_than_five_words_is_never_warned_about(worded_loras, titled_models):
    worded_loras({"example_scene": ["one two three four five six"],
                  "example_mixed": ["alpha", "one two three four five six"]})
    titled_models({"example_mixed": "Example Mixed 1.0"})
    params = {"positive_prompt": "a portrait", "lora": "example_scene.safetensors",
              "lora_low": "example_mixed.safetensors"}

    found = trigger_word_advice(params, ("lora", "lora_low"))

    assert list(found) == ["lora_low"]
    assert found["lora_low"].said == ("Example Mixed 1.0's trigger word, alpha, isn't in the "
                                      "Positive Prompt. Click to add it.")


def test_a_trigger_word_of_five_words_is_still_one_to_warn_about(worded_loras):
    worded_loras({"example_scene": ["one two three four five"]})
    params = {"positive_prompt": "a portrait", "lora": "example_scene.safetensors"}

    assert set(trigger_word_advice(params, ("lora",))) == {"lora"}


def test_a_setting_advices_click_uses_its_fix_whatever_the_setting_holds():
    found = setting_advice(_image(steps=50))["steps"]

    assert (found.writes, found.fixed(50), found.said) == (
        "", 40, "Example Model's page recommends 20–40 steps. Click to use 40.")


def test_a_ticked_fixs_lora_trained_on_another_installed_model_says_so_and_a_click_uses_it(
        titled_models):
    titled_models({"trained_on": "Trained On v1"})

    found = fix_lora_model_advice({"picked.safetensors"}, {"hands": "trained_on.safetensors"},
                                  ["picked.safetensors", "trained_on.safetensors"])

    assert found["checkpoint"].said == (
        "The Hands fix's LoRA was trained on Trained On v1. Click to use Trained On v1.")
    assert found["checkpoint"].fixed("picked.safetensors") == "trained_on.safetensors"


def test_no_model_advice_while_a_fixs_lora_has_its_model_or_that_model_is_not_installed():
    assert fix_lora_model_advice({"trained_on.safetensors"}, {"hands": "trained_on.safetensors"},
                                 ["trained_on.safetensors"]) == {}
    assert fix_lora_model_advice({"picked.safetensors"}, {"hands": "gone.safetensors"},
                                 ["picked.safetensors"]) == {}
