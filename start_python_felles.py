"""Start IGH Merge inside the already open Python FELLES process.

Runs via ``START_IGH_MERGE.cmd`` (Ivanti PowerGate) or directly:

    python start_python_felles.py

The script prepends the user's site-packages and the project's ``src``
folder to ``sys.path`` and then launches the IGH Merge GUI.
"""
from __future__ import annotations

import importlib
import os
import site
import sys
import traceback
from collections.abc import Callable
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent


def _add_path_first(path: Path) -> None:
    text = str(path)
    while text in sys.path:
        sys.path.remove(text)
    sys.path.insert(0, text)


def activate_user_site() -> Path:
    """Prepend the user site-packages directory to ``sys.path``."""
    if sys.version_info < (3, 11):
        raise RuntimeError(
            "IGH Merge requires Python 3.11 or newer, but the active "
            f"version is {sys.version.split()[0]}."
        )
    user_site = Path(site.getusersitepackages())
    user_site.mkdir(parents=True, exist_ok=True)
    _add_path_first(user_site)
    return user_site


def _log_file() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    logs = base / "IGH" / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    return logs / "start.log"


def _record_failure(stage: str, error: BaseException) -> None:
    with _log_file().open("a", encoding="utf-8") as stream:
        stream.write(f"\n[{stage}] {type(error).__name__}: {error}\n")
        traceback.print_exception(
            type(error), error, error.__traceback__, file=stream
        )


def start(
    *,
    project_dir: Path = PROJECT_DIR,
    user_site: Path | None = None,
    app_main: Callable[[], int | None] | None = None,
) -> int:
    project = project_dir.resolve()
    if not (project / "src" / "igh_merge").is_dir():
        raise RuntimeError("Cannot find the IGH Merge code in src\\igh_merge.")

    package_site = (user_site or Path(site.getusersitepackages())).resolve()
    _add_path_first(package_site)
    _add_path_first(project / "src")
    _add_path_first(project)
    importlib.invalidate_caches()

    if app_main is None:
        from igh_merge.__main__ import main as app_main

    result = int(app_main() or 0)
    if result != 0:
        raise RuntimeError(f"IGH Merge exited with code {result}.")
    return 0


def main(*, project_dir: Path = PROJECT_DIR) -> int:
    """Safety net for Python FELLES: catch and log every failure."""
    try:
        activate_user_site()
        return start(project_dir=project_dir)
    except Exception as error:  # noqa: BLE001
        _record_failure("igh_merge_start_failed", error)
        print()
        print("IGH Merge could not be started.")
        print(f"Error: {error}")
        print(f"Details were written to: {_log_file()}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
