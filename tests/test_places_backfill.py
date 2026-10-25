"""Finding the places in pictures enhanced before the places were kept: only the Fixes' finding,
run while the app is shut."""
from __future__ import annotations

import json

import pytest

from origenerator import downtime, gallery, places_backfill, points_of_interest
from origenerator.app_state import AppState
from origenerator.comfyui_client import ComfyUIClient
from origenerator.db import Database
from origenerator.gui.main_window import OrigeneratorWindow
from origenerator.workflows import detail_parts

FIXED = {"enhance_detail_fixes": {"faces": 0.45}}


@pytest.fixture(autouse=True)
def _installed_detectors(monkeypatch):
    monkeypatch.setattr(detail_parts, "list_detector_files", lambda: ["face_finder.pt", "eye_finder.pt"])


def _file(name, **extra):
    return {"filename": name, "subfolder": "image", "type": "output", **extra}


def _enhanced(db, prompt_id, enhanced_file, *, settings=FIXED):
    original = _file(f"{prompt_id}_original.png")
    db.insert_generation(prompt_id=prompt_id, workflow_name="sdxl_t2i", workflow_version="v004",
                         positive_prompt="scene one", seed=1, params_json="{}", workflow_json="{}",
                         source="generated")
    db.update_generation(prompt_id, status="completed",
                         output_files=json.dumps([enhanced_file, original]),
                         original_files=json.dumps([original]),
                         enhance_history=json.dumps(
                             [{"filename": enhanced_file["filename"], "params": settings}]))
    return db.get_generation(prompt_id)


class FakeComfy:
    def __init__(self, histories: dict | None = None) -> None:
        self.submitted: dict[str, dict] = {}
        self.histories = histories or {}
        self.cancelled: list[str] = []

    def submit_job(self, payload: dict, prompt_id: str) -> None:
        self.submitted[prompt_id] = payload

    def fetch_history(self, prompt_id: str) -> dict:
        return self.histories.get(prompt_id, {})

    def cancel_prompt(self, prompt_id: str) -> None:
        self.cancelled.append(prompt_id)

    def interrupt(self, prompt_id: str) -> None:
        pass


def _looked_over(db) -> list[tuple[str, str]]:
    return [(row["prompt_id"], level.file["filename"])
            for row, level in places_backfill.pictures_to_look_over(db.list_generations())]


def test_a_picture_enhanced_before_its_places_were_kept_is_one_to_look_over(tmp_path):
    db = Database(tmp_path / "t.db")
    _enhanced(db, "old", _file("enhanced_old.png"))
    _enhanced(db, "kept", _file("enhanced_kept.png", **points_of_interest.kept([])))

    assert _looked_over(db) == [("old", "enhanced_old.png")]


def test_a_picture_whose_places_were_kept_before_they_named_their_part_is_looked_over_again(tmp_path):
    db = Database(tmp_path / "t.db")
    unnamed = {"left": 0.1, "top": 0.1, "right": 0.3, "bottom": 0.3}
    _enhanced(db, "early", _file("enhanced_early.png", points_of_interest=[unnamed]))
    _enhanced(db, "named", _file("enhanced_named.png", **points_of_interest.kept([{**unnamed, "part": "faces"}])))

    assert _looked_over(db) == [("early", "enhanced_early.png")]


def test_a_picture_whose_eyes_were_kept_already_joined_is_looked_over_again(tmp_path):
    db = Database(tmp_path / "t.db")
    joined = {"left": 0.1, "top": 0.1, "right": 0.6, "bottom": 0.3, "part": "eyes"}
    _enhanced(db, "joined", _file("enhanced_joined.png", points_of_interest=[joined]))

    assert _looked_over(db) == [("joined", "enhanced_joined.png")]


def test_a_picture_is_looked_over_by_its_own_enhancements_detectors_and_nothing_is_redrawn(tmp_path):
    db = Database(tmp_path / "t.db")
    _enhanced(db, "old", _file("enhanced_old.png"), settings={"enhance_detail_fixes": {"faces": 0.45, "eyes": 0.4}})
    [(_row, level)] = places_backfill.pictures_to_look_over(db.list_generations())

    graph = places_backfill.finding_graph(level)

    kinds = [node["class_type"] for node in graph.values()]
    assert [node["inputs"]["image"] for node in graph.values() if node["class_type"] == "LoadImage"] == [
        "image/enhanced_old.png [output]"]
    assert sorted(node["inputs"]["model_name"] for node in graph.values()
                  if node["class_type"] == "UltralyticsDetectorProvider") == ["bbox/eye_finder.pt", "bbox/face_finder.pt"]
    assert kinds.count("PreviewAny") == 2
    assert not set(kinds) & {"DetailerForEach", "KSampler", "SaveImage", "VAEDecode"}


