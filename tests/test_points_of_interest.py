"""The places an enhancement's fixes found, as the app keeps them with the file they were found in."""
from __future__ import annotations

import json

from origenerator import points_of_interest
from origenerator.workflows.detail_parts import DetailPart

FACE = {"left": 0.1, "top": 0.1, "right": 0.3, "bottom": 0.5}
HAND = {"left": 0.6, "top": 0.5, "right": 0.9, "bottom": 0.9}
EYES = DetailPart("eyes", ("eye", "eyes"), ("eye",), framed_together=True)
WHOLE = (0, 0, 1000, 1000)


def report(*regions) -> dict:
    return {"text": [json.dumps(list(region)) for region in regions]}


def test_eyes_a_fix_found_close_together_are_framed_as_one_place():
    outputs = {"fix0_points": report((100, 100, 400, 300), (300, 120, 600, 320), WHOLE)}

    assert points_of_interest.reported(outputs, {0: EYES}) == [
        {"left": 0.1, "top": 0.1, "right": 0.6, "bottom": 0.32, "part": "eyes"}]


def test_eyes_far_apart_are_framed_apart():
    outputs = {"fix0_points": report((100, 100, 200, 200), (700, 100, 800, 200), WHOLE)}

    assert [place["left"] for place in points_of_interest.reported(outputs, {0: EYES})] == [0.1, 0.7]


def test_places_of_a_part_framed_one_by_one_stay_apart_however_close():
    hands = DetailPart("hands", ("hand",), ("hand",))
    outputs = {"fix1_points": report((100, 100, 400, 300), (300, 120, 600, 320), WHOLE)}

    assert points_of_interest.reported(outputs, {1: hands}) == [
        {"left": 0.1, "top": 0.1, "right": 0.4, "bottom": 0.3, "part": "hands"},
        {"left": 0.3, "top": 0.12, "right": 0.6, "bottom": 0.32, "part": "hands"}]


def test_a_files_places_come_back_as_the_boxes_a_funestra_frames_in_the_order_they_were_found():
    entry = {"filename": "enhanced.png", points_of_interest.FILE_KEY: [FACE, HAND]}

    assert points_of_interest.boxes_of(entry) == ((0.1, 0.1, 0.3, 0.5), (0.6, 0.5, 0.9, 0.9))


def test_a_file_no_fix_found_anything_in_has_no_places():
    assert points_of_interest.boxes_of({"filename": "base.png"}) == ()


def test_a_place_written_in_a_shape_no_fix_writes_is_passed_over():
    entry = {"filename": "enhanced.png", points_of_interest.FILE_KEY: [{"left": 0.1}, None, FACE]}

    assert points_of_interest.boxes_of(entry) == ((0.1, 0.1, 0.3, 0.5),)


def test_a_report_that_never_says_how_big_the_picture_is_gives_no_places():
    outputs = {"fix0_points": {"text": [json.dumps([0, 0, 0, 0])]}}

    assert points_of_interest.reported(outputs) == []


def test_a_run_whose_only_text_is_no_report_of_a_fix_reported_nothing():
    outputs = {"12": {"text": [json.dumps([0, 0, 10, 10]), json.dumps([0, 0, 20, 20])]}}

    assert points_of_interest.reported(outputs) is None


def test_every_pass_shares_one_measure_of_the_picture_it_ran_on():
    first = points_of_interest.report_nodes(0, ["fix0_segs", 0], ["enh_decode", 0])
    second = points_of_interest.report_nodes(1, ["fix1_segs", 0], ["enh_decode", 0])

    shared = first.keys() & second.keys()

    assert {first[node]["class_type"] for node in shared} == {"GetImageSize", "SolidMask", "MaskToSEGS"}
    assert all(first[node] == second[node] for node in shared)
