from __future__ import annotations

import pytest

import origenerator.setting_advice as advice_module
from origenerator.setting_advice import fresh_settings, setting_advice

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


def test_a_picture_on_its_models_recommended_settings_gets_no_advice():
    assert setting_advice(_picture()) == {}


def test_a_sampler_the_models_page_does_not_name_is_advised_against():
    advice = setting_advice(_picture(sampler_name="heun"))
    assert advice == {"sampler_name": "Example Model's page recommends euler_ancestral "
                                      "or dpmpp_2m."}


def test_a_step_spacing_the_models_page_does_not_pair_with_its_sampler_is_advised_against():
    advice = setting_advice(_picture(sampler_name="dpmpp_2m", scheduler="normal"))
    assert advice == {"scheduler": "Example Model's page pairs dpmpp_2m with karras."}


def test_a_sampler_the_models_page_names_without_a_step_spacing_takes_any_good_one(monkeypatch):
    page = dict(MODELS["example_model.safetensors"], samplers={"euler_ancestral": [],
                                                               "dpmpp_sde": ["karras"]})
    monkeypatch.setattr(advice_module, "model_recommendations",
                        lambda: {"example_model.safetensors": page})

    assert setting_advice(_picture(scheduler="karras")) == {}


def test_steps_and_prompt_strength_outside_the_models_range_are_advised_against():
    advice = setting_advice(_picture(steps=50, cfg=7.5))
    assert advice == {"steps": "Example Model's page recommends 20–40 steps.",
                      "cfg": "Example Model's page recommends 3–6."}


def test_a_model_with_no_page_gets_only_the_step_spacing_its_sampler_wants():
    unknown = _picture(checkpoint="another_model.safetensors", sampler_name="dpmpp_2m",
                       steps=80, cfg=12.0)
    assert setting_advice(unknown) == {"scheduler": "dpmpp_2m works best with karras or "
                                                    "exponential."}


def test_euler_takes_any_step_spacing():
    assert setting_advice(_picture(checkpoint="another.safetensors", sampler_name="euler",
                                   scheduler="karras")) == {}


def test_a_speed_lora_on_both_passes_asks_for_its_own_settings():
    video = {"lora_high": "example_speed_high.safetensors",
             "lora_low": "example_speed_low.safetensors", "lora_strength_high": 0.8,
             "lora_strength_low": 1.0, "steps": 20, "cfg_high": 3.5, "cfg_low": 1.0,
             "shift_high": 8.0}
    assert setting_advice(video) == {
        "lora_strength_high": "Example Speed's page recommends a strength of 1.",
        "steps": "With the Example Speed LoRA, its page recommends 4–8 steps.",
        "cfg_high": "With the Example Speed LoRA, its page recommends 1.",
        "shift_high": "With the Example Speed LoRA, its page recommends 5.",
    }


def test_a_speed_lora_on_one_pass_leaves_the_shared_settings_alone():
    video = {"lora_high": "None", "lora_low": "example_speed_low.safetensors",
             "lora_strength_low": 1.0, "steps": 20, "cfg_high": 3.5, "cfg_low": 1.0,
             "shift_high": 8.0}
    assert setting_advice(video) == {}


def test_a_known_model_starts_a_fresh_picture_on_its_recommended_settings():
    defaults = {"checkpoint": "example_model.safetensors", "sampler_name": "euler",
                "scheduler": "normal", "steps": 50, "cfg": 7.5, "seed": 0}
    assert fresh_settings(defaults, "example_model.safetensors") == {
        **defaults, "sampler_name": "euler_ancestral", "steps": 30, "cfg": 4}
    assert fresh_settings(defaults, "another_model.safetensors") == defaults
