from __future__ import annotations

import logging

import pytest

from origenerator import config, request_settings
from origenerator.box_breaks import BOX_BREAK
from origenerator.collection_notes import CollectionNotes
from origenerator.prompt_edit import (
    ADD,
    ADDED,
    ALLOWED,
    DROPPED,
    EXCLUDED,
    PUSHED,
    RAISED,
    REMOVE,
    REWRITTEN,
    WhatIsKnown,
    apply_request,
    apply_request_to_each_scene,
    ask_the_model,
    build_request_messages,
    parse_request,
    prompts_touching,
    work_out,
)
from origenerator.workflows.base import ParamDef, ParamType, story_of


@pytest.mark.parametrize(("request_text", "polarity", "term"), [
    ("no silver earrings", REMOVE, "silver earrings"),
    ("without a hat", REMOVE, "hat"),
    ("remove her sunglasses", REMOVE, "sunglasses"),
    ("get rid of the umbrella", REMOVE, "umbrella"),
    ("more freckles", ADD, "freckles"),
    ("add a red coat", ADD, "red coat"),
    ("give her braided hair", ADD, "braided hair"),
    ("can you please remove the hat, thanks", REMOVE, "hat"),
    ("don't give her a hat", REMOVE, "hat"),
    ("dont give her a hat", REMOVE, "hat"),
])
def test_a_spoken_request_reads_as_a_polarity_and_a_term(request_text, polarity, term):
    assert parse_request(request_text) == (polarity, term)


def test_naming_a_thing_is_asking_for_it():
    assert parse_request("golden hour light") == (ADD, "golden hour light")


def test_the_first_wish_word_decides():
    assert parse_request("no more silver earrings") == (REMOVE, "silver earrings")


def test_a_request_naming_nothing_reads_as_nothing():
    assert parse_request("no, please") is None
    assert parse_request("") is None


def test_the_term_keeps_its_own_casing():
    assert parse_request("add a Dutch angle") == (ADD, "Dutch angle")



def test_against_something_in_the_positive_prompt_takes_it_out():
    revision = apply_request("a woman, silver earrings, soft light", "blurry",
                             "no silver earrings")

    assert revision.positive == "a woman, soft light"
    assert revision.negative == "blurry"
    assert revision.action == DROPPED


def test_a_prompt_in_boxes_is_asked_of_read_whole():
    revision = apply_request(f"a woman, silver earrings,{BOX_BREAK}soft light",
                             f"blurry,{BOX_BREAK}dim", "no silver earrings")

    assert (revision.old_positive, revision.positive, revision.negative) == (
        "a woman, silver earrings, soft light", "a woman, soft light", "blurry, dim")


def test_against_something_in_neither_prompt_puts_it_in_the_negative():
    revision = apply_request("a woman, soft light", "blurry", "no silver earrings")

    assert revision.positive == "a woman, soft light"
    assert revision.negative == "blurry, silver earrings"
    assert revision.action == EXCLUDED


def test_against_something_already_excluded_leans_on_it_harder():
    revision = apply_request("a woman", "blurry, silver earrings",
                             "no silver earrings")

    assert revision.negative == "blurry, (silver earrings:1.1)"
    assert revision.action == PUSHED


def test_a_second_push_climbs_from_the_weight_already_there():
    revision = apply_request("a woman", "(freckles:1.2)", "no freckles")

    assert revision.negative == "(freckles:1.3)"


def test_for_something_already_wanted_raises_its_weight():
    revision = apply_request("a woman, freckles, soft light", "", "more freckles")

    assert revision.positive == "a woman, (freckles:1.1), soft light"
    assert revision.action == RAISED


def test_for_something_in_neither_prompt_adds_it():
    revision = apply_request("a woman, soft light", "blurry", "more freckles")

    assert revision.positive == "a woman, soft light, freckles"
    assert revision.action == ADDED


def test_for_something_being_excluded_stops_excluding_it():
    revision = apply_request("a woman", "blurry, freckles", "more freckles")

    assert revision.negative == "blurry"
    assert revision.positive == "a woman"
    assert revision.action == ALLOWED


def test_a_bracketed_weight_is_read_and_rewritten_explicitly():
    revision = apply_request("a woman, (freckles)", "", "more freckles")

    assert revision.positive == "a woman, (freckles:1.2)"


def test_the_segment_is_the_unit_a_request_acts_on():
    revision = apply_request("a woman, small silver earrings, soft light", "",
                             "no silver earrings")

    assert revision.positive == "a woman, soft light"


