from __future__ import annotations

import statistics
import time
from dataclasses import dataclass
from typing import NamedTuple


def execution_duration_seconds(history_data: dict) -> float | None:
    # ComfyUI's history lacks the start and success pair for a prompt that errored or is
    # still running, and on older servers.
    messages = history_data.get("status", {}).get("messages", [])
    start = end = None
    for event, data in messages:
        timestamp = data.get("timestamp")
        if event == "execution_start":
            start = timestamp
        elif event == "execution_success":
            end = timestamp
    if start is None or end is None:
        return None
    return (end - start) / 1000.0


def elapsed_since(started_at: float | None, *, now=time.time) -> float | None:
    if started_at is None:
        return None
    return max(0.0, now() - started_at)


def estimate_seconds(durations: list[float]) -> float | None:
    if not durations:
        return None
    return statistics.median(durations)


def average_seconds(durations: list[float]) -> float | None:
    if not durations:
        return None
    return statistics.fmean(durations)


def clock_duration(seconds: float) -> str:
    total = max(0, int(seconds))
    hours, remainder = divmod(total, _SECONDS_PER_HOUR)
    minutes, secs = divmod(remainder, _SECONDS_PER_MINUTE)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


_MODEL_LOAD_FRACTION = 0.25
_SECONDS_PER_MINUTE = 60
_MINUTES_PER_HOUR = 60
_SECONDS_PER_HOUR = _SECONDS_PER_MINUTE * _MINUTES_PER_HOUR
_PACE_MIN_STEPS = 2


class RunProgress(NamedTuple):
    done: int
    total: int

    @classmethod
    def of(cls, progress):
        # ComfyUI reports no progress for a job it has not started, and some of its nodes report no step counts.
        if not progress:
            return None
        return progress if isinstance(progress, cls) else cls(*progress)

    @property
    def percent_label(self) -> str:
        if self.total <= 0:
            return ""
        return f"{int(self.done * 100 / self.total)}%"


@dataclass(frozen=True)
class RunTiming:
    elapsed: float | None
    progress: RunProgress | None
    typical: float | None

    def __post_init__(self):
        object.__setattr__(self, "progress", RunProgress.of(self.progress))

    def _whole_run_at_this_pace(self):
        if self.progress is None or not self.elapsed or self.elapsed <= 0:
            return None
        done, total = self.progress
        if total <= 0 or done <= 0:
            return None
        if done < max(_PACE_MIN_STEPS, total * _MODEL_LOAD_FRACTION):
            return None
        return self.elapsed * total / done

    def remaining_seconds(self):
        if self.elapsed is None:
            return None
        pace = self._whole_run_at_this_pace()
        if pace is None:
            if self.typical is None:
                return None
            remaining = self.typical - self.elapsed
            return remaining if remaining >= 1 else None
        if self.typical is None or self.elapsed >= self.typical:
            return max(pace - self.elapsed, 0.0)
        done, total = self.progress
        settled = min(1.0, done / total)
        projected = settled * pace + (1.0 - settled) * self.typical
        return max(projected - self.elapsed, 0.0)

    def remaining_label(self) -> str:
        remaining = self.remaining_seconds()
        if remaining is None:
            return ""
        return "finishing" if remaining < 1 else f"~{clock_duration(remaining)} left"

    def time_label(self) -> str:
        if self.elapsed is None:
            return ""
        label = f"{clock_duration(self.elapsed)} elapsed"
        remaining = self.remaining_label()
        return f"{label} · {remaining}" if remaining else label

    def status_label(self, *, step: str = "", compact: bool = False) -> str:
        clock = self.remaining_label() if compact else self.time_label()
        percent = self.progress.percent_label if self.progress is not None else ""
        return " · ".join(part for part in (step, percent, clock) if part)


def _coarse_duration(seconds: float) -> str:
    if seconds < _SECONDS_PER_MINUTE:
        return f"{round(seconds)} sec"
    if seconds < _SECONDS_PER_HOUR:
        return f"{round(seconds / _SECONDS_PER_MINUTE)} min"
    hours, remainder = divmod(round(seconds), _SECONDS_PER_HOUR)
    minutes = round(remainder / _SECONDS_PER_MINUTE)
    if minutes == _MINUTES_PER_HOUR:
        hours, minutes = hours + 1, 0
    return f"{hours} hr {minutes} min" if minutes else f"{hours} hr"


def queue_estimate_label(seconds: float | None) -> str:
    if seconds is None:
        return "~?"
    return f"~{_coarse_duration(seconds)}"


def estimate_label(durations: list[float]) -> str:
    estimate = estimate_seconds(durations)
    if estimate is None:
        return "No timing data yet"
    return f"~{_coarse_duration(estimate)} (based on {_runs(len(durations))})"


def average_label(durations: list[float]) -> str:
    average = average_seconds(durations)
    if average is None:
        return ""
    return f"~{_coarse_duration(average)} (across {_runs(len(durations))})"


def _runs(count: int) -> str:
    return f"{count} run" if count == 1 else f"{count} runs"
