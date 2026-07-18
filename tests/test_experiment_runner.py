import json

from origenerator.db import Database
from origenerator.experiments.policy import Proposal
from origenerator.experiments.runner import ExperimentRunner


class StubPolicy:
    """Yields a fresh canned proposal per ask, counting the asks."""

    def __init__(self):
        self.asks = 0

    def propose(self, rows):
        self.asks += 1
        return Proposal(
            workflow=None, params={"seed": self.asks},
            base_prompt_id="base", mutated_keys=("steps",),
        )


class FakeLauncher:
    """Stands in for the gallery's launch adapter: records each proposal and
    inserts the pending row a real launch would, returning its prompt_id."""

    def __init__(self, db, fail=False):
        self.db = db
        self.fail = fail
        self.launched = []

    def __call__(self, proposal):
        self.launched.append(proposal)
        if self.fail:
            return None
        prompt_id = f"exp-{len(self.launched):03d}"
        self.db.insert_generation(
            prompt_id=prompt_id, workflow_name="fake_t2i", workflow_version="v001",
            params_json=json.dumps(proposal.params), workflow_json="{}",
            source="experiment",
        )
        return prompt_id


def make_runner(tmp_path, *, fail=False, busy=False):
    db = Database(tmp_path / "test.db")
    policy = StubPolicy()
    launcher = FakeLauncher(db, fail=fail)
    runner = ExperimentRunner(db, policy, launcher, gpu_busy=lambda: busy)
    return runner, db, policy, launcher


def test_a_disabled_runner_launches_nothing(qtbot, tmp_path):
    runner, _db, policy, launcher = make_runner(tmp_path)
    runner.tick()
    assert policy.asks == 0
    assert launcher.launched == []


def test_an_idle_tick_launches_one_experiment_and_only_one(qtbot, tmp_path):
    runner, db, _policy, launcher = make_runner(tmp_path)
    runner.set_enabled(True)  # ticks at once — no waiting out the first interval
    assert len(launcher.launched) == 1
    # The launched experiment is now pending in the DB: further ticks must wait
    # for it rather than stack the queue.
    runner.tick()
    runner.tick()
    assert len(launcher.launched) == 1
    # Once it completes, the next tick may launch the next experiment.
    db.update_generation("exp-001", status="completed")
    runner.tick()
    assert len(launcher.launched) == 2


def test_experiments_wait_while_anyone_elses_job_is_in_flight(qtbot, tmp_path):
    runner, db, _policy, launcher = make_runner(tmp_path)
    db.insert_generation(
        prompt_id="user-job", workflow_name="fake_t2i", workflow_version="v001",
        params_json="{}", workflow_json="{}",
    )
    db.update_generation("user-job", status="running")
    runner.set_enabled(True)
    assert launcher.launched == []
    # The user's job finishing frees the queue for an experiment.
    db.update_generation("user-job", status="completed")
    runner.tick()
    assert len(launcher.launched) == 1


def test_experiments_wait_while_the_gpu_is_busy_elsewhere(qtbot, tmp_path):
    runner, _db, _policy, launcher = make_runner(tmp_path, busy=True)
    runner.set_enabled(True)
    assert launcher.launched == []


def test_failures_back_off_exponentially_and_a_success_resets(qtbot, tmp_path):
    runner, db, _policy, launcher = make_runner(tmp_path)
    runner.set_enabled(True)
    db.update_generation("exp-001", status="error", error_message="boom")
    # The failure is noticed on the next tick, which then sits out 2 ticks.
    runner.tick()
    assert len(launcher.launched) == 1
    runner.tick()
    runner.tick()
    assert len(launcher.launched) == 1
    runner.tick()  # cooldown over — try again
    assert len(launcher.launched) == 2
    # A second straight failure doubles the sit-out (4 ticks this time).
    db.update_generation("exp-002", status="error", error_message="boom")
    runner.tick()
    for _ in range(4):
        runner.tick()
        assert len(launcher.launched) == 2
    runner.tick()
    assert len(launcher.launched) == 3
    # A completed experiment clears the streak: the next failure backs off 2
    # ticks again, not 8.
    db.update_generation("exp-003", status="completed")
    runner.tick()
    assert len(launcher.launched) == 4
    db.update_generation("exp-004", status="error", error_message="boom")
    runner.tick()
    runner.tick()
    runner.tick()
    assert len(launcher.launched) == 4
    runner.tick()
    assert len(launcher.launched) == 5


def test_a_rejected_submit_backs_off_too(qtbot, tmp_path):
    runner, _db, _policy, launcher = make_runner(tmp_path, fail=True)
    runner.set_enabled(True)
    assert len(launcher.launched) == 1
    runner.tick()  # cooldown tick 1
    runner.tick()  # cooldown tick 2
    assert len(launcher.launched) == 1
    runner.tick()
    assert len(launcher.launched) == 2


def test_a_user_cancelled_experiment_earns_a_breather_not_a_failure(qtbot, tmp_path):
    # Cancelling the in-flight experiment (its card's ✕) deletes its row. The
    # next one shouldn't spawn 20 seconds later in the user's face — sit out a
    # few ticks — but it's no failure either, so no exponential streak builds.
    runner, db, _policy, launcher = make_runner(tmp_path)
    runner.set_enabled(True)
    db.delete_generation("exp-001")
    runner.tick()
    runner.tick()
    runner.tick()
    assert len(launcher.launched) == 1
    runner.tick()
    assert len(launcher.launched) == 2


def test_the_timer_runs_only_while_enabled(qtbot, tmp_path):
    runner, _db, _policy, _launcher = make_runner(tmp_path)
    assert not runner._timer.isActive()
    runner.set_enabled(True)
    assert runner.is_enabled() and runner._timer.isActive()
    runner.set_enabled(False)
    assert not runner.is_enabled() and not runner._timer.isActive()
