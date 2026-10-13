from __future__ import annotations

import pytest

import origenerator.setting_advice as advice_module
from origenerator.setting_advice import fresh_settings

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


@pytest.fixture(autouse=True)
def _recommendations(monkeypatch):
    monkeypatch.setattr(advice_module, "model_recommendations", lambda: MODELS)


def test_a_known_model_starts_a_fresh_picture_on_its_recommended_settings():
    defaults = {"checkpoint": "example_model.safetensors", "sampler_name": "euler",
                "scheduler": "normal", "steps": 50, "cfg": 7.5, "seed": 0}
    assert fresh_settings(defaults, "example_model.safetensors") == {
        **defaults, "sampler_name": "euler_ancestral", "steps": 30, "cfg": 4}
    assert fresh_settings(defaults, "another_model.safetensors") == defaults
