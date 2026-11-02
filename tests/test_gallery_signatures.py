from __future__ import annotations

import json

from origenerator.gallery.signatures import generation_seed


def test_a_videos_sampler_seed_comes_from_its_params_not_its_seed_column():
    row = {"params_json": json.dumps({"noise_seed": 77}), "seed": None}
    assert generation_seed(row) == "77"


def test_the_seed_column_is_the_fallback_when_the_params_name_no_seed():
    assert generation_seed({"params_json": "{}", "seed": 5}) == "5"


def test_a_row_with_no_seed_anywhere_has_none():
    assert generation_seed({"params_json": "{}", "seed": None}) is None
