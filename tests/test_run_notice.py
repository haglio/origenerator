from __future__ import annotations

from origenerator.generation_state import GenerationSource
from origenerator.run_notice import RunOutcome, notice_for, outcome_of_row


def test_a_video_over_in_seconds_is_not_worth_interrupting_for():
    outcome = RunOutcome(kind="Video", display_name="WAN 2.2 I2V", seconds=40.0, ok=True,
                         source=GenerationSource.GENERATED, generation="alpha-1")
    assert notice_for(outcome) is None


def test_a_run_past_the_minute_says_what_landed_and_how_long_it_took():
    outcome = RunOutcome(kind="Video", display_name="WAN 2.2 I2V",
                         seconds=252.0, ok=True, source=GenerationSource.GENERATED,
                         generation="alpha-1")
    notice = notice_for(outcome)
    assert notice.title == "Video ready"
    assert notice.body == "WAN 2.2 I2V · 4:12"
    assert notice.ok


def test_a_long_run_that_died_says_so_rather_than_claiming_a_result():
    outcome = RunOutcome(kind="Video", display_name="WAN 2.2 I2V",
                         seconds=220.0, ok=False, source=GenerationSource.GENERATED,
                         generation="alpha-1")
    notice = notice_for(outcome)
    assert notice.title == "Video failed"
    assert notice.body == "WAN 2.2 I2V · stopped after 3:40"
    assert not notice.ok


def test_the_apps_own_background_work_interrupts_nobody():
    for source in (GenerationSource.EXPERIMENT, GenerationSource.BASE_RENDER):
        outcome = RunOutcome(kind="Video", display_name="WAN 2.2 I2V",
                             seconds=600.0, ok=True, source=source,
                             generation="alpha-1")
        assert notice_for(outcome) is None


def test_an_enhancement_interrupts_nobody_however_long_it_ran():
    for ok in (True, False):
        outcome = RunOutcome(kind="Enhance", display_name="Image Enhance", seconds=600.0, ok=ok,
                             source=GenerationSource.GENERATED, generation="alpha-1")
        assert notice_for(outcome) is None


def test_an_image_interrupts_nobody_however_long_it_ran():
    outcome = RunOutcome(kind="Image", display_name="SDXL T2I", seconds=180.0, ok=True,
                         source=GenerationSource.GENERATED, generation="alpha-1")
    assert notice_for(outcome) is None


def test_a_notice_carries_the_item_a_click_on_it_should_open():
    outcome = RunOutcome(kind="Video", display_name="WAN 2.2 I2V", seconds=252.0,
                         ok=True, source=GenerationSource.GENERATED,
                         generation="7f0c9b2e-1111-4444-8888-aaaabbbbcccc")
    assert notice_for(outcome).generation == "7f0c9b2e-1111-4444-8888-aaaabbbbcccc"


def test_a_failed_run_points_at_the_item_too():
    outcome = RunOutcome(kind="Video", display_name="WAN 2.2 I2V", seconds=220.0,
                         ok=False, source=GenerationSource.GENERATED, generation="beta-2")
    assert notice_for(outcome).generation == "beta-2"


def test_an_enhances_notice_points_at_the_image_it_improved():
    # An enhance's own row is folded into the image it improved the moment it
    # lands, so its own id is no way back to anything.
    row = {"workflow_name": "sdxl_t2i", "source": GenerationSource.GENERATED,
           "prompt_id": "enh-1", "enhance_of": "pic-9"}

    assert outcome_of_row(row, ok=True, seconds=99.0).generation == "pic-9"


def test_a_plain_runs_notice_points_at_the_run_itself():
    row = {"workflow_name": "sdxl_t2i", "source": GenerationSource.GENERATED,
           "prompt_id": "pic-9"}

    assert outcome_of_row(row, ok=True, seconds=99.0).generation == "pic-9"


def test_a_finished_training_says_its_fixs_lora_is_ready_and_how_long_it_took():
    outcome = RunOutcome(kind="Training", display_name="Hands fix", seconds=2952.0, ok=True,
                         source="", generation="")
    notice = notice_for(outcome)
    assert (notice.title, notice.body, notice.ok) == ("LoRA ready", "Hands fix · 49:12", True)


def test_a_training_that_stopped_says_the_training_failed():
    outcome = RunOutcome(kind="Training", display_name="Hands fix", seconds=600.0, ok=False,
                         source="", generation="")
    notice = notice_for(outcome)
    assert (notice.title, notice.body, notice.ok) == (
        "Training failed", "Hands fix · stopped after 10:00", False)


def test_a_training_that_stopped_at_once_interrupts_nobody():
    outcome = RunOutcome(kind="Training", display_name="Hands fix", seconds=5.0, ok=False,
                         source="", generation="")
    assert notice_for(outcome) is None
