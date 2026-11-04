from __future__ import annotations

import pytest

from origenerator.recycle_bin import ALLOW_UNDO, _windows_shell, send_to_recycle_bin


def test_a_file_is_handed_to_windows_so_that_it_can_be_put_back(tmp_path):
    asked = []
    path = tmp_path / "example.safetensors"

    send_to_recycle_bin(path, shell=lambda to_delete, flags: asked.append((to_delete, flags)) or 0)

    assert asked[0][0] == f"{path}\0\0"
    assert asked[0][1] & ALLOW_UNDO


def test_a_move_windows_refuses_is_an_error_naming_the_file(tmp_path):
    path = tmp_path / "example.safetensors"

    with pytest.raises(OSError, match=r"example\.safetensors"):
        send_to_recycle_bin(path, shell=lambda _to_delete, _flags: 32)


def test_windows_is_asked_to_delete_with_undo_and_an_answer_of_no_is_passed_on():
    asked = []

    def windows(operation):
        asked.append((operation._obj.wFunc, operation._obj.pFrom, operation._obj.fFlags))
        return 0

    assert _windows_shell("example.safetensors", ALLOW_UNDO, shell_call=windows) == 0
    assert asked == [(3, "example.safetensors", ALLOW_UNDO)]
    assert _windows_shell("example.safetensors", ALLOW_UNDO, shell_call=lambda _op: 32) == 32


def test_a_move_someone_stopped_counts_as_refused():
    def stopped(operation):
        operation._obj.fAnyOperationsAborted = True
        return 0

    assert _windows_shell("example.safetensors", ALLOW_UNDO, shell_call=stopped) == 1
