# ComfyUI's queue is a heap ordered by submit with no pause: a prompt on it can only be dropped or interrupted, so the line is held here and ComfyUI gets one prompt at a time
from __future__ import annotations

from origenerator.generation_state import GenerationSource
from origenerator.media import MediaType

VIDEOS_WAIT_AFTER_AN_IMAGE_S = 60.0


def is_video(job) -> bool:
    return (getattr(job, "run_media_type", None)
            or getattr(job, "media_type", None)) == MediaType.VIDEO


def _users_own(job) -> bool:
    return getattr(job, "source", GenerationSource.GENERATED) == GenerationSource.GENERATED


def takes_the_front(job) -> bool:
    return not is_video(job) and _users_own(job)


def insertion_index(line: list, job) -> int:
    return 0 if takes_the_front(job) else len(line)


def put_first(line: list, prompt_ids) -> None:
    line.sort(key=lambda job: job.prompt_id not in prompt_ids)


def waits_for(video, enhancement) -> bool:
    image = getattr(video, "start_image", "")
    return is_video(video) and bool(image) and getattr(enhancement, "enhances", "") == image


def waits_for_any(video, jobs) -> bool:
    return any(waits_for(video, job) for job in jobs)


def moved(line: list, job, before) -> list:
    order = [other for other in line if other is not job]
    order.insert(order.index(before) if before in order else len(order), job)
    at = order.index(job)
    ahead = [other for other in order[at + 1:] if waits_for(job, other)]
    behind = [other for other in order[:at] if waits_for(other, job)]
    rest = [other for other in order if other not in ahead and other not in behind]
    at = rest.index(job)
    return rest[:at] + ahead + [job] + behind + rest[at + 1:]


def rejoin_index(line: list, job, newcomer) -> int:
    if not _users_own(job):
        return len(line)
    if takes_the_front(job):
        return 1 + next((index for index, other in enumerate(line) if other is newcomer), -1)
    return 1 + max((index for index, other in enumerate(line) if takes_the_front(other)),
                   default=-1)


def wait_before_starting(job, seconds_since_an_image: float | None) -> float:
    if seconds_since_an_image is None or not is_video(job):
        return 0.0
    return max(0.0, VIDEOS_WAIT_AFTER_AN_IMAGE_S - seconds_since_an_image)
