from __future__ import annotations

import json
import random

from origenerator.experiments import policy as policy_module
from origenerator.experiments.policy import ExperimentPolicy
from origenerator.workflows.base import ParamDef, WorkflowTemplate


class FakeWorkflow(WorkflowTemplate):
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
            ParamDef("sampler_name", "Sampler", "dropdown", "euler",
                     options=["euler", "dpmpp_2m", "uni_pc"]),
        ]

    def build_api_payload(self, params: dict) -> dict:
        return {}


class FakeI2vWorkflow(FakeWorkflow):
    name = "fake_i2v"
    output_type = "video"
    lora_keys = ("lora_name",)
    derives_size_from_input = True

    def default_params(self) -> dict:
        return {**super().default_params(), "input_image": "",
                "lora_name": "style_a.safetensors", "lora_strength": 1.0}

    def param_definitions(self) -> list:
        return [*super().param_definitions(), ParamDef("input_image", "Input Image", "image", ""), ParamDef("lora_name", "LoRA", "dropdown", "style_a.safetensors", options=["None", "style_a.safetensors", "style_b.safetensors"]), ParamDef("lora_strength", "LoRA Strength", "float", 1.0, min_val=0.0, max_val=2.0, step=0.05)]


REGISTRY = {FakeWorkflow.name: FakeWorkflow(), FakeI2vWorkflow.name: FakeI2vWorkflow()}