def test_a_comma_inside_a_weighted_group_does_not_split_a_segment():
    revision = apply_request("(a woman, seated:1.2), freckles", "", "no freckles")

    assert revision.positive == "(a woman, seated:1.2)"


def test_dropping_the_only_term_leaves_an_empty_prompt():
    revision = apply_request("silver earrings", "", "no silver earrings")

    assert revision.positive == ""
    assert revision.changed


def test_a_request_naming_nothing_yields_no_revision():
    assert apply_request("a woman", "", "no, please") is None
    assert apply_request_to_each_scene(story_of(["a dog", "a cat"]), "", "no, please") is None


def test_a_revision_carries_the_prompts_it_started_from():
    revision = apply_request("a woman, freckles", "blurry", "no freckles")

    assert revision.old_positive == "a woman, freckles"
    assert revision.old_negative == "blurry"
    assert revision.changed
    assert revision.answer == ""


def test_the_rules_take_a_phrase_that_says_more_than_the_term_out_whole():
    revision = apply_request("a woman wearing a straw hat, freckles", "", "no hat")

    assert revision.positive == "freckles"
    assert revision.action == DROPPED



def test_a_prompt_that_tells_no_story_is_asked_of_as_one_however_many_lines_of_dashes_it_holds():
    revision = apply_request(story_of(["a dog running", "a dog asleep"]), "blurry", "grass")

    assert revision.positive == story_of(["a dog running", "a dog asleep, grass"])


def test_a_wish_for_something_new_reaches_every_scene_of_a_story():
    revision = apply_request_to_each_scene(story_of(["a dog running", "a dog asleep"]), "blurry",
                             "more grass")

    assert revision.positive == story_of(["a dog running, grass", "a dog asleep, grass"])


def test_each_scene_answers_a_request_against_something_by_its_own_prompts():
    revision = apply_request_to_each_scene(story_of(["a woman, beach", "a woman, sea"]), "blurry",
                             "no beach")

    assert revision.positive == story_of(["a woman", "a woman, sea"])
    assert revision.negative == story_of(["blurry", "blurry, beach"])


def test_a_negative_every_scene_shares_stays_one_while_the_scenes_change_it_alike():
    revision = apply_request_to_each_scene(story_of(["a dog running", "a dog asleep"]), "blurry", "no hat")

    assert revision.negative == "blurry, hat"


def test_a_storys_revision_names_each_rule_its_scenes_used_once():
    revision = apply_request_to_each_scene(story_of(["a woman, beach", "a woman, sea", "beach, dusk"]),
                             "blurry", "no beach")

    assert revision.action == f"{DROPPED}, {EXCLUDED}"




NOTES = CollectionNotes(prompt_count=5, batches=1, batch_notes=["one note"],
                        patterns="comma-separated parts, a subject first")
EXCHANGE = [("a hat", 'Added "a straw hat" to the Positive Prompt.'),
            ("make it red", 'Replaced "a straw hat" with "a red straw hat" in the Positive Prompt.')]


def _replace(old: str, new: str, *, for_: str, prompt: str = "positive") -> dict:
    return {"prompt": prompt, "replace": old, "with": new, "for": for_}


def _add(words: str, *, for_: str, prompt: str = "positive", after: str = "") -> dict:
    return {"prompt": prompt, "add": words, "after": after, "for": for_}


def _remove(words: str, *, for_: str, prompt: str = "positive") -> dict:
    return {"prompt": prompt, "remove": words, "for": for_}


def _answer(*changes) -> dict:
    return {"changes": list(changes)}


class _Model:
    def __init__(self, *answers):
        self.answers = list(answers)
        self.asked = []

    def __call__(self, positive, negative, request, known):
        self.asked.append((positive, negative, request, known.exchange, known.notes))
        self.examples = known.examples
        self.settings = known.settings
        answer = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if isinstance(answer, Exception):
            raise answer
        return answer


def test_the_model_is_asked_first_with_the_prompts_the_exchange_and_the_notes():
    model = _Model(_answer(_replace("a woman", "two women", for_="two women")))

    revision = work_out("a woman on a couch", "blurry", "two women", exchange=EXCHANGE,
                        notes=NOTES, ask=model)

    assert model.asked == [("a woman on a couch", "blurry", "two women", EXCHANGE, NOTES)]
    assert (revision.positive, revision.negative) == ("two women on a couch", "blurry")
    assert revision.answer == 'Replaced "a woman" with "two women" in the Positive Prompt.'
    assert revision.action == REWRITTEN
    assert revision.changed


