from __future__ import annotations

import json

from origenerator.gallery.source_image import image_actions_row, inherits_image_actions
from origenerator.generation_state import GenerationSource
from origenerator.item_actions import (
    ItemActions,
    actions_of,
    combined_actions,
    has_actions,
    stored,
)
from origenerator.media import MediaType


def test_an_item_reads_its_own_actions_and_checked_boxes_for_each_side():
    row = {"image_actions": json.dumps(["alpha", "beta"]), "image_checked": json.dumps(["box"]),
           "video_actions": json.dumps(["gamma"]), "video_checked": None}

    assert actions_of(row, MediaType.IMAGE) == ItemActions(("alpha", "beta"), ("box",))
    assert actions_of(row, MediaType.VIDEO) == ItemActions(("gamma",), ())


def test_an_item_nobody_has_given_actions_reads_as_nothing_and_says_so():
    row = {"image_actions": None, "image_checked": None}

    assert (actions_of(row, MediaType.IMAGE), has_actions(row, MediaType.IMAGE)) == (ItemActions(), False)


def test_an_item_given_no_actions_still_counts_as_answered():
    row = {"video_actions": "[]", "video_checked": json.dumps(["box"])}

    assert has_actions(row, MediaType.VIDEO) is True


def test_a_column_that_does_not_hold_a_list_of_names_reads_as_nothing():
    row = {"image_actions": "not json", "image_checked": json.dumps({"box": 1})}

    assert actions_of(row, MediaType.IMAGE) == ItemActions()


def test_actions_are_saved_as_the_lists_they_are_read_back_from():
    item_actions = ItemActions(("alpha", "beta"), ("box",))

    actions, checked = stored(item_actions)

    assert actions_of({"image_actions": actions, "image_checked": checked},
                     MediaType.IMAGE) == item_actions


def test_an_items_actions_are_its_images_then_its_videos_each_named_once():
    image = ItemActions(("alpha", "beta"))
    video = ItemActions(("beta", "gamma"))

    assert combined_actions(image, video) == ("alpha", "beta", "gamma")


def _video(source=GenerationSource.GENERATED):
    return {"prompt_id": "vid", "source": source}


def test_a_video_made_from_an_image_takes_its_image_actions_from_that_image():
    image = {"prompt_id": "img", "source": GenerationSource.GENERATED}

    assert image_actions_row(_video(), image) is image
    assert inherits_image_actions(_video(), image) is True


def test_a_video_made_from_no_image_holds_its_own_image_actions():
    video = _video()

    assert image_actions_row(video, None) is video
    assert inherits_image_actions(video, None) is False


def test_a_video_brought_in_holds_the_image_actions_of_the_frame_taken_from_it():
    frame = {"prompt_id": "frame", "source": GenerationSource.STARTING_FRAME}
    video = _video(GenerationSource.OUTSIDE)

    assert image_actions_row(video, frame) is frame
    assert inherits_image_actions(video, frame) is False


def test_a_video_made_here_from_a_frame_taken_from_another_video_inherits_its_actions():
    frame = {"prompt_id": "frame", "source": GenerationSource.STARTING_FRAME}

    assert inherits_image_actions(_video(), frame) is True
