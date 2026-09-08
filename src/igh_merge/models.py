from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

Target = Literal["Leader", "FR1"]
MoleculeType = Literal["gDNA", "cDNA"]

CONTROL_SAMPLE_ORDER: tuple[str, ...] = (
    "IGH_SHM_POS",
    "IGH_POS",
    "NGS_NEG",
    "NK",
)
_CONTROL_PRIORITY = {sample: index for index, sample in enumerate(CONTROL_SAMPLE_ORDER)}


def sample_sort_key(sample: str, sample_number: int) -> tuple[int, int, int]:
    """Place controls first in the laboratory-defined order.

    Patient samples retain their numeric input/run order after the controls.
    """
    priority = _CONTROL_PRIORITY.get(sample)
    if priority is not None:
        return (0, priority, sample_number)
    return (1, sample_number, 0)


def merged_row_sort_key(row: "MergedRow") -> tuple[int, int, int, int, int]:
    sample_key = sample_sort_key(row.sample, row.sample_number)
    return (*sample_key, 0 if row.target == "Leader" else 1, row.source.rank)


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
    molecule_type: MoleculeType
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
    molecule_type: MoleculeType
    run_date: str
    external_id: str = ""
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
