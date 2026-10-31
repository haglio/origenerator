"""The policy that turns a request into a prompt-pair edit, and the model that
answers it knowing the collection. Every prompt here is invented."""
from __future__ import annotations

import logging

import pytest

from origenerator import local_llm, request_settings
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
    apply_request,
    ask_the_model,
    build_request_messages,
    parse_request,
    prompts_touching,
    work_out,
)
from origenerator.workflows.base import ParamDef, ParamType, story_of

# --- reading the request ----------------------------------------------------


@pytest.mark.parametrize("request_text, polarity, term", [
    ("no silver earrings", REMOVE, "silver earrings"),
    ("without a hat", REMOVE, "hat"),
    ("remove her sunglasses", REMOVE, "sunglasses"),
    ("get rid of the umbrella", REMOVE, "umbrella"),
    ("more freckles", ADD, "freckles"),
    ("add a red coat", ADD, "red coat"),
    ("give her braided hair", ADD, "braided hair"),
    ("can you please remove the hat, thanks", REMOVE, "hat"),
])
def test_a_spoken_request_reads_as_a_polarity_and_a_term(request_text, polarity, term):
    assert parse_request(request_text) == (polarity, term)


def test_naming_a_thing_is_asking_for_it():
    # No wish word at all: the bare noun phrase is a desire for it.
    assert parse_request("golden hour light") == (ADD, "golden hour light")


def test_the_first_wish_word_decides():
    # "no more X" is a request against X, not for more of it.
    assert parse_request("no more silver earrings") == (REMOVE, "silver earrings")


def test_a_request_naming_nothing_reads_as_nothing():
    assert parse_request("no, please") is None
    assert parse_request("") is None


def test_the_term_keeps_its_own_casing():
    assert parse_request("add a Dutch angle") == (ADD, "Dutch angle")


# --- the rules: what a request does to a prompt pair without a model --------


def test_against_something_in_the_positive_prompt_takes_it_out():
    revision = apply_request("a woman, silver earrings, soft light", "blurry",
                             "no silver earrings")

    assert revision.positive == "a woman, soft light"
    assert revision.negative == "blurry"  # untouched: it was enough to drop it
    assert revision.action == DROPPED


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
    # The mirror of dropping it from the positive: the smallest change that
    # answers the request. Asked again it would then be added.
    revision = apply_request("a woman", "blurry, freckles", "more freckles")

    assert revision.negative == "blurry"
    assert revision.positive == "a woman"
    assert revision.action == ALLOWED


def test_a_bracketed_weight_is_read_and_rewritten_explicitly():
    revision = apply_request("a woman, (freckles)", "", "more freckles")

    assert revision.positive == "a woman, (freckles:1.2)"


def test_the_segment_is_the_unit_a_request_acts_on():
    # "small silver earrings" is one thing the image has, so a request about
    # silver earrings takes the whole phrase rather than the two words inside it.
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


def test_a_revision_carries_the_prompts_it_started_from():
    # What the tab marks the prompt's change against, so the record stands alone.
    revision = apply_request("a woman, freckles", "blurry", "no freckles")

    assert revision.old_positive == "a woman, freckles"
    assert revision.old_negative == "blurry"
    assert revision.changed
    assert revision.answer == ""  # the rules say nothing back


def test_the_rules_take_a_phrase_that_says_more_than_the_term_out_whole():
    revision = apply_request("a woman wearing a straw hat, freckles", "", "no hat")

    assert revision.positive == "freckles"
    assert revision.action == DROPPED


# --- a video told in scenes: the story is one prompt per scene ---------------


def test_a_wish_for_something_new_reaches_every_scene_of_a_story():
    revision = apply_request(story_of(["a dog running", "a dog asleep"]), "blurry",
                             "more grass")

    assert revision.positive == story_of(["a dog running, grass", "a dog asleep, grass"])


def test_each_scene_answers_a_request_against_something_by_its_own_prompts():
    revision = apply_request(story_of(["a woman, beach", "a woman, sea"]), "blurry",
                             "no beach")

    assert revision.positive == story_of(["a woman", "a woman, sea"])
    assert revision.negative == story_of(["blurry", "blurry, beach"])


def test_a_negative_every_scene_shares_stays_one_while_the_scenes_change_it_alike():
    revision = apply_request(story_of(["a dog running", "a dog asleep"]), "blurry", "no hat")

    assert revision.negative == "blurry, hat"


