from __future__ import annotations

import csv
import re
from pathlib import Path

from .models import MoleculeType, RunManifest, SampleFile, SourceRow, Target

SOURCE_HEADERS = (
    "Rank",
    "Sequence",
    "Length",
    "Merge count",
    "V-gene",
    "J-gene",
    "% total reads",
    "Cumulative %",
    "Mutation rate to partial V-gene (%)",
    "In-frame (Y/N)",
    "No Stop codon (Y/N)",
    "V-coverage",
    "CDR3 Seq",
)

SUMMARY_SUFFIX = "read_summary_merged_top10_searchtop500.tsv"
SAMPLE_RE = re.compile(
    r"^(?P<sample>.+)_S(?P<number>\d+)_L\d+_\d+_combined\.fastq_",
    re.IGNORECASE,
)
DATE_RE = re.compile(r"(?P<date>\d{4}_\d{2}_\d{2})")


class ValidationError(ValueError):
    """Input data cannot be processed safely."""


def parse_number(value: str, *, allow_blank: bool = False) -> float | None:
    text = (value or "").strip().replace("\u00a0", "").replace(" ", "")
    if not text:
        if allow_blank:
            return None
        raise ValidationError("Empty numeric value")
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    else:
        text = text.replace(",", ".")
    try:
        return float(text)
    except ValueError as exc:
        raise ValidationError(f"Invalid numeric value: {value!r}") from exc


def parse_integer(value: str) -> int:
    number = parse_number(value)
    if number is None or not float(number).is_integer():
        raise ValidationError(f"Expected integer, got {value!r}")
    return int(number)


class SummaryReader:
    def read(self, path: Path, target: Target) -> SampleFile:
        match = SAMPLE_RE.match(path.name)
        if not match:
            raise ValidationError(f"Cannot parse sample name/S-number from {path.name}")

        try:
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                records = list(csv.reader(handle, delimiter="\t"))
        except UnicodeDecodeError:
            with path.open("r", encoding="cp1252", newline="") as handle:
                records = list(csv.reader(handle, delimiter="\t"))

        if not records:
            raise ValidationError(f"Empty file: {path.name}")
        header = records[0]
        if len(header) != 16:
            raise ValidationError(f"{path.name}: expected 16 fields, found {len(header)}")
        if tuple(cell.strip() for cell in header[3:]) != SOURCE_HEADERS:
            raise ValidationError(f"{path.name}: unknown or changed header")
        if header[1].strip().lower() != "total count":
            raise ValidationError(f"{path.name}: missing Total count")

        total_reads = parse_integer(header[2])
        rows: list[SourceRow] = []
        seen_ranks: set[int] = set()
        for line_number, record in enumerate(records[1:], start=2):
            if not any(cell.strip() for cell in record):
                continue
            if len(record) != 16:
                raise ValidationError(
                    f"{path.name}, line {line_number}: expected 16 fields, found {len(record)}"
                )
            rank = parse_integer(record[3])
            if rank in seen_ranks:
                raise ValidationError(f"{path.name}: duplicate rank {rank}")
            seen_ranks.add(rank)
            sequence = record[4].strip().upper()
            if not sequence or not re.fullmatch(r"[ACGTN]+", sequence):
                raise ValidationError(f"{path.name}, rank {rank}: invalid DNA sequence")
            mutation_rate = parse_number(record[11], allow_blank=True)
            v_coverage = parse_number(record[14], allow_blank=True)
            rows.append(
                SourceRow(
                    rank=rank,
                    sequence=sequence,
                    length=parse_integer(record[5]),
                    merge_count=parse_integer(record[6]),
                    v_gene=record[7].strip(),
                    j_gene=record[8].strip(),
                    percent_total_reads=round(float(parse_number(record[9])), 2),
                    cumulative_percent=round(float(parse_number(record[10])), 2),
                    mutation_rate=None if mutation_rate is None else round(float(mutation_rate), 2),
                    in_frame=record[12].strip().upper(),
                    no_stop_codon=record[13].strip().upper(),
                    v_coverage=None if v_coverage is None else round(float(v_coverage), 2),
                    cdr3_sequence=record[15].strip(),
                )
            )
        if not rows:
            raise ValidationError(f"{path.name}: no result lines")
        rows.sort(key=lambda item: item.rank)
        return SampleFile(
            path=path,
            sample=match.group("sample"),
            sample_number=int(match.group("number")),
            target=target,
            molecule_type=detect_molecule_type(match.group("sample")),
            total_reads=total_reads,
            rows=tuple(rows),
        )


