from __future__ import annotations

from app_support import haglio_settings

from origenerator import config


def test_the_suites_settings_name_no_folder_outside_the_suites_own_scratch():
    assert haglio_settings.reaching_outside(haglio_settings.load(), config.STATE_DIR) == []
    assert config.LIBRARY_ROOT.is_relative_to(config.STATE_DIR)
