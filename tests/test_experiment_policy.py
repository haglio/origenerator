import json
import random

from origenerator.experiments.policy import ExperimentPolicy
from origenerator.workflows.base import ParamDef, WorkflowTemplate


class FakeWorkflow(WorkflowTemplate):
    """A minimal registered workflow for policy tests: one numeric dim, one
    combo dim, a prompt, and a seed."""

    name = "fake_t2i"
    version = "v001"
    display_name = "Fake T2I"
    output_type = "image"
    output_node_id = "9"

    def default_params(self) -> dict:
        return {
            "positive_prompt": "",
            "negative_prompt": "",
            "seed": 0,
            "steps": 20,
            "batch_size": 1,
            "sampler_name": "euler",
        }

    def param_definitions(self) -> list:
        return [
            ParamDef("positive_prompt", "Positive Prompt", "str", "", multiline=True),
            ParamDef("negative_prompt", "Negative Prompt", "str", "", multiline=True),
            ParamDef("seed", "Seed", "seed", 0),
            ParamDef("steps", "Steps", "int", 20, min_val=1, max_val=50),
            ParamDef("batch_size", "Batch Size", "int", 1, min_val=1, max_val=8),
            ParamDef("sampler_name", "Sampler", "combo", "euler",
                     options=["euler", "dpmpp_2m", "uni_pc"]),
        ]

    def build_api_payload(self, params: dict) -> dict:
        return {}


class FakeI2vWorkflow(FakeWorkflow):
    """An image-conditioned fake: adds the input_image its video starts from."""

    name = "fake_i2v"
    output_type = "video"

    def default_params(self) -> dict:
        return {**super().default_params(), "input_image": ""}

    def param_definitions(self) -> list:
        return super().param_definitions() + [
            ParamDef("input_image", "Input Image", "image", ""),
        ]


REGISTRY = {FakeWorkflow.name: FakeWorkflow(), FakeI2vWorkflow.name: FakeI2vWorkflow()}


def make_row(prompt_id, *, workflow_name="fake_t2i", status="completed",
             source="generated", params=None, output=True, starred=False,
             verdict=None, positive_prompt="a cat"):
    all_params = {"positive_prompt": positive_prompt, "negative_prompt": "",
                  "seed": 1, "steps": 20, "sampler_name": "euler"}
    all_params.update(params or {})
    return {
        "prompt_id": prompt_id,
        "workflow_name": workflow_name,
        "status": status,
        "source": source,
        "params_json": json.dumps(all_params),
        "output_files": json.dumps([{"filename": f"{prompt_id}.png"}]) if output else None,
        "starred": 1 if starred else 0,
        "experiment_verdict": verdict,
        "positive_prompt": positive_prompt,
        "negative_prompt": "",
        "seed": 1,
    }


def make_policy(seed=0):
    return ExperimentPolicy(registry=REGISTRY, rng=random.Random(seed))


def test_proposes_nothing_with_no_eligible_rows():
    policy = make_policy()
    assert policy.propose([]) is None
    ineligible = [
        make_row("failed", status="error", output=False),
        make_row("unknown-wf", workflow_name="not_registered"),
        make_row("rejected", source="experiment", verdict="down"),
    ]
    assert policy.propose(ineligible) is None


def test_mutated_values_respect_the_dimension_contract():
    base = make_row("base-1")
    policy = make_policy(seed=3)
    for _ in range(200):
        proposal = policy.propose([base])
        steps = proposal.params["steps"]
        assert isinstance(steps, int) and 1 <= steps <= 50
        assert proposal.params["sampler_name"] in ("euler", "dpmpp_2m", "uni_pc")


def test_starred_bases_are_favored():
    rows = [make_row("plain-1"), make_row("starred-1", starred=True)]
    policy = make_policy(seed=1)
    picks = [policy.propose(rows).base_prompt_id for _ in range(300)]
    assert picks.count("starred-1") > picks.count("plain-1")


