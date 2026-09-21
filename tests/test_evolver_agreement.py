"""What this app and Evolver must agree about, checked while the app runs.

``test_evolver_pipeline_contract.py`` holds this repo's values against Evolver's
published document, and skips where there is no Evolver beside the checkout --
which is every run of this repo's gate.  So on the one machine where both apps
are installed, nothing checked anything: a folder renamed on either side left
clips arriving nowhere, both apps silent.

These are that check's runtime twin, driven against written-out checkouts so
each disagreement can be produced rather than waited for.
"""
from __future__ import annotations

import json
from pathlib import Path

from origenerator import config, evolver_agreement, evolver_export

AGREED_INBOX = "videos/videos/2D/AI/0_inbox"
AGREED_UPSCALED = "videos/videos/2D/AI/2_outbox/upscaled_by_orientation"
AGREED_MARKER = ".partial."
AGREED_GENAU = "example-loop-clips"


def _evolver(root: Path, *, inbox=AGREED_INBOX, upscaled=AGREED_UPSCALED,
             marker=AGREED_MARKER, genau_source=AGREED_GENAU) -> Path:
    """A checkout of Evolver, with the document it publishes and the overlay it
    keeps the library's own words in."""
    checkout = root / "evolver"
    checkout.mkdir(parents=True, exist_ok=True)
    (checkout / "evolver_contract.json").write_text(json.dumps({
        "library_relative": {"inbox_dir": inbox, "upscaled_dir": upscaled},
        "partial_marker": marker,
    }), encoding="utf-8")
    (checkout / "content.local.json").write_text(
        json.dumps({"genau_source": genau_source}), encoding="utf-8")
    return checkout


def _ours(*, library=Path("L:/library"), inbox_dir=None, upscaled_dir=None,
          marker=AGREED_MARKER, genau_source=AGREED_GENAU):
    return evolver_agreement.OurSide(
        library_root=library,
        inbox_dir=inbox_dir if inbox_dir is not None else library / Path(AGREED_INBOX),
        upscaled_dir=upscaled_dir if upscaled_dir is not None else library / Path(AGREED_UPSCALED),
        partial_marker=marker,
        genau_source=genau_source,
    )


class TestWhenEvolverIsBeside:
    def test_four_values_agreeing_is_nothing_to_say(self, tmp_path: Path):
        checkout = _evolver(tmp_path)

        assert evolver_agreement.disagreements(_ours(), checkout) == ()

    def test_a_renamed_inbox_is_named_with_both_spellings(self, tmp_path: Path):
        checkout = _evolver(tmp_path, inbox="videos/videos/2D/AI/0_intake")

        said = evolver_agreement.disagreements(_ours(), checkout)

        assert len(said) == 1
        assert "0_intake" in said[0] and "0_inbox" in said[0]

    def test_a_renamed_upscale_folder_is_named_too(self, tmp_path: Path):
        checkout = _evolver(tmp_path, upscaled="videos/videos/2D/AI/2_outbox/by_shape")

        said = evolver_agreement.disagreements(_ours(), checkout)

        assert len(said) == 1
        assert "by_shape" in said[0]

    def test_a_marker_that_moved_is_a_half_written_clip_ingested(self, tmp_path: Path):
        checkout = _evolver(tmp_path, marker=".writing.")

        said = evolver_agreement.disagreements(_ours(), checkout)

        assert len(said) == 1
        assert ".writing." in said[0] and ".partial." in said[0]

    def test_the_lane_folder_is_compared_against_evolvers_own_overlay(self, tmp_path: Path):
        """The one value neither app may publish: a folder inside the library is
        library vocabulary, so it lives in two git-ignored overlays and nothing
        but this can hold them together."""
        checkout = _evolver(tmp_path, genau_source="example-other-clips")

        said = evolver_agreement.disagreements(_ours(), checkout)

        assert len(said) == 1
        assert "example-other-clips" in said[0] and "example-loop-clips" in said[0]

    def test_every_disagreement_is_reported_at_once(self, tmp_path: Path):
        """Told one at a time, four renames are four launches."""
        checkout = _evolver(tmp_path, inbox="a", upscaled="b", marker="c",
                            genau_source="d")

        assert len(evolver_agreement.disagreements(_ours(), checkout)) == 4


class TestWhenThereIsNoEvolver:
    def test_no_checkout_beside_this_one_is_not_a_disagreement(self, tmp_path: Path):
        """A fresh clone, and every run of this repo's gate."""
        assert evolver_agreement.disagreements(_ours(), tmp_path / "evolver") == ()

    def test_a_checkout_with_no_published_document_says_nothing(self, tmp_path: Path):
        bare = tmp_path / "evolver"
        bare.mkdir()

        assert evolver_agreement.disagreements(_ours(), bare) == ()

    def test_an_unreadable_document_is_reported_rather_than_raised(self, tmp_path: Path):
        """At startup, before a window: a broken file over there must not be how
        this app fails to open."""
        checkout = _evolver(tmp_path)
        (checkout / "evolver_contract.json").write_text("{not json", encoding="utf-8")

        said = evolver_agreement.disagreements(_ours(), checkout)

        assert len(said) == 1
        assert "evolver_contract.json" in said[0]


class TestWhatTheAppCompares:
    def test_our_side_is_read_off_this_app_s_own_config(self):
        """The record the check is given is built from config, so a value renamed
        there is compared, rather than a second copy of it written here."""
        ours = evolver_agreement.our_side()

        assert ours.inbox_dir == config.EVOLVER_INBOX_DIR
        assert ours.upscaled_dir == config.EVOLVER_UPSCALED_DIR
        assert ours.genau_source == config.GENAU_SOURCE
        assert ours.library_root == config.LIBRARY_ROOT

    def test_the_marker_is_the_one_a_copy_actually_wears(self):
        assert evolver_agreement.our_side().partial_marker == evolver_export.PARTIAL_MARKER
