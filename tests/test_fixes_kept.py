from __future__ import annotations

from PIL import Image
from PIL.PngImagePlugin import PngInfo

from origenerator import fixes_kept

SIZE = (100, 100)
PLAIN, FACE_FIXED, HAND_FIXED, EYES_FIXED = (10, 10, 10), (200, 0, 0), (0, 200, 0), (0, 0, 200)
FACE_BOX, HAND_BOX, EYES_BOX = (10, 10, 40, 40), (60, 60, 90, 90), (15, 15, 30, 20)
IN_THE_FACE, IN_THE_HAND, IN_THE_EYES = (35, 35), (70, 70), (20, 17)
BETWEEN_TWO_HANDS = (50, 50)


def stage(tmp_path, name: str, *redrawn) -> object:
    image = Image.new("RGB", SIZE, PLAIN)
    for box, color in redrawn:
        image.paste(color, box)
    path = tmp_path / f"{name}.png"
    image.save(path)
    return path


def an_enhancement_with_three_fixes(tmp_path):
    face, hand, eyes = (FACE_BOX, FACE_FIXED), (HAND_BOX, HAND_FIXED), (EYES_BOX, EYES_FIXED)
    stages = [stage(tmp_path, "before faces"), stage(tmp_path, "before hands", face),
              stage(tmp_path, "before eyes", face, hand),
              stage(tmp_path, "enhanced", face, hand, eyes)]
    kept = tmp_path / "kept" / "run-1"
    return stages[-1], kept, fixes_kept.keep(stages, ["faces", "hands", "eyes"], kept)


def _switch(image, kept, at: int, box, *, on: bool, off=("hands",)) -> bool:
    before = fixes_kept.opened(image)
    redrawn = fixes_kept.with_the_fix(before.image, kept, at, box, on=on)
    if redrawn is None:
        return False
    fixes_kept.write_over(fixes_kept.Redrawn(redrawn, before.written_inside), kept, image,
                          [] if on else list(off))
    return True


def colors_at(path, *points) -> list:
    with Image.open(path) as image:
        return [image.getpixel(point) for point in points]


def test_each_fix_is_kept_as_where_it_drew_and_which_earlier_fixes_it_drew_over(tmp_path):
    _enhanced, _kept, fixes = an_enhancement_with_three_fixes(tmp_path)

    assert fixes == [{"part": "faces", "box": list(FACE_BOX), "over": []},
                     {"part": "hands", "box": list(HAND_BOX), "over": []},
                     {"part": "eyes", "box": list(EYES_BOX), "over": ["faces"]}]


def test_switching_a_fix_off_puts_back_what_was_under_it_and_leaves_the_other_fixes(tmp_path):
    enhanced, kept, fixes = an_enhancement_with_three_fixes(tmp_path)

    assert _switch(enhanced, kept, 1, fixes[1]["box"], on=False)

    assert colors_at(enhanced, IN_THE_FACE, IN_THE_HAND, IN_THE_EYES) == [
        FACE_FIXED, PLAIN, EYES_FIXED]


def test_switching_a_fix_back_on_draws_it_again(tmp_path):
    enhanced, kept, fixes = an_enhancement_with_three_fixes(tmp_path)
    _switch(enhanced, kept, 1, fixes[1]["box"], on=False)

    _switch(enhanced, kept, 1, fixes[1]["box"], on=True)

    assert colors_at(enhanced, IN_THE_HAND) == [HAND_FIXED]


def test_a_fix_puts_back_only_what_it_changed_however_far_apart_its_places_are(tmp_path):
    two_hands = ((0, 0, 20, 20), HAND_FIXED), ((80, 80, 100, 100), HAND_FIXED)
    between = (BETWEEN_TWO_HANDS[0] - 5, BETWEEN_TWO_HANDS[1] - 5,
               BETWEEN_TWO_HANDS[0] + 5, BETWEEN_TWO_HANDS[1] + 5)
    stages = [stage(tmp_path, "before hands"), stage(tmp_path, "before faces", *two_hands),
              stage(tmp_path, "enhanced", *two_hands, (between, FACE_FIXED))]
    kept = tmp_path / "kept"

    fixes = fixes_kept.keep(stages, ["hands", "faces"], kept)
    _switch(stages[-1], kept, 0, fixes[0]["box"], on=False)

    assert fixes[1]["over"] == []
    assert colors_at(stages[-1], (10, 10), BETWEEN_TWO_HANDS, (90, 90)) == [
        PLAIN, FACE_FIXED, PLAIN]


def test_a_fix_that_changed_nothing_keeps_no_place(tmp_path):
    stages = [stage(tmp_path, "before"), stage(tmp_path, "enhanced")]
    kept = tmp_path / "kept"

    assert fixes_kept.keep(stages, ["teeth"], kept) == [
        {"part": "teeth", "box": None, "over": []}]
    assert not kept.exists()