def detect_molecule_type(sample: str) -> MoleculeType:
    """Infer gDNA vs cDNA from the sample identifier.

    A sample name like ``26OUM12345_cdna`` is treated as cDNA; anything else
    is gDNA. The suffix is case-insensitive and must be a full token so that
    patient IDs that merely contain "cd" stay gDNA.
    """
    if not sample:
        return "gDNA"
    if re.search(r"(?:^|_)(?:cDNA|cdna)(?:$|_)", sample, flags=re.IGNORECASE):
        return "cDNA"
    return "gDNA"


class RunDiscovery:
    def __init__(self, reader: SummaryReader | None = None):
        self.reader = reader or SummaryReader()

    def discover(self, run_directory: Path, expected_samples: int = 24) -> RunManifest:
        run_directory = run_directory.expanduser().resolve()
        if not run_directory.is_dir():
            raise ValidationError(f"Run folder does not exist: {run_directory}")
        date_match = DATE_RE.search(run_directory.name)
        if not date_match:
            raise ValidationError("Run folder must contain date in format YYYY_MM_DD")
        run_date = date_match.group("date")

        leader_dirs = [
            path for path in run_directory.iterdir()
            if path.is_dir() and path.name.upper().endswith("_LEADER_OUTPUT")
        ]
        fr1_dirs = [
            path for path in run_directory.iterdir()
            if path.is_dir() and path.name.upper().endswith("_IGH_FR1_OUTPUT")
        ]
        if len(leader_dirs) != 1 or len(fr1_dirs) != 1:
            raise ValidationError(
                f"Expected one Leader and one FR1 folder, found {len(leader_dirs)} and {len(fr1_dirs)}"
            )

        leader_paths = sorted(leader_dirs[0].glob(f"*{SUMMARY_SUFFIX}"))
        fr1_paths = sorted(fr1_dirs[0].glob(f"*{SUMMARY_SUFFIX}"))
        if not leader_paths and not fr1_paths:
            raise ValidationError("No top10 summary files found")

        files = [
            *(self.reader.read(path, "Leader") for path in leader_paths),
            *(self.reader.read(path, "FR1") for path in fr1_paths),
        ]
        seen_keys: set[tuple[str, int, str]] = set()
        for item in files:
            key = (item.sample, item.sample_number, item.target)
            if key in seen_keys:
                raise ValidationError(
                    f"Duplicate: {item.sample}, S{item.sample_number}, {item.target}"
                )
            seen_keys.add(key)

        leader_keys = {(item.sample, item.sample_number) for item in files if item.target == "Leader"}
        fr1_keys = {(item.sample, item.sample_number) for item in files if item.target == "FR1"}
        if leader_keys != fr1_keys:
            missing_fr1 = sorted(leader_keys - fr1_keys)
            missing_leader = sorted(fr1_keys - leader_keys)
            parts = []
            if missing_fr1:
                parts.append(f"missing FR1 for {len(missing_fr1)} sample(s)")
            if missing_leader:
                parts.append(f"missing Leader for {len(missing_leader)} sample(s)")
            raise ValidationError("; ".join(parts))

        warnings: list[str] = []
        if len(leader_paths) != expected_samples:
            warnings.append(
                f"Expected {expected_samples} samples per target, found {len(leader_paths)}"
            )
        files.sort(key=lambda item: (item.sample_number, 0 if item.target == "Leader" else 1))
        return RunManifest(
            run_directory=run_directory,
            run_date=run_date,
            sample_files=tuple(files),
            expected_samples=expected_samples,
            warnings=tuple(warnings),
        )
