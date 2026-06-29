from datetime import datetime, timezone

from origenerator.db import Database
from origenerator.log_backfill import (
    backfill_durations_from_logs,
    parse_log_durations,
)


def _local_epoch(y, mo, d, h, mi, s, us=0):
    return datetime(y, mo, d, h, mi, s, us).timestamp()


def _utc_iso_for_local(y, mo, d, h, mi, s, us=0):
    """The completed_at an importer would store for a file written at this
    local wall-clock time (mtime -> UTC isoformat)."""
    epoch = datetime(y, mo, d, h, mi, s, us).timestamp()
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()


def _import_row(db, prompt_id, completed_at):
    db.insert_generation(prompt_id=prompt_id, workflow_name="sdxl_t2i",
                         workflow_version="imported", params_json="{}",
                         workflow_json="{}", source="imported")
    db.update_generation(prompt_id, status="completed", completed_at=completed_at)


def test_parse_log_durations_extracts_timestamp_and_duration():
    text = (
        "[2026-06-29 12:20:53.244] Prompt executed in 15.26 seconds\n"
        "[2026-06-29 12:21:00.000] Some unrelated log line\n"
        "[2026-06-29 12:33:57.623] Prompt executed in 0.79 seconds\n"
    )
    result = parse_log_durations(text)
    assert result == [
        (_local_epoch(2026, 6, 29, 12, 20, 53, 244000), 15.26),
        (_local_epoch(2026, 6, 29, 12, 33, 57, 623000), 0.79),
    ]


def test_parse_log_durations_ignores_lines_without_the_marker():
    assert parse_log_durations("[2026-06-29 12:00:00.000] Startup complete\n") == []


def test_backfill_matches_rows_to_nearest_log_line(tmp_path):
    db = Database(tmp_path / "test.db")
    # Two imported rows; completed_at is the file mtime as the importer stores it.
    _import_row(db, "rowA", _utc_iso_for_local(2026, 6, 29, 12, 20, 53, 244000))
    _import_row(db, "rowB", _utc_iso_for_local(2026, 6, 29, 12, 33, 57))

    # Log lines land a beat after each file; an extra line matches no row.
    log = tmp_path / "comfyui.log"
    log.write_text(
        "[2026-06-29 09:00:00.000] Prompt executed in 99.00 seconds\n"
        "[2026-06-29 12:20:55.000] Prompt executed in 15.26 seconds\n"
        "[2026-06-29 12:33:57.623] Prompt executed in 0.79 seconds\n"
    )

    matched = backfill_durations_from_logs(db, [log])

    assert matched == 2
    assert db.get_generation("rowA")["duration_seconds"] == 15.26
    assert db.get_generation("rowB")["duration_seconds"] == 0.79


def test_backfill_leaves_unmatched_rows_untouched(tmp_path):
    db = Database(tmp_path / "test.db")
    _import_row(db, "lonely", _utc_iso_for_local(2026, 6, 29, 12, 0, 0))

    log = tmp_path / "comfyui.log"
    log.write_text("[2026-06-29 12:30:00.000] Prompt executed in 5.00 seconds\n")

    assert backfill_durations_from_logs(db, [log]) == 0
    assert db.get_generation("lonely")["duration_seconds"] is None


def test_backfill_does_not_reuse_one_line_for_two_rows(tmp_path):
    db = Database(tmp_path / "test.db")
    # A batch run: two files share one prompt, so one "executed" line. Only one
    # row may claim it; the other stays NULL rather than double-counting.
    _import_row(db, "batch1", _utc_iso_for_local(2026, 6, 29, 12, 20, 53))
    _import_row(db, "batch2", _utc_iso_for_local(2026, 6, 29, 12, 20, 53))

    log = tmp_path / "comfyui.log"
    log.write_text("[2026-06-29 12:20:53.500] Prompt executed in 15.26 seconds\n")

    assert backfill_durations_from_logs(db, [log]) == 1
    durations = sorted(
        db.get_generation(p)["duration_seconds"] is not None
        for p in ("batch1", "batch2")
    )
    assert durations == [False, True]