def test_a_storys_revision_names_each_rule_its_scenes_used_once():
    revision = apply_request(story_of(["a woman, beach", "a woman, sea", "beach, dusk"]),
                             "blurry", "no beach")

    assert revision.action == f"{DROPPED}, {EXCLUDED}"


# --- the model: every request goes to it first, with the notes and the exchange


NOTES = CollectionNotes(prompt_count=5, batches=1, batch_notes=["one note"],
                        patterns="comma-separated parts, a subject first")
EXCHANGE = [("a hat", "Gave her a straw hat, which your prompts favor at the beach."),
            ("make it red", "The straw hat is red now.")]


class _Model:
    def __init__(self, *answers):
        self.answers = list(answers)
        self.asked = []

    def __call__(self, positive, negative, request, exchange, notes, examples=(),
                 settings=()):
        self.asked.append((positive, negative, request, exchange, notes))
        self.examples = examples
        self.settings = settings
        answer = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if isinstance(answer, Exception):
            raise answer
        return answer


def test_the_model_is_asked_first_with_the_prompts_the_exchange_and_the_notes():
    model = _Model(("two women on a couch", "blurry", "Two women now."))

    revision = work_out("a woman on a couch", "blurry", "two women", exchange=EXCHANGE,
                        notes=NOTES, ask=model)

    assert model.asked == [("a woman on a couch", "blurry", "two women", EXCHANGE, NOTES)]
    assert (revision.positive, revision.negative) == ("two women on a couch", "blurry")
    assert revision.answer == "Two women now."
    assert revision.action == REWRITTEN
    assert revision.changed


def test_his_prompts_that_touch_the_request_go_to_the_model_with_the_rest():
    model = _Model(("a woman, a dog, wagging tail", "blurry", "A dog, tail wagging."))

    work_out("a woman", "blurry", "add a dog", examples=("a dog, wagging tail",), ask=model)

    assert model.examples == ("a dog, wagging tail",)


def test_a_term_the_rules_are_sure_of_still_goes_to_the_model_which_knows_the_collection():
    model = _Model(("a woman, soft light", "blurry", "Took the hat off."))

    revision = work_out("a woman, a hat, soft light", "blurry", "no hat", ask=model)

    assert len(model.asked) == 1
    assert revision.positive == "a woman, soft light"
    assert revision.answer == "Took the hat off."


def test_a_model_that_cannot_be_asked_leaves_the_rules_own_edit_and_nothing_said(caplog):
    with caplog.at_level(logging.WARNING, logger="origenerator.prompt_edit"):
        revision = work_out("a woman, soft light", "blurry", "freckles",
                            ask=_Model(OSError("the model is down")))

    assert revision.positive == "a woman, soft light, freckles"
    assert revision.action == ADDED
    assert revision.answer == ""
    assert caplog.messages == ["prompt_edit: the model could not answer the request (OSError)"]


def test_a_model_that_changes_nothing_and_says_nothing_leaves_the_rules_own_edit():
    revision = work_out("a woman wearing a straw hat, freckles", "", "no hat",
                        ask=_Model(("a woman wearing a straw hat, freckles", "", "")))

    assert revision.positive == "freckles"
    assert revision.action == DROPPED


def test_a_model_that_changes_nothing_but_answers_is_an_answer_with_nothing_to_make():
    revision = work_out("a woman, freckles", "", "more freckles",
                        ask=_Model(("a woman, freckles", "", "The freckles are already there.")))

    assert not revision.changed
    assert revision.answer == "The freckles are already there."


def test_a_term_the_model_weights_at_nothing_is_taken_out():
    revision = work_out("a woman, natural makeup, beach", "blurry", "no makeup",
                        ask=_Model(("a woman, (makeup:0.0), beach", "blurry, (glare:0)", "Done.")))

    assert (revision.positive, revision.negative) == ("a woman, beach", "blurry")


def test_an_answer_that_stands_dots_in_for_a_prompt_leaves_that_prompt_as_it_was():
    revision = work_out("A dog sits on a porch at sunset.", "", "bigger ears",
                        ask=_Model(("A dog with big ears sits on a porch at sunset.", "...",
                                    "Bigger ears.")))

    assert (revision.positive, revision.negative) == (
        "A dog with big ears sits on a porch at sunset.", "")


