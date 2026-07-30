#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

FORBIDDEN_SUFFIXES = {
    ".xlsx", ".xls", ".xlsm", ".xlsb", ".fastq", ".fq", ".fasta", ".fa",
    ".fna", ".pdf", ".tsv", ".csv", ".rdata",
}
FORBIDDEN_NAME_PARTS = {
    "ighv-shm_output", "leader_output", "igh_fr1_output", "merged_updated",
    "resultater ighv-shm",
}
CLINICAL_ID = re.compile(r"\b\d{2}OUM\d{4,}\b", re.IGNORECASE)
SEQUENCE_LINE = re.compile(r"^[ACGTN]{80,}$", re.IGNORECASE)


def staged_paths() -> list[Path]:
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
        check=True,
        capture_output=True,
        text=True,
    )
    return [Path(line) for line in result.stdout.splitlines() if line.strip()]


def tracked_paths() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files"], check=True, capture_output=True, text=True
    )
    return [Path(line) for line in result.stdout.splitlines() if line.strip()]


def scan_paths(paths: list[Path]) -> list[str]:
    errors: list[str] = []
    for path in paths:
        lower = path.name.lower()
        if path.suffix.lower() in FORBIDDEN_SUFFIXES or any(part in lower for part in FORBIDDEN_NAME_PARTS):
            errors.append(f"Forbudt klinisk filtype/navn: {path}")
            continue
        if not path.is_file() or path.stat().st_size > 2_000_000:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if CLINICAL_ID.search(text):
            errors.append(f"Mulig klinisk prøve-ID i {path}")
        if any(SEQUENCE_LINE.fullmatch(line.strip()) for line in text.splitlines()):
            errors.append(f"Mulig lang DNA-sekvens i {path}")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--staged", action="store_true")
    mode.add_argument("--all", action="store_true")
    args = parser.parse_args(argv)
    try:
        paths = staged_paths() if args.staged else tracked_paths()
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        print(f"Kunne ikke lese Git-indeks: {exc}", file=sys.stderr)
        return 2
    errors = scan_paths(paths)
    for error in errors:
        print(f"FEIL: {error}", file=sys.stderr)
    if errors:
        print("Commit/push stoppet for å beskytte kliniske data.", file=sys.stderr)
        return 1
    print(f"Sikkerhetskontroll OK ({len(paths)} filer).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
