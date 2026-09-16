from __future__ import annotations

from origenerator.generation_state import GenerationSource
from origenerator.run_notice import RunOutcome, notice_for


def test_a_run_over_in_seconds_is_not_worth_interrupting_for():
    outcome = RunOutcome(kind="Image", recipe="SDXL Text-to-Image", seconds=12.0, ok=True,
                         source=GenerationSource.GENERATED)
    assert notice_for(outcome) is None


def test_a_run_past_the_minute_says_what_landed_and_how_long_it_took():
    outcome = RunOutcome(kind="Video", recipe="WAN 2.2 Image-to-Video",
                         seconds=252.0, ok=True, source=GenerationSource.GENERATED)
    notice = notice_for(outcome)
    assert notice.title == "Video ready"
    assert notice.body == "WAN 2.2 Image-to-Video · 4:12"
    assert notice.ok


def test_a_long_run_that_died_says_so_rather_than_claiming_a_result():
    outcome = RunOutcome(kind="Video", recipe="WAN 2.2 Image-to-Video",
                         seconds=220.0, ok=False, source=GenerationSource.GENERATED)
    notice = notice_for(outcome)
    assert notice.title == "Video failed"
    assert notice.body == "WAN 2.2 Image-to-Video · stopped after 3:40"
    assert not notice.ok


def test_the_apps_own_background_work_interrupts_nobody():
    for source in (GenerationSource.EXPERIMENT, GenerationSource.BASE_RENDER):
        outcome = RunOutcome(kind="Video", recipe="WAN 2.2 Image-to-Video",
                             seconds=600.0, ok=True, source=source)
        assert notice_for(outcome) is None