def test_an_answer_that_leaves_part_of_the_prompt_out_with_dots_is_no_answer():
    revision = work_out("A dog sits on a porch at sunset, warm light", "", "bigger ears",
                        ask=_Model(("A dog with bigger ears ... warm light", "", "Bigger.")))

    assert revision.positive == "A dog sits on a porch at sunset, warm light, bigger ears"
    assert revision.answer == ""


def test_an_answer_with_no_words_for_a_prompt_leaves_that_prompt_as_it_was():
    revision = work_out("a woman", "blurry", "sharper",
                        ask=_Model(("a woman, sharp focus", "", "Sharper.")))

    assert revision.negative == "blurry"


def test_a_synonym_is_the_models_to_find_and_without_it_the_words_stand_alone():
    # "no earrings" over a prompt that says "silver ear studs": the model reads
    # the two as one thing; the rules, which read words, can only exclude it.
    with_model = work_out("a woman, silver ear studs, soft light", "blurry", "no earrings",
                          ask=_Model(("a woman, soft light", "blurry", "Took the studs out.")))
    without = work_out("a woman, silver ear studs, soft light", "blurry", "no earrings",
                       ask=_Model(OSError("down")))

    assert with_model.positive == "a woman, soft light"
    assert (without.negative, without.action) == ("blurry, earrings", EXCLUDED)


def test_a_request_naming_nothing_asks_the_model_nothing_and_yields_no_revision():
    model = _Model(("x", "y", "z"))

    assert work_out("a woman", "", "no, please", ask=model) is None
    assert model.asked == []


def test_the_model_rewrites_each_scene_from_that_scenes_own_prompts():
    model = _Model(("two men reading", "blurry", "Two of them."),
                   ("two men asleep", "blurry", "Two of them."))

    revision = work_out(story_of(["a man reading", "a man asleep"]), "blurry", "two men",
                        exchange=EXCHANGE, notes=NOTES, ask=model)

    assert [(positive, negative, request) for positive, negative, request, *_ in model.asked] == [
        ("a man reading", "blurry", "two men"), ("a man asleep", "blurry", "two men")]
    assert revision.positive == story_of(["two men reading", "two men asleep"])
    assert revision.answer == "Two of them."


def test_a_storys_scenes_answered_differently_are_answered_scene_by_scene():
    model = _Model(("a dog, grass", "blurry", "Grass under the dog."),
                   ("a cat, grass", "blurry", "Grass under the cat."))

    revision = work_out(story_of(["a dog", "a cat"]), "blurry", "grass", ask=model)

    assert revision.answer == "Grass under the dog. Grass under the cat."


def test_a_story_the_model_answered_only_in_part_is_left_to_the_rules():
    model = _Model(("two men reading", "blurry", "Two."), OSError("down"))

    revision = work_out(story_of(["a man reading", "a man asleep"]), "blurry", "two men",
                        ask=model)

    assert revision.positive == story_of(["a man reading, two men", "a man asleep, two men"])
    assert revision.answer == ""


# --- his own prompts that touch the request, shown to the model as examples --


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


# --- what the model is asked, and how its answer is read --------------------


def test_the_request_messages_carry_the_notes_the_exchange_the_prompts_and_the_request():
    messages = build_request_messages("a woman, tan", "blurry", "no tan lines", EXCHANGE, NOTES,
                                      "SYSTEM")

    assert messages[0] == {"role": "system", "content": "SYSTEM"}
    content = messages[1]["content"]
    assert content.index("comma-separated parts") < content.index("a hat") < content.index(
        "The straw hat is red now.") < content.index("a woman, tan") < content.index("blurry")
    assert content.rindex("no tan lines") > content.index("blurry")
    assert "one note" in content


def test_the_messages_show_his_prompts_that_touch_the_request_numbered_before_the_current_pair():
    content = build_request_messages("a woman", "", "add a dog", [], None, "S", examples=(
        "a dog on a park bench, wagging tail", "two dogs, wagging tails"))[1]["content"]

    heading = "PROMPTS OF HIS THAT TOUCH WHAT HE ASKS FOR"
    assert "carry over the details" in content
    assert content.index(heading) < content.index(
        "1. a dog on a park bench, wagging tail\n2. two dogs, wagging tails") < content.index(
        "CURRENT POSITIVE PROMPT")


def test_without_notes_or_an_exchange_the_messages_say_neither():
    content = build_request_messages("a woman", "", "no hat", [], None, "S")[1]["content"]

    assert "NOTES" not in content and "EXCHANGE" not in content and "PROMPTS OF HIS" not in content
    assert "a woman" in content and "no hat" in content


