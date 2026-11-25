from __future__ import annotations

import os
import random
import sys
import time
from collections import Counter
from dataclasses import dataclass
from functools import partial
from pathlib import Path

from origenerator import collection_notes, config, graphics_card, local_llm, prompt_edit
from origenerator.his_edits import edits_in, words_in_order
from origenerator.prompt_checks import things_of

HOLDER = "Origenerator's Request measurement"
SCORES_PATH = config.STATE_DIR / "request_measure.txt"
_REQUESTS_MEASURED = 40


@dataclass(frozen=True)
class Case:
    before: tuple[str, str]
    after: tuple[str, str]
    word: str
    earlier: int

    @property
    def request(self) -> str:
        return f"add {self.word}"


def _words(things) -> set[str]:
    return {word for thing in things for word in words_in_order(thing)}


def cases_in(prompts) -> list[Case]:
    edits = {edit.position: edit for edit in edits_in(prompts)}
    written_before: set[str] = set()
    cases = []
    for position, (positive, _negative) in enumerate(prompts):
        edit = edits.get(position)
        new_to_it = written_before - _words(edit.before) if edit else set()
        for thing in (edit.added if edit else ()):
            named = [word for word in words_in_order(thing) if word in new_to_it]
            if named:
                cases.append(Case(prompts[edit.made_from], prompts[position], named[-1], position))
        written_before |= _words([positive])
    return cases


def _gained(before: str, after: str) -> set[str]:
    return set(things_of(after)) - set(things_of(before))


@dataclass(frozen=True)
class Scores:
    counted: Counter
    seconds: float = 0.0

    def _share(self, of: str, whole: str = "requests") -> str:
        return f"{100 * self.counted[of] / self.counted[whole]:.0f}%" if self.counted[whole] else "-"

    def lines(self) -> list[str]:
        requests = self.counted["requests"] or 1
        return [
            f"Requests measured: {self.counted['requests']}",
            f"The thing went in in the words you wrote it in: {self._share('in his words')}",
            f"Nothing off topic went in: {self._share('nothing off topic')}",
            f"Off-topic parts per Request: {self.counted['off topic'] / requests:.2f}",
            f"Of the parts you added, went in: {self._share('his that went in', 'his')}",
            f"Of the parts that went in, you had added: {self._share('his that went in', 'went in')}",
            f"Exactly your edit: {self._share('exactly his edit')}",
            f"Seconds per Request: {self.seconds / requests:.1f}",
        ]


def _counts_of(case: Case, answered: tuple[str, str]) -> Counter:
    his = [_gained(before, after) for before, after in zip(case.before, case.after, strict=True)]
    its = [_gained(before, after) for before, after in zip(case.before, answered, strict=True)]
    his_all, its_all = his[0] | {f"-{thing}" for thing in his[1]}, its[0] | {f"-{thing}" for thing in its[1]}
    naming = {thing for thing in his[0] if case.word in _words([thing])}
    on_topic = _words(his[0] | his[1]) | {case.word}
    off_topic = sum(1 for thing in (its[0] - his[0]) | (its[1] - his[1]) if not _words([thing]) & on_topic)
    return Counter({"requests": 1, "in his words": naming <= its[0], "off topic": off_topic,
                    "nothing off topic": not off_topic, "his": len(his_all), "went in": len(its_all),
                    "his that went in": len(his_all & its_all), "exactly his edit": his_all == its_all})


def measured(cases, prompts, answer, *, clock=time.monotonic) -> Scores:
    counted: Counter = Counter()
    began = clock()
    for case in cases:
        counted += _counts_of(case, answer(case.before, case.request, prompts[:case.earlier]))
    return Scores(counted, clock() - began)


class _ModelThatWaitsItsTurn:
    def __init__(self, take, ask=local_llm.ask):
        self._take = take
        self._ask = ask
        self.taken = False

    def ask(self, messages, **how):
        self.taken = self.taken or self._take()
        if not self.taken:
            raise TimeoutError("the graphics card stayed busy")
        return self._ask(messages, **how)


def as_the_app_answers(llm, notes=None):
    def answer(pair: tuple[str, str], request: str, his_prompts) -> tuple[str, str]:
        revision = prompt_edit.work_out(
            *pair, request, ask=partial(prompt_edit.answer_to, llm=llm), notes=notes,
            **prompt_edit.known_from(his_prompts, request))
        return pair if revision is None else (revision.positive, revision.negative)
    return answer


def _his_prompts() -> list[tuple[str, str]]:
    from origenerator.db_connection import SqliteFile  # noqa: PLC0415
    from origenerator.db_requests import RequestStore  # noqa: PLC0415
    return RequestStore(SqliteFile(config.DB_PATH)).distinct_prompts()


def _takes_the_graphics_card() -> bool:
    from origenerator import comfyui_folders  # noqa: PLC0415
    from origenerator.comfyui_client import ComfyUIClient  # noqa: PLC0415
    return graphics_card.wait_for_the_graphics_card(
        ComfyUIClient(folders=comfyui_folders.COMFYUI_FOLDERS), HOLDER)


def main(argv=None, *, scores_path: Path = SCORES_PATH, shown=os.startfile, **stand_ins) -> None:
    how_many = int((argv if argv is not None else sys.argv[1:] or [_REQUESTS_MEASURED])[0])
    prompts = stand_ins.get("his_prompts", _his_prompts)()
    cases = cases_in(prompts)
    chosen = random.Random(0).sample(cases, min(how_many, len(cases)))
    model = _ModelThatWaitsItsTurn(stand_ins.get("take", _takes_the_graphics_card),
                                           stand_ins.get("ask", local_llm.ask))
    try:
        scores = measured(chosen, prompts, as_the_app_answers(
            model.ask, collection_notes.read(stand_ins.get("notes_path", config.COLLECTION_NOTES_PATH))))
    finally:
        if model.taken:
            stand_ins.get("leave", graphics_card.leave_the_graphics_card)()
    scores_path.parent.mkdir(parents=True, exist_ok=True)
    scores_path.write_text("\n".join(scores.lines()) + "\n", encoding="utf-8")
    shown(scores_path)


if __name__ == "__main__":
    main()
