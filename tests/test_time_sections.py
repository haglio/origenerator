from __future__ import annotations

from datetime import UTC, date, timedelta, timezone

from origenerator import gallery

_TODAY = date(2026, 9, 12)


def _headings(*created_at):
    rows = [{"prompt_id": f"g{n}", "created_at": stamp} for n, stamp in enumerate(created_at)]
    return gallery.section_headings(rows, zone=UTC, today=_TODAY)


def test_rows_made_minutes_apart_share_one_heading_spanning_them():
    assert _headings("2026-09-12 19:40:00", "2026-09-12 19:35:00", "2026-09-12 19:10:00") \
        == ["Sat Sep 12, 7:10 PM – 7:40 PM", None, None]


def test_two_hours_between_one_row_and_the_next_opens_a_new_section():
    assert _headings("2026-09-12 23:00:00", "2026-09-12 22:50:00",
                     "2026-09-12 20:50:00", "2026-09-12 20:30:00") \
        == ["Sat Sep 12, 10:50 PM – 11:00 PM", None, "Sat Sep 12, 8:30 PM – 8:50 PM", None]


def test_a_section_that_runs_past_midnight_stays_whole_and_names_both_days():
    assert _headings("2026-09-13 01:25:00", "2026-09-13 00:10:00", "2026-09-12 23:10:00") \
        == ["Sat Sep 12, 11:10 PM – Sun Sep 13, 1:25 AM", None, None]


def test_a_section_made_inside_one_minute_names_that_minute_alone():
    assert _headings("2026-09-12 19:40:30", "2026-09-12 19:40:05") == ["Sat Sep 12, 7:40 PM", None]


def test_a_section_from_an_earlier_year_names_its_year():
    assert _headings("2025-12-31 22:00:00", "2025-12-31 21:15:00") \
        == ["Wed Dec 31 2025, 9:15 PM – 10:00 PM", None]


def test_an_older_image_an_enhancement_lifted_to_the_top_joins_the_section_it_landed_in():
    assert _headings("2026-09-01 15:00:00", "2026-09-12 19:40:00", "2026-09-12 19:30:00") \
        == ["Sat Sep 12, 7:30 PM – 7:40 PM", None, None]


def test_a_listing_whose_rows_do_not_all_say_when_they_were_made_gets_no_headings():
    rows = [{"prompt_id": "g1", "created_at": "2026-09-12 19:40:00"}, {"prompt_id": "g2"}]
    assert gallery.section_headings(rows, zone=UTC, today=_TODAY) == [None, None]


def test_the_database_keeps_times_in_utc_and_the_heading_shows_them_on_the_viewers_clock():
    rows = [{"prompt_id": "g1", "created_at": "2026-09-13 02:39:00"},
            {"prompt_id": "g2", "created_at": "2026-09-13 02:10:00"}]
    pacific_daylight = timezone(timedelta(hours=-7))

    assert gallery.section_headings(rows, zone=pacific_daylight, today=_TODAY) \
        == ["Sat Sep 12, 7:10 PM – 7:39 PM", None]
