from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from origenerator.db import Database, NewGeneration
from origenerator.gallery_edits import GalleryEdits, GalleryEnvironment
from origenerator.output_places import OutputPlaces
from origenerator.trash import Genau, Kino, Trash, TrashedBatch

MADE = "wan22_i2v_00007_.mp4"
IN_GENAU = "wan22_i2v_00007__topaz.mp4"


@dataclass
class Library:
    root: Path
    ended: list = field(default_factory=list)
    brought_in: list = field(default_factory=list)
    gives_entries: bool = True

    def __post_init__(self):
        self.db = Database(self.root / "test.db")
        self.output = self.root / "output"
        self.kino = Kino(library=self.root / "upscaled", trash=self.root / "kino trash",
                         own_source="origenerator")
        self.flicks = self.root / "genau" / "flicks"
        self.genau = Genau(self.flicks)
        self.genau_trash = self.root / "genau" / "trash"
        self.edits = GalleryEdits(
            self.db, OutputPlaces.in_one_folder(self.output), Trash(self.root / "trash"),
            environment=GalleryEnvironment(kino=self.kino, genau=self.genau,
                                           bring_in=self._bring_in,
                                           delete_for_good=self.ended.append))

    def _bring_in(self, video: Path) -> bool:
        self.brought_in.append(video)
        if self.gives_entries:
            self.entry_for("brought", video)
        return self.gives_entries

    def entry_for(self, prompt_id: str, video: Path) -> None:
        self.db.insert_generation(NewGeneration(
            prompt_id=prompt_id, workflow_name="outside_video", workflow_version="outside",
            params_json="{}", workflow_json="{}"))
        self.db.update_generation(prompt_id, status="completed", output_files=json.dumps(
            [{"filename": video.name, "library_path": str(video)}]))

    def made_here(self, prompt_id: str = "v1") -> Path:
        made = self.output / "video" / MADE
        made.parent.mkdir(parents=True, exist_ok=True)
        made.write_bytes(b"made here")
        self.db.insert_generation(NewGeneration(
            prompt_id=prompt_id, workflow_name="wan22_i2v", workflow_version="v001",
            params_json="{}", workflow_json="{}"))
        self.db.update_generation(prompt_id, status="completed", output_files=json.dumps(
            [{"filename": MADE, "subfolder": "video"}]))
        return made

    def in_kino(self, *parts: str, content: bytes = b"kino video") -> Path:
        video = self.kino.library.joinpath(*parts)
        video.parent.mkdir(parents=True, exist_ok=True)
        video.write_bytes(content)
        return video

    def in_genau(self, *parts: str, content: bytes = b"genau video") -> Path:
        video = self.flicks.joinpath("2D", *parts)
        video.parent.mkdir(parents=True, exist_ok=True)
        video.write_bytes(content)
        return video

    def trashed_ids(self) -> list[str]:
        return [record["prompt_id"] for record in self.db.list_trashed()]


class TestAKinoVideoTheGalleryHasNoEntryFor:
    def test_it_is_given_an_entry_and_sent_to_trash_with_it(self, tmp_path):
        library = Library(tmp_path)
        stranger = library.in_kino("landscape", "sample site", "video two.mp4")

        library.edits.trash_file(stranger)

        assert library.brought_in == [stranger]
        assert library.trashed_ids() == ["brought"]
        assert (library.kino.trash / stranger.name).read_bytes() == b"kino video"

    def test_restore_brings_it_back_to_kino_with_its_entry(self, tmp_path):
        library = Library(tmp_path)
        stranger = library.in_kino("landscape", "sample site", "video two.mp4")
        library.edits.trash_file(stranger)

        library.edits.restore_deleted(["brought"])

        assert stranger.read_bytes() == b"kino video"
        assert library.db.get_generation("brought") is not None

    def test_one_that_cannot_be_given_an_entry_stays_in_kino(self, tmp_path):
        library = Library(tmp_path, gives_entries=False)
        stranger = library.in_kino("landscape", "sample site", "video two.mp4")

        library.edits.trash_file(stranger)

        assert stranger.read_bytes() == b"kino video"
        assert library.trashed_ids() == []

    def test_a_file_outside_kino_is_never_given_one(self, tmp_path):
        library = Library(tmp_path)
        elsewhere = tmp_path / "elsewhere" / "video two.mp4"
        elsewhere.parent.mkdir()
        elsewhere.write_bytes(b"another video")

        library.edits.trash_file(elsewhere)

        assert library.brought_in == []
        assert elsewhere.read_bytes() == b"another video"