def test_closing_hands_comfyui_one_finding_per_picture_and_writes_down_which_finds_which(tmp_path):
    db = Database(tmp_path / "t.db")
    _enhanced(db, "a", _file("enhanced_a.png"))
    _enhanced(db, "b", _file("enhanced_b.png"))
    comfy, record = FakeComfy(), tmp_path / "finding.json"

    assert places_backfill.queue_finding(db.list_generations(), comfy, record) == 2

    written = json.loads(record.read_text(encoding="utf-8"))
    assert set(written) == set(comfy.submitted)
    assert sorted(written.values(), key=lambda one: one["row"]) == [
        {"row": "a", "file": "enhanced_a.png"}, {"row": "b", "file": "enhanced_b.png"}]


def test_one_absence_hands_comfyui_no_more_pictures_than_it_is_allowed(tmp_path):
    db = Database(tmp_path / "t.db")
    _enhanced(db, "a", _file("enhanced_a.png"))
    _enhanced(db, "b", _file("enhanced_b.png"))

    assert places_backfill.queue_finding(db.list_generations(), FakeComfy(), tmp_path / "f.json", limit=1) == 1


class _TheProcessEnded(BaseException):
    pass


class _ComfyEndedPartway(FakeComfy):
    """The ComfyUI the closed app's turn was handing pictures to when that turn
    was ended, as a turn that runs out of its time is."""

    def __init__(self, ended_after: int) -> None:
        super().__init__()
        self._ended_after = ended_after

    def submit_job(self, payload: dict, prompt_id: str) -> None:
        if len(self.submitted) == self._ended_after:
            raise _TheProcessEnded
        super().submit_job(payload, prompt_id)


def test_a_hand_over_ended_partway_leaves_a_note_of_every_picture_it_sent(tmp_path):
    # The next launch takes back off ComfyUI what the note names, so a picture
    # sent and not written down would be looked over while the app is open again.
    db = Database(tmp_path / "t.db")
    for name in ("a", "b", "c"):
        _enhanced(db, name, _file(f"enhanced_{name}.png"))
    comfy, record = _ComfyEndedPartway(ended_after=2), tmp_path / "finding.json"

    with pytest.raises(_TheProcessEnded):
        places_backfill.queue_finding(db.list_generations(), comfy, record)

    assert set(comfy.submitted) <= set(json.loads(record.read_text(encoding="utf-8")))


def test_a_picture_already_handed_to_comfyui_is_not_handed_over_again(tmp_path):
    db = Database(tmp_path / "t.db")
    _enhanced(db, "a", _file("enhanced_a.png"))
    record = tmp_path / "finding.json"
    places_backfill.queue_finding(db.list_generations(), FakeComfy(), record)

    assert places_backfill.queue_finding(db.list_generations(), FakeComfy(), record) == 0


def _report(*regions) -> dict:
    return {"text": [json.dumps(list(region)) for region in regions]}


def test_the_next_launch_keeps_what_each_finished_run_found_and_takes_back_the_rest(tmp_path):
    db = Database(tmp_path / "t.db")
    _enhanced(db, "a", _file("enhanced_a.png"))
    _enhanced(db, "b", _file("enhanced_b.png"))
    record, closing = tmp_path / "finding.json", FakeComfy()
    places_backfill.queue_finding(db.list_generations(), closing, record)
    runs = {one["row"]: run for run, one in json.loads(record.read_text(encoding="utf-8")).items()}
    opening = FakeComfy(histories={runs["a"]: {
        "prompt": [1, runs["a"], closing.submitted[runs["a"]], {}, []],
        "outputs": {"fix0_points": _report((100, 100, 300, 300), (0, 0, 1000, 1000))}}})

    assert places_backfill.fold_found_places(db, opening, record) == 1

    assert gallery.row_output_files(db.get_generation("a"))[0]["points_of_interest"] == [
        {"left": 0.1, "top": 0.1, "right": 0.3, "bottom": 0.3, "part": "faces"}]
    assert opening.cancelled == [runs["b"]]
    assert _looked_over(db) == [("b", "enhanced_b.png")]
    assert places_backfill.queue_finding(db.list_generations(), FakeComfy(), record) == 1


