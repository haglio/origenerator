import json

from origenerator.generation_config import ConfigSnapshot, merge_denormalized


def _snapshot(workflow="sdxl_t2i", params=None, seed_is_random=False):
    return ConfigSnapshot(workflow, params or {}, seed_is_random)


def test_merge_denormalized_folds_in_columns():
    row = {
        "params_json": json.dumps({"steps": 20}),
        "positive_prompt": "a cat",
        "negative_prompt": "blurry",
        "seed": 7,
    }
    params = merge_denormalized(row)
    assert params == {
        "steps": 20,
        "positive_prompt": "a cat",
        "negative_prompt": "blurry",
        "seed": 7,
    }


def test_merge_denormalized_params_json_takes_precedence():
    row = {
        "params_json": json.dumps({"seed": 99, "positive_prompt": "from json"}),
        "positive_prompt": "from column",
        "negative_prompt": "neg col",
        "seed": 7,
    }
    params = merge_denormalized(row)
    assert params["seed"] == 99
    assert params["positive_prompt"] == "from json"
    assert params["negative_prompt"] == "neg col"


def test_merge_denormalized_handles_missing_or_invalid_params_json():
    assert merge_denormalized({"params_json": None, "seed": 5}) == {"seed": 5}
    assert merge_denormalized({"params_json": "not json", "seed": 5}) == {"seed": 5}
    assert merge_denormalized({}) == {}


def test_snapshot_round_trips_through_dict():
    snap = _snapshot(workflow="wan22_i2v", params={"steps": 20, "seed": 7},
                     seed_is_random=True)
    restored = ConfigSnapshot.from_dict(snap.to_dict())
    assert restored == snap


def test_snapshot_from_dict_tolerates_partial_and_corrupt_data():
    assert ConfigSnapshot.from_dict({}) == _snapshot(workflow="", params={})
    # A non-dict params payload degrades to empty rather than exploding.
    assert ConfigSnapshot.from_dict({"params": [1, 2]}).params == {}
