from __future__ import annotations

from pathlib import Path

from .excel import ExcelReportWriter
from .io import RunDiscovery
from .matching import annotate_exact_matches
from .models import MergeResult, MergedRow
from .qc import evaluate_qc


class MergeService:
    def __init__(
        self,
        discovery: RunDiscovery | None = None,
        writer: ExcelReportWriter | None = None,
    ):
        self.discovery = discovery or RunDiscovery()
        self.writer = writer or ExcelReportWriter()

    def process(self, run_directory: Path, expected_samples: int = 24) -> MergeResult:
        manifest = self.discovery.discover(run_directory, expected_samples)
        rows = [
            MergedRow(
                source=source,
                sample=sample_file.sample,
                sample_number=sample_file.sample_number,
                total_reads=sample_file.total_reads,
                target=sample_file.target,
                run_date=manifest.run_date,
            )
            for sample_file in manifest.sample_files
            for source in sample_file.rows
        ]
        annotate_exact_matches(rows)
        qc = evaluate_qc(rows)
        return MergeResult(manifest, tuple(rows), qc)

    def export(self, result: MergeResult, output: Path, *, overwrite: bool = False) -> Path:
        return self.writer.write(result.rows, output, overwrite=overwrite)
