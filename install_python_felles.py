"""Install IGH Merge for the current Python FELLES user.

Runs via ``INSTALL_IGH_MERGE.cmd`` (Ivanti PowerGate) or directly:

    python install_python_felles.py

The script installs the project from this folder into the user's own
site-packages, so no administrator rights are required. All runtime
dependencies come from ``pyproject.toml`` (including python-docx and
websocket-client, which are deliberately not part of the five pinned
``requirements.txt`` lines guarded by the test suite).
"""
from __future__ import annotations

import ensurepip
import importlib
import os
import site
import sys
import traceback
from collections.abc import Callable
from pathlib import Path
from typing import Any


PROJECT_DIR = Path(__file__).resolve().parent
REQUIRED_IMPORTS = (
    "openpyxl",
    "PyQt6",
    "reportlab",
    "requests",
    "truststore",
    "docx",
    "websocket",
    "igh_merge",
)


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
    return logs / "install.log"


def _record_failure(stage: str, error: BaseException) -> None:
    with _log_file().open("a", encoding="utf-8") as stream:
        stream.write(f"\n[{stage}] {type(error).__name__}: {error}\n")
        traceback.print_exception(
            type(error), error, error.__traceback__, file=stream
        )


def install(
    *,
    project_dir: Path = PROJECT_DIR,
    user_site: Path | None = None,
    pip_main: Callable[[list[str]], int | None] | None = None,
    importer: Callable[[str], Any] = importlib.import_module,
) -> int:
    project = project_dir.resolve()
    if not (project / "pyproject.toml").is_file():
        raise RuntimeError(f"Cannot find pyproject.toml in {project}.")
    if not (project / "src" / "igh_merge").is_dir():
        raise RuntimeError("Cannot find the IGH Merge code in src\\igh_merge.")

    package_site = (user_site or Path(site.getusersitepackages())).resolve()
    package_site.mkdir(parents=True, exist_ok=True)
    _add_path_first(package_site)

    if pip_main is None:
        try:
            import pip  # noqa: F401
        except ImportError:
            ensurepip.bootstrap(user=True, upgrade=True)
        from pip._internal.cli.main import main as pip_main

    result = int(
        pip_main(
            [
                "install",
                "--user",
                "--disable-pip-version-check",
                "-e",
                f"{project}[dev]",
            ]
        )
        or 0
    )
    if result != 0:
        raise RuntimeError(f"Installation stopped with exit code {result}.")

    _add_path_first(project / "src")
    importlib.invalidate_caches()
    for module_name in REQUIRED_IMPORTS:
        importer(module_name)

    print()
    print("IGH Merge is installed with Python FELLES.")
    print("Close Python FELLES and start IGH Merge with START_IGH_MERGE.cmd.")
    return 0


def main(*, project_dir: Path = PROJECT_DIR) -> int:
    """Safety net for Python FELLES: catch and log every failure."""
    try:
        activate_user_site()
        return install(project_dir=project_dir)
    except Exception as error:  # noqa: BLE001
        _record_failure("installer_start_failed", error)
        print()
        print("The IGH Merge installation could not be completed.")
        print(f"Error: {error}")
        print(f"Details were written to: {_log_file()}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
