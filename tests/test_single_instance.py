from __future__ import annotations

import ctypes
from pathlib import Path

import pytest

from origenerator.single_instance import claim_the_library


@pytest.fixture
def claims():
    held = []
    yield held
    for handle in filter(None, held):
        ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(handle))


def test_a_second_claim_on_one_library_is_refused(tmp_path, claims):
    claims.append(claim_the_library(tmp_path / "state"))

    assert claims[0]
    assert claim_the_library(tmp_path / "state") is None


def test_one_library_is_one_however_its_folder_is_spelled(tmp_path, claims):
    folder = tmp_path / "state"
    claims.append(claim_the_library(folder))

    assert claim_the_library(Path(str(folder).upper().replace("\\", "/"))) is None


def test_another_library_is_claimed_beside_it(tmp_path, claims):
    claims.append(claim_the_library(tmp_path / "one" / "state"))
    claims.append(claim_the_library(tmp_path / "two" / "state"))

    assert all(claims)
