from __future__ import annotations

import csv
from pathlib import Path

import pytest

from igh_merge.io import SOURCE_HEADERS


def _row(
    rank: int,
    sequence: str,
    *,
    percent: float = 3.0,
    cumulative: float | None = None,
    mutation: float | None = 2.0,
    in_frame: str = "Y",
    no_stop: str = "Y",
    coverage: float = 100.0,
    cdr3: str = "CARDR",
    v_gene: str = "IGHV1-2_01",
    j_gene: str = "IGHJ4_02",
) -> list[str]:
    cumulative = percent if cumulative is None else cumulative
    return [
        str(rank),
        sequence,
        str(len(sequence)),
        str(max(1, int(percent * 100))),
        v_gene,
        j_gene,
        str(percent).replace(".", ","),
        str(cumulative).replace(".", ","),
        "" if mutation is None else str(mutation).replace(".", ","),
        in_frame,
        no_stop,
        str(coverage).replace(".", ","),
        cdr3,
    ]


def write_summary(
    directory: Path,
    sample: str,
    sample_number: int,
    rows: list[list[str]],
    *,
    reads: int = 100_000,
    lane: int = 1,
) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    filename = (
        f"{sample}_S{sample_number}_L{lane:03d}_001_combined.fastq_"
        "read_summary_merged_top10_searchtop500.tsv"
    )
    path = directory / filename
    metadata = [str(path), "Total count", str(reads)]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow([*metadata, *SOURCE_HEADERS])
        for values in rows:
            writer.writerow([*metadata, *values])
    return path


@pytest.fixture
def run_factory(tmp_path):
    def create(date: str = "2099_01_02"):
        root = tmp_path / f"{date}_IGHV"
        leader = root / f"{date}_LEADER_output"
        fr1 = root / f"{date}_IGH_FR1_output"
        leader.mkdir(parents=True)
        fr1.mkdir(parents=True)
        return root, leader, fr1

    return create


@pytest.fixture
def make_row():
    return _row
