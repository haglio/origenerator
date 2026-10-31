from __future__ import annotations

from origenerator.generation_state import GenerationSource
from origenerator.run_toast import RunOutcome, outcome_of_row, toast_for


def test_a_video_over_in_seconds_is_not_worth_interrupting_for():
    outcome = RunOutcome(kind="Video", display_name="WAN 2.2 I2V", seconds=40.0, ok=True,
                         source=GenerationSource.GENERATED, generation="alpha-1")
    assert toast_for(outcome) is None


def test_a_run_past_the_minute_says_what_landed_and_how_long_it_took():
    outcome = RunOutcome(kind="Video", display_name="WAN 2.2 I2V",
                         seconds=252.0, ok=True, source=GenerationSource.GENERATED,
                         generation="alpha-1")
    toast = toast_for(outcome)
    assert toast.title == "Video ready"
    assert toast.body == "WAN 2.2 I2V · 4:12"
    assert toast.ok


def test_a_long_run_that_died_says_so_rather_than_claiming_a_result():
    outcome = RunOutcome(kind="Video", display_name="WAN 2.2 I2V",
                         seconds=220.0, ok=False, source=GenerationSource.GENERATED,
                         generation="alpha-1")
    toast = toast_for(outcome)
    assert toast.title == "Video failed"
    assert toast.body == "WAN 2.2 I2V · stopped after 3:40"
    assert not toast.ok


def test_the_apps_own_background_work_interrupts_nobody():
    for source in (GenerationSource.EXPERIMENT, GenerationSource.BASE_RENDER):
        outcome = RunOutcome(kind="Video", display_name="WAN 2.2 I2V",
                             seconds=600.0, ok=True, source=source,
                             generation="alpha-1")
        assert toast_for(outcome) is None


def test_an_enhancement_interrupts_nobody_however_long_it_ran():
    for ok in (True, False):
        outcome = RunOutcome(kind="Enhance", display_name="Image Enhance", seconds=600.0, ok=ok,
                             source=GenerationSource.GENERATED, generation="alpha-1")
        assert toast_for(outcome) is None


def test_an_image_interrupts_nobody_however_long_it_ran():
    outcome = RunOutcome(kind="Image", display_name="SDXL T2I", seconds=180.0, ok=True,
                         source=GenerationSource.GENERATED, generation="alpha-1")
    assert toast_for(outcome) is None


def test_a_toast_carries_the_item_a_click_on_it_should_open():
    outcome = RunOutcome(kind="Video", display_name="WAN 2.2 I2V", seconds=252.0,
                         ok=True, source=GenerationSource.GENERATED,
                         generation="7f0c9b2e-1111-4444-8888-aaaabbbbcccc")
    assert toast_for(outcome).generation == "7f0c9b2e-1111-4444-8888-aaaabbbbcccc"


def test_a_failed_run_points_at_the_item_too():
    outcome = RunOutcome(kind="Video", display_name="WAN 2.2 I2V", seconds=220.0,
                         ok=False, source=GenerationSource.GENERATED, generation="beta-2")
    assert toast_for(outcome).generation == "beta-2"


def test_an_enhances_toast_points_at_the_image_it_improved():
    # An enhance's own row is folded into the image it improved the moment it
    # lands, so its own id is no way back to anything.
    row = {"workflow_name": "sdxl_t2i", "source": GenerationSource.GENERATED,
           "prompt_id": "enh-1", "enhance_of": "pic-9"}

    assert outcome_of_row(row, ok=True, seconds=99.0).generation == "pic-9"


def test_a_plain_runs_toast_points_at_the_run_itself():
    row = {"workflow_name": "sdxl_t2i", "source": GenerationSource.GENERATED,
           "prompt_id": "pic-9"}

    assert outcome_of_row(row, ok=True, seconds=99.0).generation == "pic-9"


def test_a_finished_training_says_its_fixs_lora_is_ready_and_how_long_it_took():
    outcome = RunOutcome(kind="Training", display_name="Hands fix", seconds=2952.0, ok=True,
                         source="", generation="")
    toast = toast_for(outcome)
    assert (toast.title, toast.body, toast.ok) == ("LoRA ready", "Hands fix · 49:12", True)


def test_a_training_that_stopped_says_the_training_failed():
    outcome = RunOutcome(kind="Training", display_name="Hands fix", seconds=600.0, ok=False,
                         source="", generation="")
    toast = toast_for(outcome)
    assert (toast.title, toast.body, toast.ok) == (
        "Training failed", "Hands fix · stopped after 10:00", False)


def test_a_training_that_stopped_at_once_interrupts_nobody():
    outcome = RunOutcome(kind="Training", display_name="Hands fix", seconds=5.0, ok=False,
                         source="", generation="")
    assert toast_for(outcome) is None
