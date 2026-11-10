from __future__ import annotations

from origenerator.precision import file_size_sentence


def test_a_files_size_is_said_in_gigabytes_to_a_tenth():
    assert file_size_sentence(int(24.5 * 2**30)) == "This file is 24.5 GB."