def test_his_prompts_that_touch_the_request_go_to_the_model_with_the_rest():
    model = _Model(_answer(_add("a dog, wagging tail", for_="a dog", after="a woman")))

    work_out("a woman", "blurry", "add a dog", examples=("a dog, wagging tail",), ask=model)

    assert model.examples == ("a dog, wagging tail",)


def test_a_term_the_rules_are_sure_of_still_goes_to_the_model_which_knows_the_collection():
    model = _Model(_answer(_remove("a hat", for_="no hat"), _add("hat", for_="no hat", prompt="negative")))

    revision = work_out("a woman, a hat, soft light", "blurry", "no hat", ask=model)

    assert len(model.asked) == 1
    assert (revision.positive, revision.negative) == ("a woman, soft light", "blurry, hat")
    assert revision.answer == ('Removed "a hat" from the Positive Prompt. Added "hat" to the '
                               "Negative Prompt.")


def test_a_model_that_cannot_be_asked_leaves_the_rules_own_edit_and_nothing_said(caplog):
    with caplog.at_level(logging.WARNING, logger="origenerator.prompt_edit"):
        revision = work_out("a woman, soft light", "blurry", "freckles",
                            ask=_Model(OSError("the model is down")))

    assert revision.positive == "a woman, soft light, freckles"
    assert revision.action == ADDED
    assert revision.answer == ""
    assert caplog.messages == ["prompt_edit: the model could not answer the request (OSError)"]


def test_an_answer_that_is_no_list_of_changes_leaves_the_rules_own_edit():
    revision = work_out("a woman wearing a straw hat, freckles", "", "no hat",
                        ask=_Model("a woman, freckles"))

    assert revision.positive == "freckles"
    assert revision.action == DROPPED


def test_a_model_that_changes_nothing_says_so_and_there_is_nothing_to_make():
    revision = work_out("a woman, freckles", "", "more freckles", ask=_Model(_answer()))

    assert not revision.changed
    assert revision.answer == "Nothing changed."


def test_a_model_that_gives_up_says_what_the_prompts_already_had():
    gave_up = {"changes": [], "tried": {"positive": "freckles", "negative": "clear skin",
                                        "for": "more freckles"}}

    revision = work_out("a woman, freckles", "blurry, clear skin", "more freckles", ask=_Model(gave_up))

    assert not revision.changed
    assert revision.answer == ('"freckles" was already in the Positive Prompt, and its opposite already '
                               "in the Negative Prompt, so I couldn't figure out anything else to do.")


def test_a_change_answering_none_of_his_words_is_left_out_without_a_word():
    model = _Model(_answer(_replace("natural makeup", "heavy makeup", for_="glamour"),
                           _add("soft light", for_="more light")))

    revision = work_out("a woman, natural makeup, beach", "blurry", "more light", ask=model)

    assert revision.positive == "a woman, natural makeup, beach, soft light"
    assert revision.answer == 'Added "soft light" to the Positive Prompt.'


def test_his_earlier_requests_count_as_his_words_too():
    model = _Model(_answer(_replace("a hat", "a straw hat", for_="a hat")))

    revision = work_out("a woman, a hat", "", "no, the straw one", exchange=EXCHANGE, ask=model)

    assert revision.positive == "a woman, a straw hat"


def test_a_term_the_model_weights_at_nothing_is_taken_out():
    revision = work_out("a woman, natural makeup, beach", "blurry", "no makeup",
                        ask=_Model(_answer(_replace("natural makeup", "(makeup:0.0)", for_="makeup"),
                                           _replace("blurry", "blurry, (glare:0)", for_="makeup",
                                                    prompt="negative"))))

    assert (revision.positive, revision.negative) == ("a woman, beach", "blurry")


def test_a_synonym_is_the_models_to_find_and_without_it_the_words_stand_alone():
    with_model = work_out("a woman, silver ear studs, soft light", "blurry", "no earrings",
                          ask=_Model(_answer(_remove("silver ear studs", for_="no earrings"))))
    without = work_out("a woman, silver ear studs, soft light", "blurry", "no earrings",
                       ask=_Model(OSError("down")))

    assert with_model.positive == "a woman, soft light"
    assert (without.negative, without.action) == ("blurry, earrings", EXCLUDED)


