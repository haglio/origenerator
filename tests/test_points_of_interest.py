"""The places an enhancement's fixes found, as the app keeps them with the file they were found in."""
from __future__ import annotations

import json

from origenerator import points_of_interest
from origenerator.workflows.detail_parts import DetailPart

FACE = {"left": 0.1, "top": 0.1, "right": 0.3, "bottom": 0.5}
HAND = {"left": 0.6, "top": 0.5, "right": 0.9, "bottom": 0.9}
EYES = DetailPart("eyes", ("eye", "eyes"), ("eye",))
WHOLE = (0, 0, 1000, 1000)


def report(*regions) -> dict:
    return {"text": [json.dumps(list(region)) for region in regions]}


def _framed(outputs: dict, parts: dict) -> tuple:
    entry = {"filename": "enhanced.png",
             points_of_interest.FILE_KEY: points_of_interest.reported(outputs, parts)}
    return points_of_interest.boxes_of(entry, framed_together={EYES.name})


def test_eyes_a_fix_found_close_together_are_framed_as_one_place():
    outputs = {"fix0_points": report((100, 100, 400, 300), (300, 120, 600, 320), WHOLE)}

    assert _framed(outputs, {0: EYES}) == ((0.1, 0.1, 0.6, 0.32),)


def test_eyes_far_apart_are_framed_apart():
    outputs = {"fix0_points": report((100, 100, 200, 200), (700, 100, 800, 200), WHOLE)}

    assert [box[0] for box in _framed(outputs, {0: EYES})] == [0.1, 0.7]


def test_places_of_a_part_framed_one_by_one_stay_apart_however_close():
    hands = DetailPart("hands", ("hand",), ("hand",))
    outputs = {"fix1_points": report((100, 100, 400, 300), (300, 120, 600, 320), WHOLE)}

    assert _framed(outputs, {1: hands}) == ((0.1, 0.1, 0.4, 0.3), (0.3, 0.12, 0.6, 0.32))


def _eye(left, right) -> dict:
    return {"left": left, "top": 0.1, "right": right, "bottom": 0.19, "part": "eyes"}


def test_the_eyes_of_two_faces_close_together_are_framed_as_two_pairs():
    entry = {"filename": "enhanced.png", points_of_interest.FILE_KEY: [
        _eye(0.10, 0.25), _eye(0.20, 0.35), _eye(0.33, 0.48), _eye(0.43, 0.58)]}

    assert points_of_interest.boxes_of(entry, framed_together={EYES.name}) == (
        (0.1, 0.1, 0.35, 0.19), (0.33, 0.1, 0.58, 0.19))


def test_each_eye_is_paired_with_the_one_nearest_it_whatever_order_they_were_found_in():
    entry = {"filename": "enhanced.png", points_of_interest.FILE_KEY: [
        _eye(0.20, 0.35), _eye(0.33, 0.48), _eye(0.10, 0.25), _eye(0.43, 0.58)]}

    assert points_of_interest.boxes_of(entry, framed_together={EYES.name}) == (
        (0.1, 0.1, 0.35, 0.19), (0.33, 0.1, 0.58, 0.19))


def test_an_eye_is_never_framed_with_the_face_around_it():
    eye = {"left": 0.15, "top": 0.2, "right": 0.25, "bottom": 0.3, "part": "eyes"}
    entry = {"filename": "enhanced.png", points_of_interest.FILE_KEY: [eye, {**FACE, "part": "faces"}]}

    assert points_of_interest.boxes_of(entry, framed_together={EYES.name}) == (
        (0.15, 0.2, 0.25, 0.3), (0.1, 0.1, 0.3, 0.5))


def test_a_files_places_come_back_as_the_boxes_a_funestra_frames_in_the_order_they_were_found():
    entry = {"filename": "enhanced.png", points_of_interest.FILE_KEY: [FACE, HAND]}

    assert points_of_interest.boxes_of(entry, framed_together=()) == ((0.1, 0.1, 0.3, 0.5), (0.6, 0.5, 0.9, 0.9))


def test_a_file_no_fix_found_anything_in_has_no_places():
    assert points_of_interest.boxes_of({"filename": "base.png"}, framed_together=()) == ()


def test_a_place_written_in_a_shape_no_fix_writes_is_passed_over():
    entry = {"filename": "enhanced.png", points_of_interest.FILE_KEY: [{"left": 0.1}, None, FACE]}

    assert points_of_interest.boxes_of(entry, framed_together=()) == ((0.1, 0.1, 0.3, 0.5),)


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
