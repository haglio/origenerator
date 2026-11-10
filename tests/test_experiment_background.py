from __future__ import annotations

from origenerator.db import Database, NewGeneration
from origenerator.experiments.background import (
    EXPERIMENTS_QUEUED_PER_ABSENCE,
    cancel_experiments,
    queue_experiments,
)
from origenerator.experiments.policy import Proposal


class StubPolicy:
    def __init__(self, limit=None):
        self.asks = 0
        self._limit = limit

    def propose(self, rows):
        if self._limit is not None and self.asks >= self._limit:
            return None
        self.asks += 1
        return Proposal(
            workflow=None, params={"seed": self.asks},
            base_prompt_id="base", mutated_keys=("steps",),
        )


class FakeLauncher:
    def __init__(self, refuse=(), refuse_all=False):
        self.launched = []
        self._refuse = set(refuse)
        self._refuse_all = refuse_all

    def __call__(self, proposal):
        self.launched.append(proposal)
        if self._refuse_all or len(self.launched) in self._refuse:
            return None
        return f"exp-{len(self.launched):03d}"


def test_each_launch_records_what_it_was_bred_from_and_what_it_varies(caplog):
    with caplog.at_level("INFO", logger="origenerator.experiments.background"):
        queue_experiments([], StubPolicy(limit=1), FakeLauncher())

    assert "bred from base, varying steps" in caplog.text, (
        "the app is shut while the batch runs, so the log is the one record of what it explored")


def test_closing_fills_the_queue_with_a_batch_of_experiments():
    policy = StubPolicy()
    launcher = FakeLauncher()
    assert queue_experiments([], policy, launcher) == EXPERIMENTS_QUEUED_PER_ABSENCE
    assert len(launcher.launched) == EXPERIMENTS_QUEUED_PER_ABSENCE
    assert EXPERIMENTS_QUEUED_PER_ABSENCE <= 10, (
        "every one comes back as a tile to review: enough to fill an evening, "
        "few enough for one sitting")


def test_a_launch_that_didnt_take_doesnt_use_up_the_batch():
    policy = StubPolicy()
    launcher = FakeLauncher(refuse=(1, 4))
    assert queue_experiments([], policy, launcher) == EXPERIMENTS_QUEUED_PER_ABSENCE
    assert len(launcher.launched) == EXPERIMENTS_QUEUED_PER_ABSENCE + 2, (
        "a refused launch is usually a proposal landing in a folder an earlier one claimed, "
        "so the next proposal is worth trying")


def test_a_gallery_with_nothing_to_build_on_queues_nothing():
    policy = StubPolicy(limit=0)
    launcher = FakeLauncher()
    assert queue_experiments([], policy, launcher) == 0
    assert launcher.launched == []


def test_launches_that_keep_failing_give_up_instead_of_retrying_the_batch_out():
    policy = StubPolicy()
    launcher = FakeLauncher(refuse_all=True)
    assert queue_experiments([], policy, launcher) == 0
    assert 0 < len(launcher.launched) < EXPERIMENTS_QUEUED_PER_ABSENCE


class FakeClient:
    def __init__(self, refuse=()):
        self.refuse = set(refuse)
        self.canceled = []
        self.interrupted = []

    def cancel_prompt(self, prompt_id):
        if prompt_id in self.refuse:
            raise OSError("ComfyUI is not answering")
        self.canceled.append(prompt_id)

    def interrupt(self, prompt_id=None):
        self.interrupted.append(prompt_id)


def _row(db, prompt_id, *, status, source="generated"):
    db.insert_generation(NewGeneration(
        prompt_id=prompt_id, workflow_name="fake_t2i", workflow_version="v001",
        params_json="{}", workflow_json="{}", source=source,
    ))
    db.update_generation(prompt_id, status=status)


def test_opening_drops_every_experiment_still_waiting_in_the_queue(tmp_path):
    db = Database(tmp_path / "test.db")
    _row(db, "exp-1", status="running", source="experiment")
    _row(db, "exp-2", status="pending", source="experiment")
    _row(db, "exp-done", status="completed", source="experiment")
    _row(db, "mine", status="running")
    client = FakeClient()

    assert cancel_experiments(db, client) == 2
    assert sorted(client.canceled) == ["exp-1", "exp-2"]
    assert db.get_generation("exp-1") is None
    assert db.get_generation("exp-2") is None
    assert db.get_generation("exp-done") is not None
    assert db.get_generation("mine") is not None, (
        "only experiments are dropped: with the app open the graphics card is for the "
        "user's own work, and no experiment may compete for it")


def test_each_experiment_is_asked_to_stop_by_name_in_case_it_is_mid_render(tmp_path):
    # ComfyUI serves other clients too, and a nameless /interrupt stops whatever is executing, so stop each by name
    db = Database(tmp_path / "test.db")
    _row(db, "exp-1", status="running", source="experiment")
    _row(db, "exp-2", status="pending", source="experiment")
    client = FakeClient()

    assert cancel_experiments(db, client) == 2
    assert sorted(client.interrupted) == ["exp-1", "exp-2"]


def test_an_experiment_that_wont_dequeue_keeps_its_row(tmp_path):
    db = Database(tmp_path / "test.db")
    _row(db, "exp-1", status="running", source="experiment")
    _row(db, "exp-2", status="pending", source="experiment")
    client = FakeClient(refuse=["exp-1"])

    assert cancel_experiments(db, client) == 1
    assert db.get_generation("exp-1") is not None
    assert db.get_generation("exp-2") is None