def test_a_request_naming_nothing_asks_the_model_nothing_and_yields_no_revision():
    model = _Model(_answer())

    assert work_out("a woman", "", "no, please", ask=model) is None
    assert model.asked == []


def test_the_model_rewrites_each_scene_from_that_scenes_own_prompts():
    model = _Model(_answer(_replace("a man", "two men", for_="two men")),
                   _answer(_replace("a man", "two men", for_="two men")))

    revision = work_out(story_of(["a man reading", "a man asleep"]), "blurry", "two men",
                        exchange=EXCHANGE, notes=NOTES, in_scenes=True, ask=model)

    assert [(positive, negative, request) for positive, negative, request, *_ in model.asked] == [
        ("a man reading", "blurry", "two men"), ("a man asleep", "blurry", "two men")]
    assert revision.positive == story_of(["two men reading", "two men asleep"])
    assert revision.answer == 'Replaced "a man" with "two men" in the Positive Prompt.'


def test_a_storys_scenes_answered_differently_are_answered_scene_by_scene():
    model = _Model(_answer(_add("grass", for_="grass", after="a dog")),
                   _answer(_add("green grass", for_="grass", after="a cat")))

    revision = work_out(story_of(["a dog", "a cat"]), "blurry", "grass", in_scenes=True, ask=model)

    assert revision.positive == story_of(["a dog, grass", "a cat, green grass"])
    assert revision.answer == ('Added "grass" to the Positive Prompt. Added "green grass" to the '
                               "Positive Prompt.")


def test_a_story_the_model_answered_only_in_part_is_left_to_the_rules():
    model = _Model(_answer(_replace("a man", "two men", for_="two men")), OSError("down"))

    revision = work_out(story_of(["a man reading", "a man asleep"]), "blurry", "two men",
                        in_scenes=True, ask=model)

    assert revision.positive == story_of(["a man reading, two men", "a man asleep, two men"])
    assert revision.answer == ""


def test_a_prompt_that_tells_no_story_is_asked_of_the_model_whole():
    model = _Model(_answer())
    prompt = story_of(["a man reading", "a man asleep"])

    work_out(prompt, "blurry", "two men", ask=model)

    assert [asked[0] for asked in model.asked] == [prompt]


def test_the_model_reads_a_prompt_with_no_box_marks_in_it():
    model = _Model(_answer(_add("a hat", for_="a hat")))

    revision = work_out(f"a woman,{BOX_BREAK}soft light", "blurry", "a hat", ask=model)

    assert model.asked[0][0] == "a woman, soft light"
    assert revision.old_positive == "a woman, soft light"
    assert revision.positive == "a woman, soft light, a hat"


HIS_PROMPTS = [
    "a woman in a yellow raincoat on a pier at noon, photo",
    "a dog on a park bench, wagging tail, autumn leaves",
    "two dogs chasing a stick, wagging tails, a park bench in the back",
    "a cat asleep on a windowsill, soft light",
]


def test_the_prompts_sharing_the_most_of_the_requests_words_come_first_and_the_rest_not_at_all():
    assert prompts_touching("add a dog on a bench", HIS_PROMPTS) == [
        "a dog on a park bench, wagging tail, autumn leaves",
        "two dogs chasing a stick, wagging tails, a park bench in the back",
    ]


def test_the_words_of_a_request_that_name_nothing_touch_no_prompt():
    assert prompts_touching("make it more", HIS_PROMPTS) == []
    assert prompts_touching("she gives him the stick", HIS_PROMPTS) == [
        "two dogs chasing a stick, wagging tails, a park bench in the back"]


@pytest.mark.parametrize("request_text", ["a dog chased, tails", "dogs chase, a tail"])
def test_a_word_touches_its_plural_and_its_verb_forms(request_text):
    assert prompts_touching(request_text, HIS_PROMPTS) == [
        "two dogs chasing a stick, wagging tails, a park bench in the back",
        "a dog on a park bench, wagging tail, autumn leaves",
    ]


def test_a_word_said_twice_in_a_request_counts_once():
    assert prompts_touching("a dog, a dog on a bench", HIS_PROMPTS) == [
        "a dog on a park bench, wagging tail, autumn leaves",
        "two dogs chasing a stick, wagging tails, a park bench in the back",
    ]


