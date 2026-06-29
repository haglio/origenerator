import json

from origenerator.generation_config import (
    ConfigSnapshot,
    configs_match,
    find_duplicate_generation,
    merge_denormalized,
    randomize_seeds,
)


def _snapshot(workflow="sdxl_t2i", params=None, seed_is_random=False):
    return ConfigSnapshot(workflow, params or {}, seed_is_random)


def _row(workflow="sdxl_t2i", params=None, status="completed", **extra):
    row = {
        "workflow_name": workflow,
        "status": status,
        "params_json": json.dumps(params or {}),
    }
    row.update(extra)
    return row


def test_configs_match_true_for_identical_workflow_and_params():
    snap = _snapshot(params={"steps": 20, "seed": 7})
    assert configs_match(snap, "sdxl_t2i", {"steps": 20, "seed": 7}) is True


def test_configs_match_false_when_seed_is_random():
    snap = _snapshot(params={"steps": 20, "seed": 7}, seed_is_random=True)
    assert configs_match(snap, "sdxl_t2i", {"steps": 20, "seed": 7}) is False


def test_configs_match_false_for_different_workflow():
    snap = _snapshot(workflow="wan22_i2v", params={"seed": 7})
    assert configs_match(snap, "sdxl_t2i", {"seed": 7}) is False


def test_configs_match_false_for_differing_param():
    snap = _snapshot(params={"steps": 20, "seed": 7})
    assert configs_match(snap, "sdxl_t2i", {"steps": 30, "seed": 7}) is False


def test_configs_match_ignores_keys_absent_from_stored():
    snap = _snapshot(params={"steps": 20, "seed": 7, "extra": "live-only"})
    assert configs_match(snap, "sdxl_t2i", {"steps": 20, "seed": 7}) is True


def test_configs_match_false_when_stored_key_missing_from_snapshot():
    snap = _snapshot(params={"steps": 20})
    assert configs_match(snap, "sdxl_t2i", {"steps": 20, "seed": 7}) is False


def test_configs_match_tolerates_float_round_tripping():
    snap = _snapshot(params={"cfg": 0.3})
    assert configs_match(snap, "sdxl_t2i", {"cfg": 0.1 + 0.2}) is True


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


def test_randomize_seeds_replaces_only_named_keys():
    params = {"seed": 7, "noise_seed": 8, "steps": 20, "positive_prompt": "a cat"}
    out = randomize_seeds(params, ["seed", "noise_seed"])
    assert out["steps"] == 20
    assert out["positive_prompt"] == "a cat"
    assert out["seed"] != 7
    assert out["noise_seed"] != 8
    assert 0 <= out["seed"] <= (1 << 63) - 1
    assert 0 <= out["noise_seed"] <= (1 << 63) - 1


def test_randomize_seeds_does_not_mutate_input():
    params = {"seed": 7, "steps": 20}
    out = randomize_seeds(params, ["seed"])
    assert params["seed"] == 7  # original untouched
    assert out is not params


def test_randomize_seeds_sets_missing_seed_keys():
    # A workflow's seed key absent from a sparse row is still given a value so
    # the rebuilt payload has a seed to use.
    out = randomize_seeds({"steps": 20}, ["seed"])
    assert "seed" in out and isinstance(out["seed"], int)


def test_find_duplicate_returns_matching_completed_generation():
    rows = [_row(params={"steps": 20, "seed": 7})]
    snap = _snapshot(params={"steps": 20, "seed": 7})
    assert find_duplicate_generation(rows, snap) is rows[0]


def test_find_duplicate_none_when_seed_is_random():
    # A randomized seed never reproduces a past run, so never a duplicate.
    rows = [_row(params={"steps": 20, "seed": 7})]
    snap = _snapshot(params={"steps": 20, "seed": 7}, seed_is_random=True)
    assert find_duplicate_generation(rows, snap) is None


def test_find_duplicate_none_when_no_row_matches():
    rows = [_row(params={"steps": 20, "seed": 7})]
    snap = _snapshot(params={"steps": 20, "seed": 8})  # different seed
    assert find_duplicate_generation(rows, snap) is None


def test_find_duplicate_ignores_non_completed_rows():
    # A failed/running attempt with the same config is a retry, not a duplicate.
    params = {"steps": 20, "seed": 7}
    rows = [
        _row(params=params, status="error"),
        _row(params=params, status="running"),
    ]
    snap = _snapshot(params=params)
    assert find_duplicate_generation(rows, snap) is None


def test_find_duplicate_picks_the_matching_row_among_several():
    other = _row(params={"steps": 20, "seed": 1})
    different_workflow = _row(workflow="wan22_i2v", params={"steps": 20, "seed": 7})
    match = _row(params={"steps": 20, "seed": 7})
    snap = _snapshot(params={"steps": 20, "seed": 7})
    assert find_duplicate_generation([other, different_workflow, match], snap) is match
