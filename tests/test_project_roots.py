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
    def test_the_osr2_state_dir_comes_from_a_project_root(self):
        assert any(
            config.OSR2_STATE_DIR.is_relative_to(root) for root in config.PROJECT_ROOTS
        ), f"{config.OSR2_STATE_DIR} is under none of {config.PROJECT_ROOTS}"

    def test_the_genau_flag_file_stays_inside_the_osr2_state_dir(self):
        assert config.OSR2_GENAU_ENABLED_FILE.parent == config.OSR2_STATE_DIR

    def test_comfyui_stays_on_the_suite_root_because_it_is_not_one_of_our_repos(self):
        """ComfyUI is a third-party app that did not move with the suite."""
        assert config.COMFYUI_DIR == config.SUITE_ROOT / "projects" / "ComfyUIApp" / "ComfyUI"

    def test_the_evolver_inbox_stays_on_the_suite_root_because_the_library_did_not_move(self):
        assert config.EVOLVER_INBOX_DIR.is_relative_to(config.SUITE_ROOT / "videos")
