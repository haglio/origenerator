from __future__ import annotations

from pathlib import Path

import pytest

from origenerator import config, evolver_export
from origenerator.evolver_export import export_video


def test_export_copies_video_into_the_inbox(tmp_path):
    src = tmp_path / "wan22_i2v_00001_.mp4"
    src.write_bytes(b"video-bytes")
    inbox = tmp_path / "0_inbox" / "origenerator"

    dest = export_video(src, inbox)

    assert dest == inbox / "wan22_i2v_00001_.mp4"
    assert dest.read_bytes() == b"video-bytes"
    assert src.exists()


def test_export_writes_a_partial_file_before_finalizing(tmp_path, monkeypatch):
    src = tmp_path / "clip.mp4"
    src.write_bytes(b"data")
    inbox = tmp_path / "inbox"

    seen = {}
    real_copy = evolver_export.shutil.copy2

    def spy_copy(source, dest):
        dest = Path(dest)
        seen["copy_dest"] = dest
        seen["final_present_during_copy"] = (inbox / "clip.mp4").exists()
        return real_copy(source, dest)

    monkeypatch.setattr(evolver_export.shutil, "copy2", spy_copy)

    dest = export_video(src, inbox)

    assert ".partial." in seen["copy_dest"].name
    assert seen["final_present_during_copy"] is False
    assert dest.name == "clip.mp4"
    assert [p.name for p in inbox.iterdir()] == ["clip.mp4"]


def test_export_does_not_clobber_an_already_queued_video(tmp_path):
    inbox = tmp_path / "inbox"
    src = tmp_path / "clip.mp4"

    src.write_bytes(b"first")
    first = export_video(src, inbox)
    src.write_bytes(b"second")
    second = export_video(src, inbox)

    assert first != second
    assert first.read_bytes() == b"first"
    assert second.read_bytes() == b"second"


def test_a_copy_waiting_under_the_name_a_second_send_gave_it_is_still_held(tmp_path):
    inbox = evolver_export.EvolverInbox(tmp_path / "inbox")
    src = tmp_path / "clip.mp4"
    src.write_bytes(b"pixels")
    first = inbox.hand_over(src, "lane")
    inbox.hand_over(src, "lane")
    first.unlink()

    assert inbox.holds(src, "lane")
    assert not inbox.holds(tmp_path / "clip two.mp4", "lane")
    assert not inbox.holds(src, "another lane")


class TestTheFunscriptThatGoesWithIt:
    def test_lands_beside_the_copy_under_its_name(self, tmp_path):
        video, script = tmp_path / "made_00001.mp4", tmp_path / "made_00001.funscript"
        video.write_bytes(b"video")
        script.write_text("{}", encoding="utf-8")

        landed = export_video(video, tmp_path / "inbox", funscript=script)

        assert landed.with_suffix(".funscript").read_text(encoding="utf-8") == "{}"
        assert script.exists()

    def test_shows_up_only_after_its_clip_so_evolver_never_finds_it_alone(self, tmp_path,
                                                                           monkeypatch):
        video, script = tmp_path / "made_00004.mp4", tmp_path / "made_00004.funscript"
        video.write_bytes(b"video")
        script.write_text("{}", encoding="utf-8")
        shown = []
        real_replace = evolver_export.os.replace

        def replace(partial, final):
            assert evolver_export.PARTIAL_MARKER in Path(partial).name
            shown.append(Path(final).suffix)
            return real_replace(partial, final)

        monkeypatch.setattr(evolver_export.os, "replace", replace)

        export_video(video, tmp_path / "inbox", funscript=script)

        assert shown == [".mp4", ".funscript"]

    def test_a_funscript_that_will_not_copy_leaves_nothing_of_the_send_in_the_inbox(
            self, tmp_path, monkeypatch):
        video, script = tmp_path / "made_00002.mp4", tmp_path / "made_00002.funscript"
        video.write_bytes(b"video")
        script.write_text("{}", encoding="utf-8")
        inbox = tmp_path / "inbox"
        real_copy = evolver_export.shutil.copy2

        def copy_all_but_the_script(source, dest):
            if Path(source) == script:
                raise OSError("unreadable")
            return real_copy(source, dest)

        monkeypatch.setattr(evolver_export.shutil, "copy2", copy_all_but_the_script)

        with pytest.raises(OSError, match="unreadable"):
            export_video(video, inbox, funscript=script)

        assert list(inbox.iterdir()) == []

    def test_a_name_whose_funscript_is_still_waiting_moves_the_pair_along(self, tmp_path):
        video, script = tmp_path / "made_00003.mp4", tmp_path / "made_00003.funscript"
        video.write_bytes(b"video")
        script.write_text("{}", encoding="utf-8")
        inbox = tmp_path / "inbox"
        inbox.mkdir()
        (inbox / "made_00003.funscript").write_text("waiting", encoding="utf-8")

        landed = export_video(video, inbox, funscript=script)

        assert landed.name == "made_00003 (2).mp4"
        assert (inbox / "made_00003 (2).funscript").read_text(encoding="utf-8") == "{}"
        assert (inbox / "made_00003.funscript").read_text(encoding="utf-8") == "waiting"


class TestTheInbox:
    def test_a_clip_lands_in_the_folder_the_lane_is_routed_by(self, tmp_path):
        inbox = evolver_export.EvolverInbox(tmp_path / "0_inbox")
        video = tmp_path / "clip.mp4"
        video.write_bytes(b"video")

        landed = inbox.hand_over(video, "example-loop-clips")

        assert landed == tmp_path / "0_inbox" / "example-loop-clips" / "clip.mp4", (
            "the folder is the whole message: Evolver routes by it and by nothing else")
        assert landed.read_bytes() == b"video"

    def test_a_clip_handed_over_with_its_funscript_brings_it(self, tmp_path):
        inbox = evolver_export.EvolverInbox(tmp_path / "0_inbox")
        video, script = tmp_path / "clip.mp4", tmp_path / "clip.funscript"
        video.write_bytes(b"video")
        script.write_text("{}", encoding="utf-8")

        landed = inbox.hand_over(video, "example-library-lane", funscript=script)

        assert landed.with_suffix(".funscript").read_text(encoding="utf-8") == "{}"

    def test_a_lane_with_no_folder_is_refused_rather_than_dropped_in_the_root(
            self, tmp_path):
        inbox = evolver_export.EvolverInbox(tmp_path / "0_inbox")
        video = tmp_path / "clip.mp4"
        video.write_bytes(b"video")
        refusal = ""

        try:
            inbox.hand_over(video, "")
        except ValueError as refused:
            refusal = str(refused)

        assert list(tmp_path.glob("0_inbox/*")) == [], (
            "Evolver sorts only the folders inside its inbox, one per lane, so a video "
            "dropped in the inbox's own folder belongs to no lane it knows")
        assert "no folder" in refusal

    def test_the_app_s_own_inbox_is_the_one_config_names(self):
        assert evolver_export.default_inbox().inbox_dir == config.EVOLVER_INBOX_DIR
