from __future__ import annotations

from app_support import haglio_settings

from origenerator import config, osr2


class TestProjectRoots:
    def test_are_the_ones_all_of_haglio_shares(self):
        assert haglio_settings.project_roots() == config.PROJECT_ROOTS


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

    def test_a_sibling_that_is_not_installed_still_resolves_to_a_path(self, tmp_path):
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
    def test_comfyui_stays_on_the_library_root_because_it_is_not_one_of_our_repos(self):
        assert config.COMFYUI_DIR == config.LIBRARY_ROOT / "projects" / "ComfyUIApp" / "ComfyUI"


class TestTheValuesAnotherAppHoldsToo:
    # Spelled out, not derived: a derived value reads the same before and after it moves.

    def test_the_shared_osr2_state_lives_in_fun_times_checkout(self):
        assert config.project_dir("fun_time") / "state" == osr2.SHARED_STATE_DIR

    def test_evolver_watches_this_exact_inbox(self):
        assert config.EVOLVER_INBOX_DIR == (
            config.LIBRARY_ROOT / "videos" / "videos" / "2D" / "AI" / "0_inbox")
        assert config.EVOLVER_SOURCE == "origenerator"

    def test_evolver_files_its_upscales_under_this_exact_tree(self):
        assert config.EVOLVER_UPSCALED_DIR == (
            config.LIBRARY_ROOT / "videos" / "videos" / "2D" / "AI" / "2_outbox"
            / "upscaled_by_orientation")
