import subprocess
import sys
from unittest.mock import patch

from origenerator.experiments.gpu import gpu_busy


def _completed(stdout: str, returncode: int = 0):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout)


def test_reports_busy_when_utilization_reaches_the_threshold():
    with patch("origenerator.experiments.gpu.subprocess.run",
               return_value=_completed("37\n")):
        assert gpu_busy(threshold_percent=25) is True
        assert gpu_busy(threshold_percent=50) is False


def test_an_unprobeable_gpu_reads_as_idle():
    # No nvidia-smi, a failing one, or garbled output must not stall experiments
    # forever — the probe only ever *defers* work, never disables the feature.
    with patch("origenerator.experiments.gpu.subprocess.run",
               side_effect=FileNotFoundError("nvidia-smi")):
        assert gpu_busy() is False
    with patch("origenerator.experiments.gpu.subprocess.run",
               return_value=_completed("", returncode=1)):
        assert gpu_busy() is False
    with patch("origenerator.experiments.gpu.subprocess.run",
               return_value=_completed("N/A\n")):
        assert gpu_busy() is False


def test_probe_never_flashes_a_console_window():
    # Windows opens a console per console-tool subprocess unless CREATE_NO_WINDOW
    # is passed — the cause of the app's historical startup window storm.
    with patch("origenerator.experiments.gpu.subprocess.run",
               return_value=_completed("0\n")) as run:
        gpu_busy()
    assert run.call_args.kwargs["creationflags"] == (
        subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    )
