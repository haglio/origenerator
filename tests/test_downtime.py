from __future__ import annotations

import json
import types
from dataclasses import dataclass, field
from unittest.mock import MagicMock, patch

from origenerator import collection_notes, downtime, gallery
from origenerator.comfyui_client import ComfyUIClient
from origenerator.comfyui_inputs import ComfyFolders
from origenerator.db import Database
from origenerator.gui.generation_job import GenerationJob
from origenerator.gui.job_queue import JobQueue
from origenerator.output_places import OutputPlaces
from origenerator.workflows import WORKFLOW_REGISTRY
from tests.comfyui_folders import SUITE_FOLDERS

_HANDS = types.SimpleNamespace(name="hands")


@dataclass
class _Machine:
    app_open: bool = False
    notes_due: bool = False
    noted: int = 0
    training: bool = False
    comfyui_busy: bool = False
    batches_due: bool = False
    fix: object = None
    queued: int = 0
    trained: list = field(default_factory=list)

    def turn(self) -> downtime.Turn:
        return downtime.take_a_turn(downtime.Machine(
            app_open=lambda: self.app_open, training_running=lambda: self.training,
            comfyui_busy=lambda: self.comfyui_busy, batches_due=lambda: self.batches_due,
            queue_batches=self._queue, notes_due=lambda: self.notes_due,
            take_notes=self._take_notes,
            fix_to_train=lambda: self.fix, train=self._train))

    def _take_notes(self) -> None:
        self.noted += 1
        self.notes_due = False

    def _queue(self) -> None:
        self.queued += 1
        self.batches_due = False

    def _train(self, part) -> None:
        self.trained.append(part)
        self.training = True


def test_nothing_is_started_while_origenerator_is_open():
    machine = _Machine(app_open=True, batches_due=True, fix=_HANDS)

    turn = machine.turn()

    assert (machine.queued, machine.trained) == (0, [])
    assert turn.holds_the_graphics_card is False


def test_the_work_origenerator_left_as_it_closed_is_handed_to_comfyui_first():
    machine = _Machine(batches_due=True, fix=_HANDS)

    machine.turn()

    assert (machine.queued, machine.trained) == (1, [])


def test_the_work_origenerator_left_as_it_closed_is_handed_over_before_any_notes():
    machine = _Machine(batches_due=True, notes_due=True)

    machine.turn()

    assert (machine.queued, machine.noted) == (1, 0)


def test_once_comfyui_has_nothing_left_a_fix_whose_photos_changed_is_trained():
    machine = _Machine(fix=_HANDS)

    turn = machine.turn()

    assert machine.trained == [_HANDS]
    assert turn.holds_the_graphics_card is True


def test_nothing_new_starts_while_a_training_or_comfyui_still_has_the_graphics_card():
    training = _Machine(training=True, batches_due=True, fix=_HANDS)
    busy = _Machine(comfyui_busy=True, batches_due=True, fix=_HANDS)

    assert training.turn().holds_the_graphics_card is True
    assert busy.turn().holds_the_graphics_card is False
    assert [(m.queued, m.trained) for m in (training, busy)] == [(0, []), (0, [])]


def test_closing_leaves_work_for_while_closed_and_the_next_launch_takes_it_back(
        monkeypatch, tmp_path):
    monkeypatch.setattr(downtime.config, "LIBRARY_STATE_DIR", tmp_path)
    assert downtime.work_left() is False

    downtime.leave_work_for_while_closed()
    assert downtime.work_left() is True

    downtime.forget_work_left()
    assert downtime.work_left() is False


class _Proposing:
    def __init__(self, proposals):
        self.proposals = list(proposals)
        self.asked = 0

    def propose(self, rows):
        self.asked += 1
        return self.proposals.pop(0) if self.proposals else None


