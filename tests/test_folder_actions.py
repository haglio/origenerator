from __future__ import annotations

import json

import pytest
from PySide6.QtWidgets import QToolButton, QWidget

from origenerator import gallery
from origenerator.db import Database, NewGeneration
from origenerator.gui.action_row import action_pills
from origenerator.gui.folder_actions import FolderActions
from origenerator.gui.pills import Pill
from origenerator.item_actions import ItemActions, actions_of
from origenerator.media import MediaType

_BOXES = {MediaType.IMAGE: ("first box",), MediaType.VIDEO: ("third box",)}
_ACTIONS = {MediaType.IMAGE: ("alpha", "beta"), MediaType.VIDEO: ("delta",)}


def _image(db, prompt_id: str, seed: int, actions: ItemActions | None = None) -> dict:
    db.insert_generation(NewGeneration(prompt_id=prompt_id, workflow_name="sdxl_t2i",
                                       workflow_version="v1", seed=seed, workflow_json="{}",
                                       params_json=json.dumps({"positive_prompt": "a red kite",
                                                               "seed": seed})))
    db.update_generation(prompt_id, status="completed",
                         output_files=json.dumps([{"filename": f"{prompt_id}.png", "subfolder": ""}]))
    if actions is not None:
        db.set_actions(prompt_id, MediaType.IMAGE, actions)
    return db.get_generation(prompt_id)


@pytest.fixture
def library(tmp_path):
    return Database(tmp_path / "gallery.db")


@pytest.fixture
def folder_actions(qtbot, library):
    made = FolderActions(library, checkboxes=_BOXES, actions=_ACTIONS,
                         open_setter=lambda *_args, **_kwargs: QWidget())
    qtbot.addWidget(made)
    return made


def _pills(made) -> list[Pill]:
    return made.findChild(QWidget, action_pills(MediaType.IMAGE)).findChildren(Pill)


def _partial(pill: Pill) -> bool:
    return pill.text() in pill.parentWidget().partial()


def test_a_leaf_folder_shows_the_actions_of_every_item_in_it(folder_actions, library):
    rows = [_image(library, "one", 1, ItemActions(("alpha",))), _image(library, "two", 2)]

    folder_actions.show_folder(gallery.SettingsGroup("k", "S", rows))

    assert (folder_actions.isHidden(),
            [(pill.text(), _partial(pill)) for pill in _pills(folder_actions)]) == (
        False, [("alpha", True)])


def test_a_folder_that_is_no_leaf_folder_shows_none(folder_actions, library):
    rows = [_image(library, "one", 1)]
    folder_actions.show_folder(gallery.SettingsGroup("k", "S", rows))

    folder_actions.show_folder(None)

    assert folder_actions.isHidden()


def test_actions_set_on_the_folder_are_saved_on_every_item_and_announced(folder_actions, library, qtbot):
    rows = [_image(library, "one", 1, ItemActions(("alpha",))),
            _image(library, "two", 2, ItemActions(("alpha", "beta")))]
    folder_actions.show_folder(gallery.SettingsGroup("k", "S", rows))
    alpha = _pills(folder_actions)[0]

    with qtbot.waitSignal(folder_actions.saved) as caught:
        alpha.findChild(QToolButton).click()

    assert [actions_of(library.get_generation(prompt_id), MediaType.IMAGE).actions
            for prompt_id in ("one", "two")] == [(), ("beta",)]
    assert caught.args[0] == MediaType.IMAGE
