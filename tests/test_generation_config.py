import json

from origenerator.generation_config import (
    ConfigSnapshot,
    configs_match,
    filled_params,
    find_duplicate_generation,
    merge_denormalized,
    prepared_params,
    randomize_seeds,
    would_reproduce_a_completed_run,
)
from origenerator.workflows import WORKFLOW_REGISTRY


def _snapshot(workflow="sdxl_t2i", params=None, seed_is_random=False):
    return ConfigSnapshot(workflow, params or {}, seed_is_random)


def test_config_snapshot_round_trips_through_dict():
    snap = ConfigSnapshot("wan22_i2v", {"input_image": "x.png"}, seed_is_random=True)
    restored = ConfigSnapshot.from_dict(snap.to_dict())
    assert restored.workflow_name == "wan22_i2v"
    assert restored.params == {"input_image": "x.png"}
    assert restored.seed_is_random is True


def test_prepared_params_fills_defaults_and_rerolls_seeds():
    wf = WORKFLOW_REGISTRY["sdxl_t2i"]
    row = {"params_json": json.dumps({"positive_prompt": "a cat", "seed": 5})}
    params = prepared_params(row, wf)
    assert params["positive_prompt"] == "a cat"                       # kept from the row
    assert params["checkpoint"] == wf.default_params()["checkpoint"]  # filled from defaults
    assert params["seed"] != 5                                         # re-rolled


def test_filled_params_fills_defaults_but_keeps_every_seed():
    # The seed-preserving half of prepared_params: sparse row filled from the
    # workflow's defaults, but the stored seeds left exactly as they were.
    wf = WORKFLOW_REGISTRY["wan22_i2v"]
    row = {"params_json": json.dumps({"positive_prompt": "a cat", "seed": 5, "noise_seed": 9})}
    params = filled_params(row, wf)
    assert params["positive_prompt"] == "a cat"            # kept from the row
    assert params["steps"] == wf.default_params()["steps"]  # filled from defaults
    assert params["seed"] == 5                              # both seeds kept, not re-rolled
    assert params["noise_seed"] == 9


def _row(workflow="sdxl_t2i", params=None, status="completed", **extra):
    row = {
        "workflow_name": workflow,
        "status": status,
        "params_json": json.dumps(params or {}),
        # A real completed generation recorded what it produced; only a row that
        # did counts as one already made (see the no-output test below).
        "output_files": json.dumps([{"filename": "out.png", "subfolder": ""}]),
    }
    row.update(extra)
    return row


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


def test_find_duplicate_ignores_a_completed_row_that_produced_nothing():
    # A run canceled mid-flight can land as 'completed' with no output recorded
    # (ComfyUI ends an interrupted prompt the same way it ends a finished one).
    # The video it would have made doesn't exist, so re-running it is a retry —
    # never a duplicate, whatever the row's status says.
    params = {"steps": 20, "seed": 7}
    rows = [
        _row(params=params, output_files=None),
        _row(params=params, output_files="[]"),
        _row(params=params, output_files="not json"),
    ]
    snap = _snapshot(params=params)
    assert find_duplicate_generation(rows, snap) is None


def test_find_duplicate_picks_the_matching_row_among_several():
    other = _row(params={"steps": 20, "seed": 1})
    different_workflow = _row(workflow="wan22_i2v", params={"steps": 20, "seed": 7})
    match = _row(params={"steps": 20, "seed": 7})
    snap = _snapshot(params={"steps": 20, "seed": 7})
    assert find_duplicate_generation([other, different_workflow, match], snap) is match


def test_find_duplicate_none_when_stored_params_are_a_subset():
    # A sparse stored row (e.g. a reused import that recorded only a few fields)
    # must not count as a duplicate of a fuller live config just because the keys
    # it does carry agree — the user changed a field the stored row never had.
    rows = [_row(params={"seed": 7})]
    snap = _snapshot(params={"seed": 7, "steps": 20})
    assert find_duplicate_generation(rows, snap) is None


def test_find_duplicate_ignores_imported_rows():
    # Imports lack our full graph/params and aren't reproducible, so re-running
    # never re-creates one — never a duplicate, even if every recorded field matches.
    rows = [_row(params={"seed": 7, "steps": 20}, source="imported")]
    snap = _snapshot(params={"seed": 7, "steps": 20})
    assert find_duplicate_generation(rows, snap) is None


# --- configs_match: does a form still describe the generation it was seeded from? --

def test_configs_match_when_every_setting_is_the_same():
    assert configs_match(_snapshot(params={"positive_prompt": "a cat", "seed": 5}),
                         _snapshot(params={"positive_prompt": "a cat", "seed": 5}))


def test_configs_differ_on_any_changed_param():
    assert not configs_match(_snapshot(params={"positive_prompt": "a cat"}),
                             _snapshot(params={"positive_prompt": "a dog"}))


def test_configs_differ_on_a_changed_seed():
    # A different seed is a different picture, so it counts as a modification
    # even though it lands the run in the same gallery folder.
    assert not configs_match(_snapshot(params={"seed": 5}),
                             _snapshot(params={"seed": 6}))


def test_configs_differ_on_a_changed_workflow():
    assert not configs_match(_snapshot(workflow="sdxl_t2i", params={"seed": 5}),
                             _snapshot(workflow="wan22_i2v", params={"seed": 5}))


def test_configs_differ_once_the_seed_is_set_to_random():
    # Same seed in the field, but one of them re-rolls it on Generate — so they
    # would not make the same picture.
    assert not configs_match(_snapshot(params={"seed": 5}),
                             _snapshot(params={"seed": 5}, seed_is_random=True))


def test_configs_differ_when_one_carries_a_param_the_other_lacks():
    assert not configs_match(_snapshot(params={"seed": 5}),
                             _snapshot(params={"seed": 5, "steps": 20}))


def test_configs_match_across_int_and_float_spellings_of_a_number():
    # A form reads 1.5 back as a float where a stored row may hold it as an int;
    # equal values are equal settings.
    assert configs_match(_snapshot(params={"cfg": 8}), _snapshot(params={"cfg": 8.0}))


def test_would_reproduce_fills_defaults_before_comparing():
    # The one question both the gallery's launch and the Generate button's caption
    # ask. A caller carrying only the fields it edited must still match a stored
    # row, which holds every param — so the defaults are filled in first.
    wf = WORKFLOW_REGISTRY["sdxl_t2i"]
    rows = [_row(params=dict(wf.default_params(), positive_prompt="a cat", seed=7))]
    assert would_reproduce_a_completed_run(
        rows, wf, {"positive_prompt": "a cat", "seed": 7}) is True


def test_would_reproduce_is_false_while_the_seed_is_random():
    # The same settings under a Random seed reproduce nothing, so the button that
    # would offer a fresh seed has nothing to offer — it just reads "Generate".
    wf = WORKFLOW_REGISTRY["sdxl_t2i"]
    params = dict(wf.default_params(), positive_prompt="a cat", seed=7)
    rows = [_row(params=params)]
    assert would_reproduce_a_completed_run(
        rows, wf, params, seed_is_random=True) is False
