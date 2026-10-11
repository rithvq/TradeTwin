"""Compatibility entry point for an isolated audit UI already running on port 3100."""

import importlib.util
from pathlib import Path

if __name__ == "__main__":
    path = Path(__file__).with_name("domestic-browser-check.py")
    spec = importlib.util.spec_from_file_location("domestic_browser_checks", path)
    checks = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checks)
    checks.ORIGIN = "http://127.0.0.1:3100"
    checks.browser_check()
