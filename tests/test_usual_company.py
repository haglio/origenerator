from __future__ import annotations

from origenerator.usual_company import UsualCompany, usual_company, usual_writing

_SCENES = ["a fisherman, harbor, fog", "a farmer, a field, dusk", "a sailor, a deck, rain",
           "a child, a beach, noon"]


def _twins(scenes=_SCENES, *, came="a wide straw hat, frayed brim", kept_out="bare head"):
    return [pair for scene in scenes
            for pair in ((scene, "blurry"), (f"{scene}, {came}", f"blurry, {kept_out}"))]


def _is_a_hat(thing: str) -> bool:
    return "hat" in thing


def test_the_things_that_came_with_the_thing_in_prompts_otherwise_alike_are_its_company():
    assert usual_company(_twins(), _is_a_hat) == UsualCompany(
        positive=("a wide straw hat", "frayed brim"), negative=("bare head",))


def test_what_a_prompt_with_the_thing_shares_with_its_twin_is_no_company_of_it():
    same_series = [("a fisherman, harbor, fog, a wide straw hat", "blurry, bare head, grain")] * 3
    without = [("a fisherman, harbor, fog", "blurry, grain"), ("a cat, a sofa", "cartoon")]

    assert usual_company(same_series + without, _is_a_hat) == UsualCompany(
        positive=("a wide straw hat",), negative=("bare head",))


def test_a_prompt_with_the_thing_and_no_prompt_like_it_without_says_nothing():
    unlike = [("a fisherman, harbor, fog, a wide straw hat, frayed brim, nets, gulls, a pier", "")] * 5

    assert usual_company([*unlike, ("a fisherman", "")], _is_a_hat) == UsualCompany()


def test_fewer_than_three_twins_show_no_company():
    assert usual_company(_twins(_SCENES[:2]), _is_a_hat) == UsualCompany()


def test_a_thing_that_came_with_fewer_than_a_third_of_the_twins_is_no_company():
    prompts = (_twins(_SCENES[:3], came="a hat, a red ribbon")
               + _twins(["a cook, a kitchen, steam", "a nurse, a ward, night", "a clerk, a desk, dawn",
                         "a guard, a gate, snow", "a miner, a tunnel, dust", "a baker, an oven, flour",
                         "a pilot, a cockpit, cloud"], came="a hat"))

    assert usual_company(prompts, _is_a_hat).positive == ("a hat",)
    assert usual_company(prompts[:-2], _is_a_hat).positive == ("a hat", "a red ribbon")


def test_each_thing_inside_a_weighted_group_is_a_thing_of_its_own():
    prompts = _twins(came="(a wide straw hat, frayed brim:1.2)", kept_out="((bare head)), (cap:1.3)")

    assert usual_company(prompts, _is_a_hat) == UsualCompany(
        positive=("a wide straw hat", "frayed brim"), negative=("bare head", "cap"))


def test_twins_of_which_one_has_no_negative_prompt_say_nothing_about_what_is_kept_out():
    silent = [(positive, "" if "hat" in positive else negative) for positive, negative in _twins()]

    assert usual_company(silent, _is_a_hat) == UsualCompany(
        positive=("a wide straw hat", "frayed brim"))


def test_only_his_newest_prompts_with_the_thing_say_what_its_company_is():
    older = _twins(came="a felt hat, a feather")
    newer = [("a clerk, a desk, dawn", "blurry")] + [
        ("a clerk, a desk, dawn, a straw hat", "blurry, paper hat")] * 150

    assert usual_company(older + newer, _is_a_hat) == UsualCompany(
        positive=("a straw hat",), negative=("paper hat",))


def test_a_word_that_usually_came_under_several_wordings_brings_its_commonest_wording():
    prompts = [pair for scene, man in zip(_SCENES, ("a tall man", "the tall man", "a tall man",
                                                    "a man"), strict=True)
               for pair in ((scene, ""), (f"{scene}, {man}, a hat", ""))]

    assert usual_company(prompts, _is_a_hat).positive == ("a hat", "a tall man")


def test_a_wording_that_says_more_than_what_usually_came_is_no_wording_to_bring():
    scenes = [f"{who}, {where}, {light}" for who, where, light in zip(
        ("a fisherman", "a farmer", "a sailor", "a child", "a baker", "a nurse", "a judge",
         "a painter", "a pilot", "a clerk"),
        ("harbor", "a field", "a deck", "a beach", "a kitchen", "a ward", "a court", "a loft",
         "a runway", "an office"),
        ("fog", "dusk", "rain", "noon", "dawn", "night", "snow", "haze", "wind", "frost"),
        strict=True)]
    men = (*["two sailors hauling a tall man"] * 3, *["a tall man"] * 3, "an old man",
           "the man beside her", "a kind man", "a quiet man")
    prompts = [pair for scene, man in zip(scenes, men, strict=True)
               for pair in ((scene, ""), (f"{scene}, {man}, a hat", ""))]

    assert usual_company(prompts, _is_a_hat).positive == ("a hat", "a tall man")


def _writing_a_hat(writing: str, times: int, scene: str = "a pier") -> list[tuple[str, str]]:
    return [(f"a man, {writing}, {scene} {number}", "") for number in range(times)]


def test_the_wording_and_weight_his_prompts_most_often_give_a_thing_is_its_usual_writing():
    prompts = [*_writing_a_hat("(a hat:1.2)", 2), *_writing_a_hat("(a Tall Felt hat:1.5)", 3),
               *_writing_a_hat("a tall felt hat", 2)]

    assert usual_writing(prompts, _is_a_hat) == ("a Tall Felt hat", 1.5)


def test_a_writing_fewer_than_three_prompts_share_is_no_usual_writing():
    prompts = [*_writing_a_hat("(a hat:1.2)", 2), *_writing_a_hat("(a tall felt hat:1.5)", 2)]

    assert usual_writing(prompts, _is_a_hat) is None
    assert usual_writing([("a man", "")], _is_a_hat) is None


def test_only_his_newest_thirty_prompts_with_the_thing_say_how_he_writes_it():
    prompts = [*_writing_a_hat("(a hat:1.2)", 40, "a field"),
               *_writing_a_hat("(a tall felt hat:1.5)", 16),
               *_writing_a_hat("(a straw hat:1.3)", 14)]

    assert usual_writing(prompts, _is_a_hat) == ("a tall felt hat", 1.5)
