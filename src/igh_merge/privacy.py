from __future__ import annotations

from pathlib import Path


class PrivacyError(ValueError):
    """Operasjonen ville plassere kliniske data i et Git-arbeidstre."""


def ensure_outside_git(output: Path) -> None:
    resolved = output.expanduser().resolve()
    start = resolved if resolved.is_dir() else resolved.parent
    for parent in (start, *start.parents):
        if (parent / ".git").exists():
            raise PrivacyError(
                f"Klinisk output kan ikke lagres i Git-arbeidstreet: {parent}"
            )
