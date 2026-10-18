from __future__ import annotations

import pytest

import origenerator.setting_advice as advice_module
from origenerator.setting_advice import (
    fresh_settings,
    recommendations,
    recommended_choices,
    setting_advice,
)
from origenerator.workflows.base import ParamDef, ParamType

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


def _picture(**changes):
    return {"checkpoint": "example_model.safetensors", "sampler_name": "euler_ancestral",
            "scheduler": "normal", "steps": 30, "cfg": 4.0, **changes}


def _said(params):
    return {key: advice.text for key, advice in setting_advice(params).items()}


def test_a_picture_on_its_models_recommended_settings_gets_no_advice():
    assert _said(_picture()) == {}


def test_a_sampler_the_models_page_does_not_name_is_advised_against():
    advice = _said(_picture(sampler_name="heun"))
    assert advice == {"sampler_name": "Example Model's page recommends euler_ancestral "
                                      "or dpmpp_2m."}


def test_a_step_spacing_the_models_page_does_not_pair_with_its_sampler_is_advised_against():
    advice = _said(_picture(sampler_name="dpmpp_2m", scheduler="normal"))
    assert advice == {"scheduler": "Example Model's page pairs dpmpp_2m with karras."}


def test_a_sampler_the_models_page_names_without_a_step_spacing_takes_any_good_one(monkeypatch):
    page = dict(MODELS["example_model.safetensors"], samplers={"euler_ancestral": [],
                                                               "dpmpp_sde": ["karras"]})
    monkeypatch.setattr(advice_module, "model_recommendations",
                        lambda: {"example_model.safetensors": page})

    assert _said(_picture(scheduler="karras")) == {}


def test_steps_and_prompt_strength_outside_the_models_range_are_advised_against():
    advice = _said(_picture(steps=50, cfg=7.5))
    assert advice == {"steps": "Example Model's page recommends 20–40 steps.",
                      "cfg": "Example Model's page recommends 3–6."}


def test_a_model_with_no_page_gets_only_the_step_spacing_its_sampler_wants():
    unknown = _picture(checkpoint="another_model.safetensors", sampler_name="dpmpp_2m",
                       steps=80, cfg=12.0)
    assert _said(unknown) == {"scheduler": "dpmpp_2m works best with karras or "
                                                    "exponential."}


def test_euler_takes_any_step_spacing():
    assert _said(_picture(checkpoint="another.safetensors", sampler_name="euler",
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


def test_a_known_model_starts_a_fresh_picture_on_its_recommended_settings():
    defaults = {"checkpoint": "example_model.safetensors", "sampler_name": "euler",
                "scheduler": "normal", "steps": 50, "cfg": 7.5, "seed": 0}
    assert fresh_settings(defaults, "example_model.safetensors") == {
        **defaults, "sampler_name": "euler_ancestral", "steps": 30, "cfg": 4}
    assert fresh_settings(defaults, "another_model.safetensors") == defaults


def test_a_models_samplers_and_the_spacings_its_page_pairs_are_its_recommended_choices():
    assert recommended_choices(_picture(sampler_name="dpmpp_2m")) == {
        "sampler_name": ("euler_ancestral", "dpmpp_2m"), "scheduler": ("karras",)}


def test_without_a_page_only_the_spacing_its_sampler_wants_is_recommended():
    unknown = _picture(checkpoint="another_model.safetensors", sampler_name="dpmpp_2m")
    assert recommended_choices(unknown) == {"sampler_name": (),
                                            "scheduler": ("karras", "exponential")}
    assert recommended_choices(dict(unknown, sampler_name="euler")) == {"sampler_name": (),
                                                                       "scheduler": ()}


def test_a_sampler_off_the_page_still_hears_which_step_spacing_it_wants():
    advice = _said(_picture(sampler_name="dpmpp_sde", scheduler="normal"))
    assert advice == {
        "sampler_name": "Example Model's page recommends euler_ancestral or dpmpp_2m.",
        "scheduler": "dpmpp_sde works best with karras."}


def test_a_number_outside_its_models_range_is_set_to_the_nearer_end():
    advice = setting_advice(_picture(steps=50, cfg=2.5))
    assert (advice["steps"].fix, advice["cfg"].fix) == (40, 3)


def test_a_dropdown_off_its_recommendation_is_set_to_the_nearest_recommended_choice():
    assert setting_advice(_picture(sampler_name="heun"))["sampler_name"].fix == "euler_ancestral"
    assert setting_advice(_picture(sampler_name="dpmpp_2m_sde"))["sampler_name"].fix == "dpmpp_2m"
    assert setting_advice(_picture(scheduler="beta"))["scheduler"].fix == "simple"


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


def test_a_number_its_models_page_judges_is_not_held_to_its_definitions_range():
    cfg = ParamDef("cfg", "Prompt Strength", ParamType.FLOAT, 4.0, good=(3, 4))
    assert setting_advice(_picture(cfg=5.5), [cfg]) == {}
    assert setting_advice(_picture(cfg=7.5), [cfg])["cfg"].text == (
        "Example Model's page recommends 3–6.")


def test_a_number_a_speed_loras_page_judges_is_not_held_to_its_definitions_range():
    steps = ParamDef("steps", "Steps", ParamType.INT, 20, good=(20, 30))
    video = {"lora_high": "example_speed_high.safetensors",
             "lora_low": "example_speed_low.safetensors", "lora_strength_high": 1.0,
             "lora_strength_low": 1.0, "steps": 6, "cfg_high": 1.0, "cfg_low": 1.0,
             "shift_high": 5.0}
    assert setting_advice(video, [steps]) == {}


def test_a_models_page_is_quoted_for_every_setting_it_speaks_for_even_when_followed():
    assert recommendations(_picture(sampler_name="dpmpp_2m", scheduler="karras")) == {
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
    unknown = _picture(checkpoint="another_model.safetensors", sampler_name="dpmpp_2m")
    assert recommendations(unknown) == {
        "scheduler": "dpmpp_2m works best with karras or exponential."}


def test_a_durations_fix_is_shown_in_seconds():
    duration = ParamDef("frame_count", "Duration", ParamType.INT, 81, min_val=5, max_val=161,
                        step=4, unit="s", rate=16, good=(81, 161))
    found = setting_advice({"frame_count": 201}, [duration])["frame_count"]
    assert (found.fix, found.fix_shown) == (161, "10 s")