def test_a_change_in_one_color_alone_is_still_a_change(tmp_path):
    a_shade_bluer = (PLAIN[0], PLAIN[1], PLAIN[2] + 1)
    stages = [stage(tmp_path, "before"),
              stage(tmp_path, "enhanced", ((10, 10, 11, 11), a_shade_bluer))]

    assert fixes_kept.keep(stages, ["skin"], tmp_path / "kept")[0]["box"] == [10, 10, 11, 11]


def test_stages_of_two_sizes_keep_nothing(tmp_path):
    small = tmp_path / "small.png"
    Image.new("RGB", (50, 50), PLAIN).save(small)

    assert fixes_kept.keep([small, stage(tmp_path, "enhanced")], ["faces"],
                           tmp_path / "kept") == []


def test_a_switch_keeps_the_note_written_inside_the_image(tmp_path):
    enhanced, kept, fixes = an_enhancement_with_three_fixes(tmp_path)
    note = PngInfo()
    note.add_text("made_up_note", "kept")
    with Image.open(enhanced) as image:
        image.save(enhanced, pnginfo=note)

    _switch(enhanced, kept, 1, fixes[1]["box"], on=False)

    with Image.open(enhanced) as image:
        assert image.info.get("made_up_note") == "kept"


def test_a_switch_whose_kept_pieces_are_gone_leaves_the_image_alone(tmp_path):
    enhanced, kept, fixes = an_enhancement_with_three_fixes(tmp_path)
    (kept / "1_before.png").unlink()

    assert not _switch(enhanced, kept, 1, fixes[1]["box"], on=False)
    assert colors_at(enhanced, IN_THE_HAND) == [HAND_FIXED]


def test_what_was_kept_sits_beside_the_thumbnails(tmp_path):
    assert fixes_kept.folder_beside(tmp_path / "thumbnails") == tmp_path / "kept from fixes"


def test_a_switch_redraws_an_image_another_program_holds_open(tmp_path):
    enhanced, kept, fixes = an_enhancement_with_three_fixes(tmp_path)

    with open(enhanced, "rb"):
        assert _switch(enhanced, kept, 1, fixes[1]["box"], on=False), (
            "a slideshow showing the image holds it open, and Windows replaces no file held open")

    assert colors_at(enhanced, IN_THE_HAND) == [PLAIN]


def test_drawing_a_fix_off_leaves_the_image_it_was_drawn_from_as_it_was(tmp_path):
    enhanced, kept, fixes = an_enhancement_with_three_fixes(tmp_path)
    before = fixes_kept.opened(enhanced)

    redrawn = fixes_kept.with_the_fix(before.image, kept, 1, fixes[1]["box"], on=False)

    assert (redrawn.getpixel(IN_THE_HAND), before.image.getpixel(IN_THE_HAND)) == (
        PLAIN, HAND_FIXED), "the screen and the writer each hold their own image"
    assert colors_at(enhanced, IN_THE_HAND) == [HAND_FIXED]


def test_an_image_written_over_leaves_a_whole_copy_saying_which_fixes_are_off_until_forgotten(
        tmp_path):
    enhanced, kept, fixes = an_enhancement_with_three_fixes(tmp_path)
    _switch(enhanced, kept, 2, fixes[2]["box"], on=False, off=("eyes",))
    Image.new("RGB", SIZE, FACE_FIXED).save(enhanced)

    assert fixes_kept.finish_what_was_written(kept, enhanced) == ["eyes"]

    assert colors_at(enhanced, IN_THE_EYES, IN_THE_HAND) == [FACE_FIXED, HAND_FIXED], (
        "a write cut short part way through the image is finished from the whole copy")
    fixes_kept.forget_what_was_written(kept, enhanced)
    assert fixes_kept.finish_what_was_written(kept, enhanced) is None


def test_only_the_last_image_written_over_is_kept_to_finish_from(tmp_path):
    enhanced, kept, fixes = an_enhancement_with_three_fixes(tmp_path)
    _switch(enhanced, kept, 2, fixes[2]["box"], on=False, off=("eyes",))

    _switch(enhanced, kept, 2, fixes[2]["box"], on=True)

    assert fixes_kept.finish_what_was_written(kept, enhanced) == []
    assert len([left for left in kept.iterdir() if "enhanced.png" in left.name]) == 1


def test_an_image_never_written_over_has_nothing_to_finish(tmp_path):
    enhanced, kept, _fixes = an_enhancement_with_three_fixes(tmp_path)

    assert fixes_kept.finish_what_was_written(kept, enhanced) is None