class TestAGenauVideo:
    def test_one_genau_already_moved_to_its_trash_sends_its_entry_there(self, tmp_path):
        library = Library(tmp_path)
        library.made_here()
        played = library.flicks / "2D" / "AI" / IN_GENAU
        waits = library.genau_trash / "2D" / "AI" / IN_GENAU
        waits.parent.mkdir(parents=True)
        waits.write_bytes(b"genau video")

        library.edits.trash_file(played, already_at=waits)

        assert library.trashed_ids() == ["v1"]
        assert waits.read_bytes() == b"genau video"

    def test_restore_puts_it_back_in_genau_where_it_played(self, tmp_path):
        library = Library(tmp_path)
        library.made_here()
        played = library.flicks / "2D" / "AI" / IN_GENAU
        waits = library.genau_trash / "2D" / "AI" / IN_GENAU
        waits.parent.mkdir(parents=True)
        waits.write_bytes(b"genau video")
        library.edits.trash_file(played, already_at=waits)

        library.edits.restore_deleted(["v1"])

        assert played.read_bytes() == b"genau video"
        assert not waits.exists()

    def test_sending_its_entry_to_trash_takes_it_out_of_genau_into_genaus_trash(self, tmp_path):
        library = Library(tmp_path)
        library.made_here()
        flick = library.in_genau("AI", "kept aside", IN_GENAU)

        library.edits.delete_rows([library.db.get_generation("v1")])

        assert not flick.exists()
        assert (library.genau_trash / "2D" / "AI" / "kept aside" / IN_GENAU).read_bytes() == (
            b"genau video")

    def test_undoing_that_puts_it_back_in_genau(self, tmp_path):
        library = Library(tmp_path)
        library.made_here()
        flick = library.in_genau("AI", IN_GENAU)
        library.edits.delete_rows([library.db.get_generation("v1")])

        library.edits.undo()

        assert flick.read_bytes() == b"genau video"

    def test_a_genau_video_of_another_entry_stays_in_genau(self, tmp_path):
        library = Library(tmp_path)
        library.made_here()
        other = library.in_genau("AI", "wan22_i2v_00008__topaz.mp4")

        library.edits.delete_rows([library.db.get_generation("v1")])

        assert other.read_bytes() == b"genau video"


class TestDeletePermanently:
    def test_it_hands_evolver_every_copy_waiting_in_kinos_and_genaus_trash(self, tmp_path):
        library = Library(tmp_path)
        library.made_here()
        library.in_kino("portrait", "origenerator", IN_GENAU, content=b"upscale")
        library.in_genau("AI", IN_GENAU)
        library.edits.delete_rows([library.db.get_generation("v1")])

        library.edits.purge_deleted(["v1"])

        assert library.ended == [[library.kino.trash / IN_GENAU,
                                  library.genau_trash / "2D" / "AI" / IN_GENAU]]
        assert library.trashed_ids() == []

    def test_several_items_go_to_evolver_in_one_go(self, tmp_path):
        library = Library(tmp_path)
        first = library.in_kino("landscape", "sample site", "video one.mp4")
        second = library.in_kino("landscape", "sample site", "video two.mp4")
        library.entry_for("v1", first)
        library.entry_for("v2", second)
        library.edits.delete_rows([library.db.get_generation("v1"), library.db.get_generation("v2")])

        library.edits.purge_deleted(["v1", "v2"])

        assert library.ended == [[library.kino.trash / "video one.mp4",
                                  library.kino.trash / "video two.mp4"]]

    def test_an_item_with_no_copy_out_of_play_asks_evolver_for_nothing(self, tmp_path):
        library = Library(tmp_path)
        library.made_here()
        library.edits.delete_rows([library.db.get_generation("v1")])

        library.edits.purge_deleted(["v1"])

        assert library.ended == []


class TestTheTrashRecord:
    def test_a_record_written_before_genau_still_restores_its_kino_copies(self, tmp_path):
        played, held = tmp_path / "kino" / "video.mp4", tmp_path / "kino trash" / "video.mp4"
        held.parent.mkdir()
        held.write_bytes(b"kino video")
        record = {"moves": [], "subdir": None, "sent_to_kino_trash": [[str(played), str(held)]]}

        TrashedBatch.from_record(record).restore()

        assert played.read_bytes() == b"kino video"

    def test_a_record_names_every_copy_taken_out_of_play(self, tmp_path):
        played, held = tmp_path / "genau" / "video.mp4", tmp_path / "genau trash" / "video.mp4"
        batch = TrashedBatch(moves=[], subdir=None, out_of_play=[(played, held)])

        assert TrashedBatch.from_record(batch.record()).out_of_play == [(played, held)]


class TestWhereGenausVideosAre:
    def test_genaus_folder_names_its_flicks_folder(self, tmp_path):
        (tmp_path / "genau" / "flicks" / "2D").mkdir(parents=True)

        assert Genau.in_folder(tmp_path / "genau") == Genau(tmp_path / "genau" / "flicks")

    def test_a_genau_folder_that_is_not_there_gives_genau_no_place_in_the_trash(self, tmp_path):
        assert Genau.in_folder(tmp_path / "genau") is None

    def test_genaus_trash_is_the_trash_folder_beside_its_flicks(self, tmp_path):
        assert Genau(tmp_path / "genau" / "flicks").trash == tmp_path / "genau" / "trash"
