"""Start IGH-appen inne i den allerede åpne Python Felles-prosessen."""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

PROJECT_DIR = Path(
    r"K:\Felles\KDI\Delte\PAT\Molekylaerpatologi\Molpat OCCI\Diagnostikk"
    r"\Analyser,oppsett,kontroller\Hemapatologi\IGHV\CFB\IGH_app"
)


def start() -> None:
    package_dir = PROJECT_DIR / ".python_felles_packages"
    source_dir = PROJECT_DIR / "src"
    requirements = PROJECT_DIR / "requirements.txt"
    state_file = PROJECT_DIR / ".python_felles_state.json"
    if not source_dir.is_dir():
        raise FileNotFoundError(f"Finner ikke programkoden i {source_dir}")
    if not package_dir.is_dir():
        raise RuntimeError(
            "Pakkene er ikke installert. Kjør INSTALLER PAKKER-kommandoen først."
        )
    try:
        state = json.loads(state_file.read_text(encoding="utf-8"))
        installed_hash = state["requirements_sha256"]
    except (FileNotFoundError, KeyError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            "Installasjonsstatus mangler eller er ugyldig. Kjør INSTALLER PAKKER-"
            "kommandoen på nytt."
        ) from exc
    current_hash = hashlib.sha256(requirements.read_bytes()).hexdigest()
    if installed_hash != current_hash:
        raise RuntimeError(
            "requirements.txt er endret siden pakkene ble installert. Kjør "
            "INSTALLER PAKKER-kommandoen på nytt før appen startes."
        )
    for path in (source_dir, package_dir):
        value = str(path)
        if value not in sys.path:
            sys.path.insert(0, value)
    os.chdir(PROJECT_DIR)

    try:
        from igh_merge.__main__ import main
    except ImportError as exc:
        raise RuntimeError(
            "IGH-appen kunne ikke lastes. Kjør installasjonsskriptet på nytt."
        ) from exc
    main()


if __name__ == "__main__":
    start()