def test_the_prompts_handed_over_stop_at_the_limit_and_at_the_characters_allowed():
    assert prompts_touching("a dog", HIS_PROMPTS, limit=1) == [
        "a dog on a park bench, wagging tail, autumn leaves"]
    assert prompts_touching("a dog", HIS_PROMPTS, limit_chars=60) == [
        "a dog on a park bench, wagging tail, autumn leaves"]
    assert prompts_touching("a dog", HIS_PROMPTS, limit_chars=10) == []




def test_the_request_messages_carry_the_notes_the_exchange_as_turns_the_prompts_and_the_request():
    messages = build_request_messages("a woman, tan", "blurry", "no tan lines",
                                      WhatIsKnown(EXCHANGE, NOTES), "SYSTEM")

    assert messages[0] == {"role": "system", "content": "SYSTEM"}
    assert messages[1:5] == [
        {"role": "user", "content": "a hat"},
        {"role": "assistant", "content": 'Added "a straw hat" to the Positive Prompt.'},
        {"role": "user", "content": "make it red"},
        {"role": "assistant",
         "content": 'Replaced "a straw hat" with "a red straw hat" in the Positive Prompt.'}]
    content = messages[5]["content"]
    assert content.index("comma-separated parts") < content.index("a woman, tan") < content.index(
        "blurry") < content.index("no tan lines")
    assert "one note" in content
    assert len(messages) == 6


def test_the_messages_show_his_prompts_that_touch_the_request_numbered_before_the_current_pair():
    content = build_request_messages("a woman", "", "add a dog", WhatIsKnown(examples=(
        "a dog on a park bench, wagging tail", "two dogs, wagging tails")), "S")[-1]["content"]

    heading = "PROMPTS OF HIS THAT TOUCH WHAT HE ASKS FOR"
    assert "carry over the details" in content
    assert content.index(heading) < content.index(
        "1. a dog on a park bench, wagging tail\n2. two dogs, wagging tails") < content.index(
        "CURRENT POSITIVE PROMPT")


def test_without_notes_or_an_exchange_the_messages_say_neither():
    messages = build_request_messages("a woman", "", "no hat", WhatIsKnown(), "S")

    assert len(messages) == 2
    content = messages[1]["content"]
    assert "NOTES" not in content
    assert "PROMPTS OF HIS" not in content
    assert "a woman" in content
    assert "no hat" in content


def test_notes_still_being_taken_are_not_told_yet():
    unfinished = CollectionNotes(prompt_count=5, batches=2, batch_notes=["a note"])

    content = build_request_messages("a woman", "", "no hat", WhatIsKnown(notes=unfinished), "S")[1]["content"]

    assert "a note" not in content


def test_the_answer_asked_for_is_a_list_of_changes_each_naming_his_words():
    content = build_request_messages("a woman, tan", "", "no tan lines", WhatIsKnown(), "S")[1]["content"]

    shape = content.rsplit("\n\n", 1)[1]
    assert shape.startswith('Reply with only a JSON object: {"changes": [...]}.')
    assert "note" not in shape
    assert '"for": "<his words>"' in shape
    assert "thrown away" in shape
    assert shape.endswith('add "tried": {"positive": "<the words for it now in the positive prompt>", '
                          '"negative": "<the words for its opposite now in the negative prompt>", '
                          '"for": "<his words>"}.')
    assert "..." not in content.rsplit("\n\n", 1)[0]


def test_asking_the_model_sends_one_question_that_reads_long_and_leaves_the_model_loaded():
    sent = {}

    def ask(messages, **settings):
        sent["messages"], sent["settings"] = messages, settings
        return {"message": {"content": '{"changes": [{"prompt": "negative", "add": "tan lines", '
                                       '"for": "no tan lines"}]}'}}

    answered = ask_the_model("a woman, tan", "", "no tan lines", WhatIsKnown(EXCHANGE, NOTES), llm=ask)

    assert answered == {"changes": [{"prompt": "negative", "add": "tan lines",
                                     "for": "no tan lines"}]}
    assert "a woman, tan" in sent["messages"][-1]["content"]
    assert sent["settings"]["json_answer"] is True
    assert sent["settings"]["model"] == config.REQUEST_LLM_MODEL != config.LOCAL_LLM_MODEL
    assert sent["settings"]["reads_tokens"] > 16000
    assert sent["settings"]["stays_loaded"] == f"{config.REQUEST_MODEL_STAYS_LOADED_S + 60}s"
    assert "thinks" not in sent["settings"]