def make_row(prompt_id, **given):
    positive_prompt = given.get("positive_prompt", "a cat")
    all_params = {"positive_prompt": positive_prompt, "negative_prompt": "",
                  "seed": 1, "steps": 20, "sampler_name": "euler"}
    all_params.update(given.get("params") or {})
    return {
        "prompt_id": prompt_id,
        "workflow_name": given.get("workflow_name", "fake_t2i"),
        "status": given.get("status", "completed"),
        "source": given.get("source", "generated"),
        "params_json": json.dumps(all_params),
        "output_files": (json.dumps([{"filename": f"{prompt_id}.png"}])
                         if given.get("output", True) else None),
        "starred": 1 if given.get("favorite") else 0,
        "experiment_verdict": given.get("verdict"),
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


def test_machinery_is_never_an_experiment_base_whatever_it_is_called():
    machinery = FakeWorkflow()
    machinery.name = "machine_only"
    machinery.selectable = False
    policy = ExperimentPolicy(
        registry={**REGISTRY, "machine_only": machinery}, rng=random.Random(0))

    only_machinery = [make_row("m-1", workflow_name="machine_only")]

    assert policy.propose(only_machinery) is None, \
        "varying an enhancement only enhances again an image that exists"
    assert policy.propose([*only_machinery, make_row("ok-1")]).base_prompt_id == "ok-1"


def test_mutated_values_respect_the_dimension_contract():
    base = make_row("base-1")
    policy = make_policy(seed=3)
    for _ in range(200):
        proposal = policy.propose([base])
        steps = proposal.params["steps"]
        assert isinstance(steps, int)
        assert 1 <= steps <= 50
        assert proposal.params["sampler_name"] in ("euler", "dpmpp_2m", "uni_pc")


def test_favorite_bases_are_favored():
    rows = [make_row("plain-1"), make_row("starred-1", favorite=True)]
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
    assert crossed
    assert crossed <= {"a cat", "a dog"}


def test_down_voted_values_are_sampled_less_than_up_voted_ones():
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
    base = make_row("base-1")
    policy = make_policy(seed=8)
    for _ in range(300):
        proposal = policy.propose([base])
        assert "batch_size" not in proposal.mutated_keys, (
            "a bigger batch repeats the same settings, exploring nothing at many times the cost")
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
    rows = [
        make_row("vetted", source="experiment", verdict="up"),
        make_row("unvetted", source="experiment", verdict=None),
    ]
    policy = make_policy(seed=6)
    for _ in range(100):
        assert policy.propose(rows).base_prompt_id == "vetted"


def test_video_bases_dominate_even_an_image_heavy_gallery():
    rows = [make_row(f"img-{i}") for i in range(40)]
    rows += [make_row(f"vid-{i}", workflow_name="fake_i2v",
                      params={"input_image": "frame.png [output]"}) for i in range(2)]
    policy = make_policy(seed=9)
    picked = [policy.propose(rows).workflow.name for _ in range(300)]
    video_share = picked.count("fake_i2v") / len(picked)
    assert video_share < 1, "images keep the smaller share of the proposals"
    assert video_share > 0.6, (
        "a gallery holds many images per video, so a weight on each video base would be swamped; "
        "a share of the proposals is not")


def test_lora_dims_are_the_favorite_mutation(monkeypatch):
    rows = [make_row("vid-1", workflow_name="fake_i2v",
                     params={"input_image": "frame.png [output]"})]

    def lora_share():
        policy = make_policy(seed=10)
        mutated = []
        for _ in range(400):
            mutated.extend(policy.propose(rows).mutated_keys)
        return sum(1 for key in mutated if "lora" in key) / len(mutated)

    favoured = lora_share()
    monkeypatch.setattr(policy_module, "_LORA_DIM_WEIGHT", 1.0)
    even = lora_share()

    assert favoured > even + 0.15, "a LoRA and its strength are what the user most wants explored"


def test_video_experiments_keep_their_start_frame():
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


def test_a_verdict_on_a_number_counts_for_the_numbers_near_it_and_not_for_one_far_off():
    steps = FakeWorkflow().param_definitions()[3]
    bucket = ExperimentPolicy._bucket

    assert bucket(20, steps) == bucket(21.4, steps)
    assert bucket(20, steps) != bucket(45, steps)


def test_a_verdict_on_a_dropdown_value_counts_for_exactly_that_value():
    sampler = FakeWorkflow().param_definitions()[5]

    assert ExperimentPolicy._bucket("uni_pc", sampler) == "uni_pc"
    assert ExperimentPolicy._bucket("euler", sampler) != ExperimentPolicy._bucket("uni_pc", sampler)


def test_proposal_mutates_declared_dims_and_rerolls_the_seed():
    base = make_row("base-1", params={"seed": 777})
    base_params = json.loads(base["params_json"])
    policy = make_policy()
    for _ in range(50):
        proposal = policy.propose([base])
        assert proposal.workflow.name == "fake_t2i"
        assert proposal.base_prompt_id == "base-1"
        assert proposal.params["seed"] != 777
        assert proposal.mutated_keys, "a proposal that changes nothing but its seed teaches nothing"
        for key in proposal.mutated_keys:
            assert proposal.params[key] != base_params[key]
        untouched = set(base_params) - set(proposal.mutated_keys) - {"seed"}
        for key in untouched:
            assert proposal.params[key] == base_params[key]


def test_an_experiment_leaves_a_videos_size_to_the_image_it_animates():
    base = make_row("v1", workflow_name="fake_i2v",
                    params={"input_image": "face.png", "width": 720, "height": 544})
    policy = ExperimentPolicy(REGISTRY, random.Random(0))

    proposal = policy.propose([base])

    assert "width" not in proposal.params
    assert "height" not in proposal.params


class FakeTwoLoraWorkflow(FakeWorkflow):
    name = "fake_two_lora_t2i"
    lora_keys = ("lora", "lora_2")

    def default_params(self) -> dict:
        return {**super().default_params(), "lora": "style_a.safetensors", "lora_strength": 1.0,
                "lora_2": "None", "lora_strength_2": 1.0}

    def param_definitions(self) -> list:
        loras = ["None", "style_a.safetensors", "style_b.safetensors"]
        return [*super().param_definitions(), ParamDef("lora", "LoRA 1", "dropdown", "style_a.safetensors", options=loras), ParamDef("lora_strength", "LoRA Strength 1", "float", 1.0, min_val=0.0, max_val=2.0, step=0.05), ParamDef("lora_2", "LoRA 2", "dropdown", "None", options=loras), ParamDef("lora_strength_2", "LoRA Strength 2", "float", 1.0, min_val=0.0, max_val=2.0, step=0.05)]


def test_an_experiment_never_turns_the_strength_of_a_lora_left_on_none():
    workflow = FakeTwoLoraWorkflow()
    base = make_row("two-loras", workflow_name=workflow.name,
                    params={"lora": "style_a.safetensors", "lora_strength": 1.0,
                            "lora_2": "None", "lora_strength_2": 1.0})
    policy = ExperimentPolicy(registry={workflow.name: workflow}, rng=random.Random(4))

    proposals = [policy.propose([base]) for _ in range(300)]

    assert any("lora_strength" in p.mutated_keys for p in proposals)
    assert all(p.params["lora_2"] != "None" for p in proposals
               if "lora_strength_2" in p.mutated_keys)


class FakeFollowingLoraWorkflow(FakeWorkflow):
    name = "fake_following_lora_t2i"
    lora_keys = ("lora",)

    def default_params(self) -> dict:
        return {**super().default_params(), "unet": "raw_model.safetensors", "lora": "None",
                "lora_strength": 1.0}

    def param_definitions(self) -> list:
        return [
            *super().param_definitions(),
            ParamDef("unet", "Model", "dropdown", "raw_model.safetensors",
                     options=["raw_model.safetensors", "turbo_model.safetensors"]),
            ParamDef("lora", "LoRA", "dropdown", "None", beside_model="unet",
                     options=["None", "speed_up.safetensors", "a_look.safetensors"]),
            ParamDef("lora_strength", "LoRA Strength", "float", 1.0,
                     min_val=0.0, max_val=2.0, step=0.05),
        ]


def test_an_experiment_never_pairs_a_lora_with_a_model_it_is_filed_apart_from(
        recorded_base_models):
    recorded_base_models({"raw_model": "Krea 2", "turbo_model": "Krea 2 Turbo",
                          "speed_up": "Krea 2 Raw"})
    workflow = FakeFollowingLoraWorkflow()
    bases = [make_row("on-raw", workflow_name=workflow.name,
                      params={"unet": "raw_model.safetensors", "lora": "speed_up.safetensors"}),
             make_row("on-turbo", workflow_name=workflow.name,
                      params={"unet": "turbo_model.safetensors", "lora": "None"})]
    policy = ExperimentPolicy(registry={workflow.name: workflow}, rng=random.Random(4))

    proposals = [policy.propose(bases) for _ in range(300)]

    assert any("unet" in p.mutated_keys for p in proposals)
    assert any("lora" in p.mutated_keys for p in proposals)
    assert not [p for p in proposals if (p.params["unet"], p.params["lora"]) == (
        "turbo_model.safetensors", "speed_up.safetensors")]