def test_a_picture_whose_run_found_nothing_is_not_looked_over_again(tmp_path):
    db = Database(tmp_path / "t.db")
    _enhanced(db, "a", _file("enhanced_a.png"))
    record, closing = tmp_path / "finding.json", FakeComfy()
    places_backfill.queue_finding(db.list_generations(), closing, record)
    [run] = closing.submitted
    opening = FakeComfy(histories={run: {"prompt": [1, run, closing.submitted[run], {}, []],
                                         "outputs": {"fix0_points": _report((0, 0, 1000, 1000))}}})

    places_backfill.fold_found_places(db, opening, record)

    assert _looked_over(db) == []


def test_a_picture_gone_before_its_places_came_back_is_passed_over(tmp_path):
    db = Database(tmp_path / "t.db")
    _enhanced(db, "a", _file("enhanced_a.png"))
    record, closing = tmp_path / "finding.json", FakeComfy()
    places_backfill.queue_finding(db.list_generations(), closing, record)
    [run] = closing.submitted
    db.delete_generation("a")
    opening = FakeComfy(histories={run: {"prompt": [1, run, closing.submitted[run], {}, []],
                                         "outputs": {"fix0_points": _report((100, 100, 300, 300), (0, 0, 1000, 1000))}}})

    assert places_backfill.fold_found_places(db, opening, record) == 0


def test_once_closed_the_apps_turn_hands_comfyui_the_pictures_to_look_over(qtbot, tmp_path,
                                                                             monkeypatch):
    submitted = []
    monkeypatch.setattr(ComfyUIClient, "submit_job", lambda self, payload, prompt_id: submitted.append(prompt_id))
    monkeypatch.setattr(places_backfill, "RECORD", tmp_path / "finding.json")
    db = Database(tmp_path / "t.db")
    _enhanced(db, "a", _file("enhanced_a.png"))
    window = OrigeneratorWindow(ComfyUIClient(), db, AppState(tmp_path / "ui.json"))
    qtbot.addWidget(window)
    window.close()
    window.hand_comfyui_what_runs_while_closed()
    assert submitted == []

    downtime.hand_comfyui_the_work_left(db, ComfyUIClient(), AppState(tmp_path / "ui.json"))

    looked_over = list(json.loads((tmp_path / "finding.json").read_text(encoding="utf-8")))
    assert looked_over
    assert set(looked_over) <= set(submitted)


def test_a_branch_preview_hands_comfyui_no_pictures_to_look_over(tmp_path, monkeypatch):
    comfy = FakeComfy()
    monkeypatch.setattr(places_backfill, "RECORD", tmp_path / "finding.json")
    monkeypatch.setattr(places_backfill, "is_branch_session", lambda: True)
    db = Database(tmp_path / "t.db")
    _enhanced(db, "a", _file("enhanced_a.png"))

    assert places_backfill.queue_finding_for_the_absence(db, comfy) == 0
    assert comfy.submitted == {}


def test_opening_the_app_keeps_the_places_found_while_it_was_closed(qtbot, tmp_path, monkeypatch):
    record = tmp_path / "finding.json"
    monkeypatch.setattr(places_backfill, "RECORD", record)
    db = Database(tmp_path / "t.db")
    _enhanced(db, "a", _file("enhanced_a.png"))
    closing = FakeComfy()
    places_backfill.queue_finding(db.list_generations(), closing, record)
    [run] = closing.submitted
    finished = {"prompt": [1, run, closing.submitted[run], {}, []],
                "outputs": {"fix0_points": _report((100, 100, 300, 300), (0, 0, 1000, 1000))}}
    monkeypatch.setattr(ComfyUIClient, "fetch_history", lambda self, prompt_id: finished if prompt_id == run else {})

    qtbot.addWidget(OrigeneratorWindow(ComfyUIClient(), db, AppState(tmp_path / "ui.json")))

    assert gallery.row_output_files(db.get_generation("a"))[0]["points_of_interest"] == [
        {"left": 0.1, "top": 0.1, "right": 0.3, "bottom": 0.3, "part": "faces"}]


def test_a_picture_whose_enhancement_fixed_no_part_has_nothing_to_look_for(tmp_path):
    db = Database(tmp_path / "t.db")
    _enhanced(db, "plain", _file("enhanced_plain.png"), settings={"enhance_detail_fixes": {}})

    assert _looked_over(db) == []
