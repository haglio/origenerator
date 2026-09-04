"""Where the sibling app checkouts are, and how config finds them.

``suite_root`` named two things at once -- the folder holding the media library
and the folder holding the sibling apps -- and those came apart when the suite's
own repos were moved out of the file-synced tree the library stays in. ComfyUI
is not one of those repos: it did not move, so it stays on ``suite_root`` while
``fun_time`` comes from the new setting. That split is the point of these tests.
"""

from pathlib import Path

from origenerator import config


class TestProjectRoots:
    def test_defaults_to_the_projects_folder_under_the_suite_root(self):
        """An overlay with no project_roots behaves exactly as it always did."""
        assert config.project_roots({"suite_root": "S:/suite"}) == (Path("S:/suite/projects"),)

    def test_an_empty_list_falls_back_to_the_default_too(self):
        content = {"suite_root": "S:/suite", "project_roots": []}

        assert config.project_roots(content) == (Path("S:/suite/projects"),)

    def test_reads_the_roots_from_the_overlay_in_the_order_given(self):
        content = {"suite_root": "S:/suite", "project_roots": ["W:/work", "S:/suite/projects"]}

        assert config.project_roots(content) == (Path("W:/work"), Path("S:/suite/projects"))


class TestProjectDir:
    def test_finds_a_checkout_in_the_only_root(self, tmp_path):
        checkout = tmp_path / "suite" / "alpha_app"
        checkout.mkdir(parents=True)

        assert config.project_dir("alpha_app", (tmp_path / "suite",)) == checkout

    def test_prefers_the_earlier_root_when_both_hold_the_checkout(self, tmp_path):
        moved = tmp_path / "work" / "alpha_app"
        moved.mkdir(parents=True)
        (tmp_path / "old" / "alpha_app").mkdir(parents=True)

        found = config.project_dir("alpha_app", (tmp_path / "work", tmp_path / "old"))

        assert found == moved

    def test_falls_through_to_a_later_root_for_a_checkout_that_has_not_moved(self, tmp_path):
        (tmp_path / "work" / "alpha_app").mkdir(parents=True)
        stayed = tmp_path / "old" / "beta_app"
        stayed.mkdir(parents=True)

        found = config.project_dir("beta_app", (tmp_path / "work", tmp_path / "old"))

        assert found == stayed

    def test_returns_a_path_under_the_first_root_when_no_root_holds_it(self, tmp_path):
        """Every consumer guards on existence; resolving must not raise."""
        found = config.project_dir("gamma_app", (tmp_path / "work", tmp_path / "old"))

        assert found == tmp_path / "work" / "gamma_app"

    def test_a_file_of_that_name_does_not_count_as_the_checkout(self, tmp_path):
        (tmp_path / "work").mkdir()
        (tmp_path / "work" / "alpha_app").write_text("not a checkout", encoding="utf-8")
        checkout = tmp_path / "old" / "alpha_app"
        checkout.mkdir(parents=True)

        found = config.project_dir("alpha_app", (tmp_path / "work", tmp_path / "old"))

        assert found == checkout


class TestWhichPathsMovedAndWhichDidNot:
    def test_comfyui_stays_on_the_suite_root_because_it_is_not_one_of_our_repos(self):
        """ComfyUI is a third-party app that did not move with the suite."""
        assert config.COMFYUI_DIR == config.SUITE_ROOT / "projects" / "ComfyUIApp" / "ComfyUI"


class TestTheValuesAnotherAppHoldsToo:
    """Each of these is only correct because a sibling app holds the same one.

    Spelled out rather than derived: a derivation ("the flag is inside the state
    dir", "the inbox is somewhere under videos") reads exactly the same before and
    after the value moves, and noticing that it moved is the whole job. Change one
    of these without changing the counterpart named beside it and a channel
    between two running apps goes quiet — the writer keeps writing and the reader
    hears nothing, with no error anywhere.
    """

    def test_the_broker_takes_t_code_on_this_udp_port(self):
        # osr2_broker/session.py binds the same number. A different one here is an
        # OSR2 that never moves, with nothing on screen saying why.
        assert config.OSR2_TCODE_UDP_PORT == 50557

    def test_the_shared_osr2_state_lives_in_fun_times_checkout(self):
        # Not this app's state dir and not the broker's: fun_time's, which is
        # where all three look for these files.
        assert config.project_dir("fun_time") / "state" == config.OSR2_STATE_DIR

    def test_the_genau_flag_is_the_file_the_broker_reads(self):
        # This app writes "0" here while it drives, and restores the prior value
        # after; the broker reads it to know whether genau's auto-mode may run.
        assert config.OSR2_GENAU_ENABLED_FILE.name == "genau_enabled.txt"

    def test_the_devices_own_stamp_is_the_file_the_broker_writes(self):
        # The only evidence the OSR2 is there at all (see origenerator.osr2).
        assert config.OSR2_SERIAL_RX_FILE.name == "osr2_serial_rx.txt"

    def test_the_device_may_stay_quiet_for_the_brokers_own_window(self):
        # osr2_broker.monitor.MonitorState answers the same question with the same
        # window, so the app and the broker never disagree about whether it is on.
        assert config.OSR2_RX_STALE_S == 30.0

    def test_evolver_watches_this_exact_inbox(self):
        # Mirrors evolver's own INBOX_DIR. A folder evolver is not watching is a
        # finished video that is simply never ingested.
        assert config.EVOLVER_INBOX_DIR == (
            config.SUITE_ROOT / "videos" / "videos" / "2D" / "AI" / "0_inbox")
        assert config.EVOLVER_SOURCE == "origenerator"  # how evolver routes ours