def test_asking_the_model_shows_it_his_prompts_that_touch_the_request():
    sent = {}

    def ask(messages, **settings):
        sent["messages"] = messages
        return {"message": {"content": '{"changes": []}'}}

    ask_the_model("a woman", "", "add a dog", WhatIsKnown(examples=("a dog, wagging tail",)), llm=ask)

    assert "1. a dog, wagging tail" in sent["messages"][-1]["content"]


_SETTINGS_TOLD = request_settings.settings_to_tell(
    [ParamDef("lora_strength", "LoRA Strength", ParamType.FLOAT, 0.8, min_val=0.0, max_val=2.0),
     ParamDef("steps", "Steps", ParamType.INT, 50, min_val=1, max_val=200)],
    {"lora_strength": 0.8, "steps": 50})


def test_the_messages_list_the_settings_he_may_change_and_ask_for_them_in_the_answer():
    content = build_request_messages("a woman", "", "stronger lora",
                                     WhatIsKnown(settings=_SETTINGS_TOLD), "S")[1]["content"]

    assert "SETTINGS HE MAY ALSO CHANGE" in content
    assert "LoRA Strength [lora_strength]: 0.8, a number from 0.0 to 2.0" in content
    assert content.index("SETTINGS HE MAY") < content.index("CURRENT POSITIVE PROMPT")
    assert '"setting": "<key>"' in content.rsplit("\n\n", 1)[1]


def test_without_settings_to_tell_the_messages_list_none():
    content = build_request_messages("a woman", "", "no hat", WhatIsKnown(), "S")[1]["content"]

    assert "SETTINGS HE MAY" not in content


def test_a_request_about_a_setting_changes_it_within_its_range_and_leaves_the_prompts():
    model = _Model(_answer({"setting": "lora_strength", "to": "2.5", "for": "stronger lora"}))

    revision = work_out("a woman", "blurry", "stronger lora", settings=_SETTINGS_TOLD, ask=model)

    assert model.settings == _SETTINGS_TOLD
    assert revision.changed
    assert (revision.positive, revision.negative) == ("a woman", "blurry")
    assert revision.settings == (("lora_strength", 2.0),)
    assert revision.setting_changes == (("LoRA Strength", "0.8", "2.0"),)
    assert revision.answer == "Set LoRA Strength to 2.0 (was 0.8)."


def test_a_request_may_change_a_setting_and_the_prompts_in_one_turn():
    model = _Model(_answer({"setting": "steps", "to": 30, "for": "fewer steps"},
                           _add("hat", for_="no hat", prompt="negative")))

    revision = work_out("a woman", "blurry", "fewer steps and no hat", settings=_SETTINGS_TOLD,
                        ask=model)

    assert revision.settings == (("steps", 30),)
    assert revision.negative == "blurry, hat"
    assert revision.answer == ('Set Steps to 30 (was 50). Couldn\'t find "hat" in the Positive '
                               'Prompt. Added "hat" to the Negative Prompt.')


def test_the_model_is_told_when_the_prompts_take_no_weights():
    said = build_request_messages("a woman", "", "more freckles", WhatIsKnown(weights=False),
                                  "S")[1]["content"]
    plain = build_request_messages("a woman", "", "more freckles", WhatIsKnown(), "S")[1]["content"]

    assert "THESE PROMPTS TAKE NO WEIGHTS" in said
    assert "WEIGHTS" not in plain


def test_a_weight_the_model_writes_is_left_out_where_the_prompts_take_none():
    model = _Model(_answer({"prompt": "positive", "replace": "freckles", "with": "(freckles:1.3)",
                            "for": "more freckles"},
                           {"prompt": "positive", "add": "(a red scarf:1.2)", "for": "a red scarf"}))

    revision = work_out("a woman, freckles", "", "more freckles and a red scarf", weights=False,
                        ask=model)

    assert revision.positive == "a woman, freckles, a red scarf"


def test_the_rules_own_edit_writes_no_weight_where_the_prompts_take_none():
    def no_model(*_asked):
        raise RuntimeError("no model here")

    assert apply_request("a woman, freckles", "", "more freckles").positive == "a woman, (freckles:1.1)"
    assert not apply_request("a woman, freckles", "", "more freckles", weights=False).changed
    assert not apply_request("a woman", "hat", "no hat", weights=False).changed
    assert not work_out("a woman, freckles", "", "more freckles", weights=False, ask=no_model).changed
