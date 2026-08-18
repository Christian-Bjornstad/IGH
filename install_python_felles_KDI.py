"""Install IGH app packages locally from the open Python Common process."""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_DIR = Path(
    r"K:\Felles\KDI\Delte\PAT\Molekylaerpatologi\Molpat OCCI\Diagnostikk"
    r"\Analyser,oppsett,kontroller\Hemapatologi\IGHV\CFB\IGH_app"
)
PACKAGE_DIR_NAME = ".python_felles_packages"


def install() -> None:
    if sys.version_info < (3, 11):
        raise RuntimeError(
            f"IGH app requires Python 3.11 or newer. You have {sys.version.split()[0]}."
        )
    requirements = PROJECT_DIR / "requirements.txt"
    package_dir = PROJECT_DIR / PACKAGE_DIR_NAME
    wheelhouse = PROJECT_DIR / "wheelhouse"
    if not requirements.is_file():
        raise FileNotFoundError(f"Cannot find {requirements}")
    package_dir.mkdir(exist_ok=True)

    try:
        from pip._internal.cli.main import main as pip_main
    except ImportError as exc:
        raise RuntimeError(
            "Python Common lacks pip. IT must enable pip in the published "
            "Python installation."
        ) from exc

    arguments = [
        "install",
        "--upgrade",
        "--target",
        str(package_dir),
        "--requirement",
        str(requirements),
    ]
    if wheelhouse.is_dir():
        arguments.extend(["--no-index", "--find-links", str(wheelhouse)])

    print(f"Installing IGH dependencies for Python {sys.version.split()[0]} ...")
    result = pip_main(arguments)
    if result:
        raise RuntimeError(f"Package installation failed with code {result}.")

    state = {
        "installed_at": datetime.now(timezone.utc).isoformat(),
        "python": sys.version,
        "requirements_sha256": hashlib.sha256(requirements.read_bytes()).hexdigest(),
    }
    (PROJECT_DIR / ".python_felles_state.json").write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("Done. You can now run the start command for the IGH app.")


if __name__ == "__main__":
    install()
