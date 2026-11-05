from __future__ import annotations

import subprocess
import sys

from tests.children import REPO_ROOT

_A_WORKER_THAT_SAYS_ITS_PRIORITY = """
import ctypes, sys
sys.path.insert(0, "tests")
from side_by_side import run_behind_what_he_is_using
run_behind_what_he_is_using()
print(ctypes.WinDLL("kernel32").GetPriorityClass(ctypes.c_void_p(-1)))
"""


def test_a_worker_of_a_run_side_by_side_runs_behind_what_he_is_using():
    started_at_normal_priority = subprocess.CREATE_NO_WINDOW | subprocess.NORMAL_PRIORITY_CLASS

    worker = subprocess.run([sys.executable, "-c", _A_WORKER_THAT_SAYS_ITS_PRIORITY], cwd=REPO_ROOT,
                            creationflags=started_at_normal_priority, capture_output=True, text=True, check=True)

    assert int(worker.stdout) == subprocess.BELOW_NORMAL_PRIORITY_CLASS
