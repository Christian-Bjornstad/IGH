from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

Target = Literal["Leader", "FR1"]


@dataclass(frozen=True)
class SourceRow:
    rank: int
    sequence: str
    length: int
    merge_count: int
    v_gene: str
    j_gene: str
    percent_total_reads: float
    cumulative_percent: float
    mutation_rate: float | None
    in_frame: str
    no_stop_codon: str
    v_coverage: float | None
    cdr3_sequence: str


@dataclass(frozen=True)
class SampleFile:
    path: Path
    sample: str
    sample_number: int
    target: Target
    total_reads: int
    rows: tuple[SourceRow, ...]


@dataclass(frozen=True)
class RunManifest:
    run_directory: Path
    run_date: str
    sample_files: tuple[SampleFile, ...]
    expected_samples: int
    warnings: tuple[str, ...] = ()

    @property
    def leader_files(self) -> tuple[SampleFile, ...]:
        return tuple(item for item in self.sample_files if item.target == "Leader")

    @property
    def fr1_files(self) -> tuple[SampleFile, ...]:
        return tuple(item for item in self.sample_files if item.target == "FR1")


@dataclass
class MergedRow:
    source: SourceRow
    sample: str
    sample_number: int
    total_reads: int
    target: Target
    run_date: str
    other_samples: str = ""
    subset: str = ""
    comment: str = ""

    @property
    def fasta(self) -> str:
        return f">{self.sample}-{self.target}-{self.source.rank}\n{self.source.sequence}"


@dataclass(frozen=True)
class QcItem:
    category: str
    sample: str
    target: str
    status: Literal["OK", "VARSEL", "FEIL"]
    message: str


@dataclass(frozen=True)
class QcReport:
    controls: tuple[QcItem, ...] = ()

    @property
    def error_count(self) -> int:
        return sum(item.status == "FEIL" for item in self.controls)


@dataclass(frozen=True)
class MergeResult:
    manifest: RunManifest
    rows: tuple[MergedRow, ...]
    qc: QcReport
