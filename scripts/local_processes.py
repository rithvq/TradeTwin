"""Lifecycle helpers for isolated integration-test servers."""

import os
import subprocess
from pathlib import Path


def stop_process(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        # The Windows venv launcher owns a second interpreter holding SQLite files.
        subprocess.run(
            [
                str(Path(os.environ["SystemRoot"]) / "System32/taskkill.exe"),
                "/PID",
                str(process.pid),
                "/T",
                "/F",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=15,
        )
    else:
        process.terminate()
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)
