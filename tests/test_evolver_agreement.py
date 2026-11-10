from __future__ import annotations

import json
from pathlib import Path

from app_support import haglio_settings

from origenerator import config, evolver_agreement, evolver_export

AGREED_INBOX = "videos/videos/2D/AI/0_inbox"
AGREED_MARKER = ".partial."


def _evolver(root: Path, *, inbox=AGREED_INBOX, marker=AGREED_MARKER) -> Path:
    checkout = root / "evolver"
    checkout.mkdir(parents=True, exist_ok=True)
    (checkout / "evolver_contract.json").write_text(json.dumps({
        "library_relative": {"inbox_dir": inbox},
        "partial_marker": marker,
    }), encoding="utf-8")
    return checkout


def _ours(*, library=Path("L:/library"), inbox_dir=None, marker=AGREED_MARKER):
    return evolver_agreement.OurSide(
        library_root=library,
        inbox_dir=inbox_dir if inbox_dir is not None else library / Path(AGREED_INBOX),
        partial_marker=marker,
    )


class TestWhenEvolverIsBeside:
    def test_both_values_agreeing_is_nothing_to_say(self, tmp_path: Path):
        checkout = _evolver(tmp_path)

        assert evolver_agreement.disagreements(_ours(), checkout) == ()

    def test_a_renamed_inbox_is_named_with_both_spellings(self, tmp_path: Path):
        checkout = _evolver(tmp_path, inbox="videos/videos/2D/AI/0_intake")

        said = evolver_agreement.disagreements(_ours(), checkout)

        assert len(said) == 1
        assert "0_intake" in said[0]
        assert "0_inbox" in said[0]

    def test_a_marker_that_moved_is_a_half_written_clip_ingested(self, tmp_path: Path):
        checkout = _evolver(tmp_path, marker=".writing.")

        said = evolver_agreement.disagreements(_ours(), checkout)

        assert len(said) == 1
        assert ".writing." in said[0]
        assert ".partial." in said[0]

    def test_every_disagreement_is_reported_at_once(self, tmp_path: Path):
        checkout = _evolver(tmp_path, inbox="a", marker="c")

        assert len(evolver_agreement.disagreements(_ours(), checkout)) == 2


class TestWhenThereIsNoEvolver:
    def test_no_checkout_beside_this_one_is_not_a_disagreement(self, tmp_path: Path):
        assert evolver_agreement.disagreements(_ours(), tmp_path / "evolver") == ()

    def test_a_checkout_with_no_published_document_says_nothing(self, tmp_path: Path):
        bare = tmp_path / "evolver"
        bare.mkdir()

        assert evolver_agreement.disagreements(_ours(), bare) == ()

    def test_an_unreadable_document_is_reported_rather_than_raised(self, tmp_path: Path):
        checkout = _evolver(tmp_path)
        (checkout / "evolver_contract.json").write_text("{not json", encoding="utf-8")

        said = evolver_agreement.disagreements(_ours(), checkout)

        assert len(said) == 1
        assert "evolver_contract.json" in said[0]


def _publishing(tmp_path: Path, **sections) -> Path:
    checkout = _evolver(tmp_path)
    document = json.loads((checkout / "evolver_contract.json").read_text(encoding="utf-8"))
    (checkout / "evolver_contract.json").write_text(json.dumps({**document, **sections}),
                                                    encoding="utf-8")
    return checkout


class TestTheFoldersEvolverPublishesForTheOtherApps:
    def test_every_videos_record_is_under_the_folder_it_names(self, tmp_path: Path):
        checkout = _publishing(tmp_path, library_record={"folder": "videos/records"})

        assert evolver_agreement.records_folder(checkout, Path("L:/library")) == Path(
            "L:/library/videos/records")


class TestWhatTheAppCompares:
    def test_our_side_is_read_off_this_app_s_own_config(self):
        ours = evolver_agreement.our_side()

        assert ours.inbox_dir == config.EVOLVER_INBOX_DIR
        assert ours.library_root == config.LIBRARY_ROOT

    def test_the_lane_folder_is_the_one_all_of_haglio_shares(self):
        assert haglio_settings.value("genau_source") == config.GENAU_SOURCE, (
            "Evolver upscales what arrives under this folder's name before delivering it; "
            "sent straight on, a loop out of the graph is visibly softer than the videos there")

    def test_the_marker_is_the_one_a_copy_actually_wears(self):
        assert evolver_agreement.our_side().partial_marker == evolver_export.PARTIAL_MARKER
