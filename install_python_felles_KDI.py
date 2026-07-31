"""Installer IGH-appens pakker lokalt fra den åpne Python Felles-prosessen."""

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
            f"IGH-appen krever Python 3.11 eller nyere. Du har {sys.version.split()[0]}."
        )
    requirements = PROJECT_DIR / "requirements.txt"
    package_dir = PROJECT_DIR / PACKAGE_DIR_NAME
    wheelhouse = PROJECT_DIR / "wheelhouse"
    if not requirements.is_file():
        raise FileNotFoundError(f"Finner ikke {requirements}")
    package_dir.mkdir(exist_ok=True)

    try:
        from pip._internal.cli.main import main as pip_main
    except ImportError as exc:
        raise RuntimeError(
            "Python Felles mangler pip. IT må aktivere pip i den publiserte "
            "Python-installasjonen."
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

    print(f"Installerer IGH-avhengigheter for Python {sys.version.split()[0]} ...")
    result = pip_main(arguments)
    if result:
        raise RuntimeError(f"Pakkeinstallasjonen feilet med kode {result}.")

    state = {
        "installed_at": datetime.now(timezone.utc).isoformat(),
        "python": sys.version,
        "requirements_sha256": hashlib.sha256(requirements.read_bytes()).hexdigest(),
    }
    (PROJECT_DIR / ".python_felles_state.json").write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("Ferdig. Du kan nå kjøre startkommandoen for IGH-appen.")


if __name__ == "__main__":
    install()