def test_notes_still_being_taken_are_not_told_yet():
    unfinished = CollectionNotes(prompt_count=5, batches=2, batch_notes=["a note"])

    content = build_request_messages("a woman", "", "no hat", [], unfinished, "S")[1]["content"]

    assert "a note" not in content


def test_the_answer_asked_for_shows_no_dots_a_model_could_copy_back_as_a_prompt():
    content = build_request_messages("a woman, tan", "", "no tan lines", [], None, "S")[1]["content"]

    assert "..." not in content and "…" not in content


def test_asking_the_model_sends_one_question_that_reads_long_and_lets_the_model_go(monkeypatch):
    sent = {}

    def ask(messages, **settings):
        sent["messages"], sent["settings"] = messages, settings
        return {"message": {"content": '{"positive": "a woman", "negative": "tan lines", '
                                       '"answer": "No tan lines now.", "settings": {}}'}}

    monkeypatch.setattr(local_llm, "ask", ask)

    answered = ask_the_model("a woman, tan", "", "no tan lines", EXCHANGE, NOTES)

    assert answered == ("a woman", "tan lines", "No tan lines now.", {})
    assert "a woman, tan" in sent["messages"][1]["content"]
    assert sent["settings"]["json_answer"] is True
    assert sent["settings"]["reads_tokens"] > 16000
    assert sent["settings"]["stays_loaded"] == "0"


def test_asking_the_model_shows_it_his_prompts_that_touch_the_request(monkeypatch):
    sent = {}

    def ask(messages, **settings):
        sent["messages"] = messages
        return {"message": {"content": '{"positive": "a woman, a dog, wagging tail"}'}}

    monkeypatch.setattr(local_llm, "ask", ask)

    ask_the_model("a woman", "", "add a dog", [], None, examples=("a dog, wagging tail",))

    assert "1. a dog, wagging tail" in sent["messages"][1]["content"]


def test_a_field_the_model_leaves_out_is_read_as_unchanged_or_unsaid(monkeypatch):
    monkeypatch.setattr(local_llm, "ask", lambda messages, **settings: {
        "message": {"content": '{"positive": "a man"}'}})

    assert ask_the_model("a woman", "existing negative", "make her a man", [], None) == (
        "a man", "existing negative", "", None)


_SETTINGS_TOLD = request_settings.settings_to_tell(
    [ParamDef("lora_strength", "LoRA Strength", ParamType.FLOAT, 0.8, min_val=0.0, max_val=2.0),
     ParamDef("steps", "Steps", ParamType.INT, 50, min_val=1, max_val=200)],
    {"lora_strength": 0.8, "steps": 50})


def test_the_messages_list_the_settings_he_may_change_and_ask_for_them_in_the_answer():
    content = build_request_messages("a woman", "", "stronger lora", [], None, "S",
                                     settings=_SETTINGS_TOLD)[1]["content"]

    assert "SETTINGS HE MAY ALSO CHANGE" in content
    assert "LoRA Strength [lora_strength]: 0.8, a number from 0.0 to 2.0" in content
    assert content.index("SETTINGS HE MAY") < content.index("CURRENT POSITIVE PROMPT")
    assert '"settings"' in content.rsplit("\n\n", 1)[1]


def test_without_settings_to_tell_the_messages_list_none():
    content = build_request_messages("a woman", "", "no hat", [], None, "S")[1]["content"]

    assert "SETTINGS HE MAY" not in content


def test_a_request_about_a_setting_changes_it_within_its_range_and_leaves_the_prompts():
    model = _Model(("a woman", "blurry", "Turned the LoRA up.", {"lora_strength": "2.5"}))

    revision = work_out("a woman", "blurry", "stronger lora", settings=_SETTINGS_TOLD, ask=model)

    assert model.settings == _SETTINGS_TOLD
    assert revision.changed
    assert (revision.positive, revision.negative) == ("a woman", "blurry")
    assert revision.settings == (("lora_strength", 2.0),)
    assert revision.setting_changes == (("LoRA Strength", "0.8", "2.0"),)
    assert revision.answer == "Turned the LoRA up."


def test_a_model_answering_with_no_settings_key_changes_none():
    revision = work_out("a woman", "blurry", "no hat", settings=_SETTINGS_TOLD,
                        ask=_Model(("a woman", "blurry, hat", "Took the hat off.")))

    assert revision.settings == ()
    assert revision.setting_changes == ()