def test_the_work_left_tries_experiments_from_the_policy_handed_in_only_while_they_are_on(
        qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(GenerationJob, "start", lambda self, submit=None: None)
    db = Database(tmp_path / "t.db")
    jobs = JobQueue(db, ComfyUIClient(folders=SUITE_FOLDERS))
    workflow = WORKFLOW_REGISTRY["sdxl_t2i"]
    proposal = types.SimpleNamespace(workflow=workflow, params=workflow.default_params(),
                                     base_prompt_id="p0", mutated_keys=["steps"])
    off, on = _Proposing([proposal]), _Proposing([proposal])

    assert downtime.queue_the_work_left(jobs, [], experiments_on=False, policy=off) == 0
    assert downtime.queue_the_work_left(jobs, [], experiments_on=True, policy=on) == 1

    assert off.asked == 0
    (tried,) = [row for row in db.list_generations() if row.get("source") == "experiment"]
    assert jobs.job_for(gallery.settings_folder_key(tried, {})).prompt_id == tried["prompt_id"]


def _the_command_on_a_scratch_library(monkeypatch, tmp_path):
    for name, path in (("LIBRARY_STATE_DIR", tmp_path), ("STATE_DIR", tmp_path),
                       ("UI_STATE_PATH", tmp_path / "ui_state.json"),
                       ("FIX_TRAINING_DIR", tmp_path / "fix training")):
        monkeypatch.setattr(downtime.config, name, path)
    monkeypatch.setattr(downtime, "configure_logging", lambda *args: None)


@dataclass(frozen=True)
class _Copies:
    open_now: bool

    def one_holds_the_library(self):
        return self.open_now

    def one_is_closing(self):
        return False


def _the_app_is(monkeypatch, *, open_now):
    monkeypatch.setattr(downtime, "Copies", lambda path: _Copies(open_now))


def test_the_command_evolver_runs_says_what_it_did_and_whether_it_holds_the_tile(
        monkeypatch, tmp_path, capsys):
    _the_command_on_a_scratch_library(monkeypatch, tmp_path)
    _the_app_is(monkeypatch, open_now=True)

    assert downtime.main() == 0

    assert json.loads(capsys.readouterr().out) == {
        "did": "nothing: Origenerator is open", "holds_the_graphics_card": False}


def _answered(request, timeout):
    response = MagicMock()
    response.read.return_value = json.dumps({"prompt_id": "our-id"}).encode()
    response.__enter__ = lambda answer: answer
    response.__exit__ = MagicMock(return_value=False)
    return response


def test_the_command_evolver_runs_hands_comfyui_each_file_a_run_reads_as_a_copy_it_can_open(
        monkeypatch, tmp_path):
    folders = ComfyFolders(input=tmp_path / "input", temp=tmp_path / "temp",
                           places=OutputPlaces.in_one_folder(tmp_path / "output"))
    for name, value in (("LIBRARY_STATE_DIR", tmp_path), ("STATE_DIR", tmp_path),
                        ("UI_STATE_PATH", tmp_path / "ui_state.json"),
                        ("FIX_TRAINING_DIR", tmp_path / "fix training"),
                        ("COMFYUI_FOLDERS", folders)):
        monkeypatch.setattr(downtime.config, name, value)
    monkeypatch.setattr(downtime, "configure_logging", lambda *args: None)
    _the_app_is(monkeypatch, open_now=False)
    handed = []
    monkeypatch.setattr(downtime, "hand_comfyui_the_work_left",
                        lambda db, client, ui: handed.append(client))
    downtime.leave_work_for_while_closed()
    image = tmp_path / "elsewhere" / "jane_doe.png"
    image.parent.mkdir()
    image.write_bytes(b"fabricated image bytes")

    downtime.main()
    (client,) = handed
    with patch("urllib.request.urlopen", side_effect=_answered) as urlopen:
        client.submit_job({"1": {"class_type": "LoadImage", "inputs": {"image": str(image)}}},
                          "our-id")

    posted = json.loads(urlopen.call_args.args[0].data)["prompt"]
    assert posted["1"]["inputs"]["image"].endswith("/jane_doe.png [temp]")


def _kept(tmp_path, part, *, automatic, **status) -> None:
    work = tmp_path / "fix training" / part
    work.mkdir(parents=True)
    job = {"part": part, "display_name": f"{part.capitalize()} fix 1.0", "work": str(work),
           "status": str(work / "status.json"),
           "process": str(work / "process.json"), "automatic": automatic}
    (work / "job.json").write_text(json.dumps(job), encoding="utf-8")
    (work / "status.json").write_text(json.dumps(status), encoding="utf-8")
    (work / "process.json").write_text(json.dumps({"pid": 1, "started": 1, "began": 0.0}),
                                       encoding="utf-8")


def test_a_training_evolver_started_is_announced_once_when_it_ends_unless_already_taken(
        monkeypatch, tmp_path):
    monkeypatch.setattr(downtime.config, "FIX_TRAINING_DIR", tmp_path / "fix training")
    _kept(tmp_path, "hands", automatic=True, state="done", lora="hands 1.safetensors")
    _kept(tmp_path, "faces", automatic=False, state="done", lora="faces 1.safetensors")
    _kept(tmp_path, "teeth", automatic=True, state="done", lora="teeth 1.safetensors", taken=True)
    announced = []

    downtime.announce_trainings_that_ended(announced.append)
    downtime.announce_trainings_that_ended(announced.append)

    assert [(toast.title, toast.body.split(" · ")[0]) for toast in announced] == [
        ("LoRA ready", "Hands fix 1.0")]


def test_the_command_evolver_runs_holds_the_tile_while_a_look_lora_trains(monkeypatch, tmp_path, capsys):
    _the_command_on_a_scratch_library(monkeypatch, tmp_path)
    _the_app_is(monkeypatch, open_now=True)
    monkeypatch.setattr(downtime, "running_trainings", lambda: [{"base": "Example Look"}])

    assert downtime.main() == 0

    assert json.loads(capsys.readouterr().out)["holds_the_graphics_card"] is True


def test_the_command_evolver_runs_takes_notes_on_the_collection_while_closed_and_idle(
        monkeypatch, tmp_path, capsys):
    _the_command_on_a_scratch_library(monkeypatch, tmp_path)
    monkeypatch.setattr(downtime, "announce_trainings_that_ended", lambda announce: None)
    _the_app_is(monkeypatch, open_now=False)
    monkeypatch.setattr(downtime, "_comfyui_busy", lambda client: False)
    monkeypatch.setattr(collection_notes, "are_due", lambda db, path: True)
    taken = []
    monkeypatch.setattr(collection_notes, "take_a_sitting",
                        lambda db, client, path: taken.append(db.path))

    assert downtime.main() == 0

    assert taken == [tmp_path / "origenerator.db"]
    assert json.loads(capsys.readouterr().out) == {
        "did": "took notes on the collection", "holds_the_graphics_card": False}
