from origenerator.db import Database
from origenerator.experiments.background import (
    BATCH_SIZE, cancel_experiments, queue_experiments,
)
from origenerator.experiments.policy import Proposal


class StubPolicy:
    """Yields a fresh canned proposal per ask, counting the asks."""

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
    """Stands in for the gallery's launch adapter: records each proposal and
    returns the launched row's prompt_id — or ``None`` for the launches in
    ``refuse`` (1-based ordinals), or for every launch when ``refuse_all``."""

    def __init__(self, refuse=(), refuse_all=False):
        self.launched = []
        self._refuse = set(refuse)
        self._refuse_all = refuse_all

    def __call__(self, proposal):
        self.launched.append(proposal)
        if self._refuse_all or len(self.launched) in self._refuse:
            return None
        return f"exp-{len(self.launched):03d}"


def test_closing_fills_the_queue_with_a_batch_of_experiments():
    policy = StubPolicy()
    launcher = FakeLauncher()
    assert queue_experiments([], policy, launcher) == BATCH_SIZE
    assert len(launcher.launched) == BATCH_SIZE


def test_a_launch_that_didnt_take_doesnt_use_up_the_batch():
    # A proposal can land in a folder another one already claimed. That's a
    # skip, not an experiment — the batch is short by one unless it's retried.
    policy = StubPolicy()
    launcher = FakeLauncher(refuse=(1, 4))
    assert queue_experiments([], policy, launcher) == BATCH_SIZE
    assert len(launcher.launched) == BATCH_SIZE + 2


def test_a_gallery_with_nothing_to_build_on_queues_nothing():
    policy = StubPolicy(limit=0)
    launcher = FakeLauncher()
    assert queue_experiments([], policy, launcher) == 0
    assert launcher.launched == []


def test_launches_that_keep_failing_give_up_instead_of_retrying_the_batch_out():
    # Nothing takes when ComfyUI is down, and this runs as the app closes —
    # so it must give up quickly rather than spend a submit timeout per slot.
    policy = StubPolicy()
    launcher = FakeLauncher(refuse_all=True)
    assert queue_experiments([], policy, launcher) == 0
    assert 0 < len(launcher.launched) < BATCH_SIZE


class FakeClient:
    """A ComfyUI stand-in: records what was dequeued and interrupted, and
    raises from ``cancel_prompt`` for the prompt ids in ``refuse``."""

    def __init__(self, running=(), refuse=()):
        self.running = set(running)
        self.refuse = set(refuse)
        self.canceled = []
        self.interrupts = 0

    def fetch_running(self):
        return set(self.running)

    def cancel_prompt(self, prompt_id):
        if prompt_id in self.refuse:
            raise OSError("ComfyUI is not answering")
        self.canceled.append(prompt_id)

    def interrupt(self):
        self.interrupts += 1


def _row(db, prompt_id, *, status, source="generated"):
    db.insert_generation(
        prompt_id=prompt_id, workflow_name="fake_t2i", workflow_version="v001",
        params_json="{}", workflow_json="{}", source=source,
    )
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
    assert client.interrupts == 0  # nothing of ours was mid-render
    assert db.get_generation("exp-1") is None
    assert db.get_generation("exp-2") is None
    # A finished experiment is a result to review, and the user's own job is
    # never the experimenter's to cancel.
    assert db.get_generation("exp-done") is not None
    assert db.get_generation("mine") is not None


def test_an_experiment_caught_mid_render_is_interrupted_not_just_dequeued(tmp_path):
    # Dequeuing only unqueues; the one ComfyUI is already executing keeps the
    # GPU until it's interrupted — and holding it is exactly what the user
    # turned this off for.
    db = Database(tmp_path / "test.db")
    _row(db, "exp-1", status="running", source="experiment")
    _row(db, "exp-2", status="pending", source="experiment")
    client = FakeClient(running=["exp-1"])

    assert cancel_experiments(db, client) == 2
    assert client.interrupts == 1


def test_someone_elses_running_prompt_is_never_interrupted(tmp_path):
    # ComfyUI serves other clients too (a sibling app's upscale, say). Only an
    # experiment of ours mid-render earns an interrupt.
    db = Database(tmp_path / "test.db")
    _row(db, "exp-1", status="pending", source="experiment")
    client = FakeClient(running=["someone-elses-prompt"])

    assert cancel_experiments(db, client) == 1
    assert client.interrupts == 0


def test_an_experiment_that_wont_dequeue_keeps_its_row(tmp_path):
    # With ComfyUI unreachable the prompt may still run, so its row has to stay:
    # the app adopts an in-flight row as a live job, and a user launch preempts
    # it. Deleting it would orphan the run and lose the result.
    db = Database(tmp_path / "test.db")
    _row(db, "exp-1", status="running", source="experiment")
    _row(db, "exp-2", status="pending", source="experiment")
    client = FakeClient(refuse=["exp-1"])

    assert cancel_experiments(db, client) == 1
    assert db.get_generation("exp-1") is not None
    assert db.get_generation("exp-2") is None
