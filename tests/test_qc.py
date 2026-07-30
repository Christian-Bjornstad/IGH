from __future__ import annotations

from igh_merge.models import MergedRow, SourceRow
from igh_merge.qc import evaluate_qc


def merged(
    sample: str,
    target: str,
    rank: int,
    *,
    reads: int = 50_000,
    percent: float = 3.0,
    mutation: float | None = 2.0,
    coverage: float = 100.0,
    in_frame: str = "Y",
    no_stop: str = "Y",
    v_gene: str = "IGHV1-2_01",
) -> MergedRow:
    sequence = ("ACGT" * 40) + ("A" * rank)
    return MergedRow(
        SourceRow(
            rank,
            sequence,
            len(sequence),
            100,
            v_gene,
            "IGHJ4_02",
            percent,
            percent,
            mutation,
            in_frame,
            no_stop,
            coverage,
            "CARDR",
        ),
        sample,
        1,
        reads,
        target,
        "2099_01_02",
    )


def test_control_boundaries_are_evaluated_per_target():
    rows = []
    for target in ("Leader", "FR1"):
        rows.extend(
            [
                merged("IGH_POS", target, 1, percent=2.5),
                merged("IGH_SHM_POS", target, 1, percent=2.5, mutation=2.0),
                merged("NGS_NEG", target, 1, percent=0.99),
                merged("NK", target, 1, reads=9_999, percent=10),
            ]
        )
    report = evaluate_qc(rows)
    assert len(report.controls) == 8
    assert all(item.status == "OK" for item in report.controls)
