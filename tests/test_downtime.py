from __future__ import annotations

import json
import types
from unittest.mock import MagicMock, patch

from origenerator import downtime, gallery
from origenerator.comfyui_client import ComfyUIClient
from origenerator.comfyui_inputs import ComfyFolders
from origenerator.db import Database
from origenerator.gui.generation_job import GenerationJob
from origenerator.gui.job_queue import JobQueue
from origenerator.output_places import OutputPlaces
from origenerator.workflows import WORKFLOW_REGISTRY
from tests.comfyui_folders import SUITE_FOLDERS

_HANDS = types.SimpleNamespace(name="hands")


class _Machine:
    def __init__(self, *, app_open=False, training=False, comfyui_busy=False, batches_due=False,
                 fix=None, backfill_batches=0):
        self.app_open = app_open
        self.training = training
        self.comfyui_busy = comfyui_busy
        self.batches_due = batches_due
        self.fix = fix
        self.backfill_batches = backfill_batches
        self.queued = 0
        self.backfilled = 0
        self.trained = []

    def turn(self) -> downtime.Turn:
        return downtime.take_a_turn(
            app_open=lambda: self.app_open, training_running=lambda: self.training,
            comfyui_busy=lambda: self.comfyui_busy, batches_due=lambda: self.batches_due,
            queue_batches=self._queue, queue_more_backfill=self._backfill,
            fix_to_train=lambda: self.fix, train=self._train)

    def _queue(self) -> None:
        self.queued += 1
        self.batches_due = False

    def _backfill(self) -> int:
        if not self.backfill_batches:
            return 0
        self.backfill_batches -= 1
        self.backfilled += 1
        return 6

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


def test_while_origenerator_stays_closed_comfyui_gets_the_backfills_next_batch_once_it_is_idle():
    machine = _Machine(backfill_batches=2, fix=_HANDS)

    turns = [machine.turn().did for _ in range(3)]

    assert machine.backfilled == 2
    assert turns[:2] == ["handed ComfyUI the next videos the backfill remakes"] * 2
    assert machine.trained == [_HANDS]


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


def test_the_command_evolver_runs_says_what_it_did_and_whether_it_holds_the_card(
        monkeypatch, tmp_path, capsys):
    for name, path in (("LIBRARY_STATE_DIR", tmp_path), ("STATE_DIR", tmp_path),
                       ("UI_STATE_PATH", tmp_path / "ui_state.json"),
                       ("FIX_TRAINING_DIR", tmp_path / "fix training")):
        monkeypatch.setattr(downtime.config, name, path)
    monkeypatch.setattr(downtime, "configure_logging", lambda *args: None)
    monkeypatch.setattr(downtime, "Copies", lambda path: types.SimpleNamespace(
        one_holds_the_library=lambda: True, one_is_closing=lambda: False))

    assert downtime.main() == 0

    assert json.loads(capsys.readouterr().out) == {
        "did": "nothing: Origenerator is open", "holds_the_graphics_card": False}


def test_the_command_evolver_runs_hands_comfyui_more_of_the_backfill_while_closed_and_idle(
        monkeypatch, tmp_path, capsys):
    for name, path in (("LIBRARY_STATE_DIR", tmp_path), ("STATE_DIR", tmp_path),
                       ("UI_STATE_PATH", tmp_path / "ui_state.json"),
                       ("FIX_TRAINING_DIR", tmp_path / "fix training")):
        monkeypatch.setattr(downtime.config, name, path)
    monkeypatch.setattr(downtime, "configure_logging", lambda *args: None)
    monkeypatch.setattr(downtime, "announce_trainings_that_ended", lambda announce: None)
    monkeypatch.setattr(downtime, "Copies", lambda path: types.SimpleNamespace(
        one_holds_the_library=lambda: False, one_is_closing=lambda: False))
    monkeypatch.setattr(downtime, "_comfyui_busy", lambda client: False)
    handed = []
    monkeypatch.setattr(downtime, "hand_comfyui_more_of_the_backfill",
                        lambda db, client, ui: handed.append((db.path, client.folders)) or 6)

    assert downtime.main() == 0

    assert handed == [(tmp_path / "origenerator.db", downtime.config.COMFYUI_FOLDERS)]
    assert json.loads(capsys.readouterr().out) == {
        "did": "handed ComfyUI the next videos the backfill remakes",
        "holds_the_graphics_card": False}


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
    monkeypatch.setattr(downtime, "Copies", lambda path: types.SimpleNamespace(
        one_holds_the_library=lambda: False, one_is_closing=lambda: False))
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

    assert [(notice.title, notice.body.split(" · ")[0]) for notice in announced] == [
        ("LoRA ready", "Hands fix 1.0")]