def test_prompt_crossover_draws_from_sibling_generations():
    rows = [
        make_row("base-1", positive_prompt="a cat"),
        make_row("donor-1", positive_prompt="a dog"),
        make_row("other-wf", workflow_name="not_registered", positive_prompt="a fox"),
    ]
    policy = make_policy(seed=2)
    crossed = set()
    for _ in range(300):
        proposal = policy.propose(rows)
        if "positive_prompt" in proposal.mutated_keys:
            crossed.add(proposal.params["positive_prompt"])
    # Prompts come only from finished siblings of the same workflow — never from
    # another workflow's rows, and never invented from thin air.
    assert crossed and crossed <= {"a cat", "a dog"}


def test_down_voted_values_are_sampled_less_than_up_voted_ones():
    # The user reviewed past experiments: dpmpp_2m keeps winning, uni_pc keeps
    # losing. New proposals should lean the same way.
    rows = [make_row("base-1")]
    rows += [
        make_row(f"exp-up-{i}", source="experiment", verdict="up",
                 params={"sampler_name": "dpmpp_2m"})
        for i in range(5)
    ]
    rows += [
        make_row(f"exp-down-{i}", source="experiment", verdict="down",
                 params={"sampler_name": "uni_pc"})
        for i in range(5)
    ]
    policy = make_policy(seed=4)
    swapped = [
        proposal.params["sampler_name"]
        for proposal in (policy.propose(rows) for _ in range(400))
        if "sampler_name" in proposal.mutated_keys
    ]
    assert swapped.count("dpmpp_2m") > 2 * swapped.count("uni_pc")


def test_batch_size_is_not_an_experiment_dimension():
    # Varying batch size re-runs the same recipe in bulk — it explores nothing
    # and multiplies the GPU bill, so it is never mutated.
    base = make_row("base-1")
    policy = make_policy(seed=8)
    for _ in range(300):
        proposal = policy.propose([base])
        assert "batch_size" not in proposal.mutated_keys
        assert proposal.params["batch_size"] == 1


def test_a_clearly_damned_value_stops_being_proposed():
    rows = [make_row("base-1")]
    rows += [
        make_row(f"exp-down-{i}", source="experiment", verdict="down",
                 params={"sampler_name": "uni_pc"})
        for i in range(5)
    ]
    policy = make_policy(seed=5)
    for _ in range(400):
        proposal = policy.propose(rows)
        assert proposal.params["sampler_name"] != "uni_pc"


def test_unreviewed_experiments_do_not_compound():
    # An unreviewed experiment must not become the base of further experiments —
    # mutations only build on results the user has actually vetted.
    rows = [
        make_row("vetted", source="experiment", verdict="up"),
        make_row("unvetted", source="experiment", verdict=None),
    ]
    policy = make_policy(seed=6)
    for _ in range(100):
        assert policy.propose(rows).base_prompt_id == "vetted"


def test_video_experiments_keep_their_start_frame():
    # An i2v experiment re-runs on the base row's stored frame — the frame is an
    # instance of the recipe, not a dimension to wander. A row with no frame
    # recorded can't be re-run at all, so it is never a base.
    rows = [
        make_row("with-frame", workflow_name="fake_i2v",
                 params={"input_image": "frame.png [output]"}),
        make_row("frameless", workflow_name="fake_i2v"),
    ]
    policy = make_policy(seed=7)
    for _ in range(100):
        proposal = policy.propose(rows)
        assert proposal.base_prompt_id == "with-frame"
        assert proposal.params["input_image"] == "frame.png [output]"
        assert "input_image" not in proposal.mutated_keys


def test_proposal_mutates_declared_dims_and_rerolls_the_seed():
    base = make_row("base-1", params={"seed": 777})
    base_params = json.loads(base["params_json"])
    policy = make_policy()
    for _ in range(50):
        proposal = policy.propose([base])
        assert proposal.workflow.name == "fake_t2i"
        assert proposal.base_prompt_id == "base-1"
        assert proposal.params["seed"] != 777  # a fresh variation, never a re-run
        assert proposal.mutated_keys
        for key in proposal.mutated_keys:
            assert proposal.params[key] != base_params[key]
        untouched = set(base_params) - set(proposal.mutated_keys) - {"seed"}
        for key in untouched:
            assert proposal.params[key] == base_params[key]
