from __future__ import annotations

import json
import re
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .external import ArrestBatchResult, ExternalBatch, ImgtBatchResult
from .models import MergedRow
from .privacy import ensure_outside_git


def _gene(value: str) -> str:
    match = re.search(r"(IGH[VDJ][A-Za-z0-9/-]+\*\d+)", value)
    return match.group(1) if match else value


def generate_clinical_report_package(
    run_directory: Path,
    rows: tuple[MergedRow, ...] | list[MergedRow],
    batch: ExternalBatch,
    imgt: ImgtBatchResult,
    arrest: ArrestBatchResult | None = None,
) -> Path:
    output = run_directory.resolve() / f"{batch.run_date}_reports" / batch.session_id
    ensure_outside_git(output)
    output.mkdir(parents=True, exist_ok=True)
    candidates = batch.by_id()
    imgt_records = {item.external_id: item for item in imgt.records}
    arrest_records = {item.external_id: item for item in arrest.records} if arrest else {}
    by_sample: dict[str, list[str]] = {}
    for external_id in batch.candidate_ids:
        by_sample.setdefault(candidates[external_id].sample, []).append(external_id)

    generated = []
    for sample, external_ids in by_sample.items():
        name = re.sub(r"[^A-Za-z0-9_.-]", "_", sample)
        path = output / f"{name}_IGHV_report_draft.pdf"
        _write_sample_report(
            path, sample, external_ids, rows, candidates, imgt_records,
            arrest_records,
        )
        generated.append(path.name)
    audit = {
        "schema_version": 1,
        "status": "DRAFT - requires specialist approval",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_date": batch.run_date,
        "session_id": batch.session_id,
        "reports": generated,
        "imgt_version": imgt.program_version,
        "imgt_reference_release": imgt.reference_release,
        "imgt_records": [asdict(item) for item in imgt.records],
        "arrest_records": [asdict(item) for item in arrest.records] if arrest else [],
    }
    (output / "report_data.audit.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return output


def _write_sample_report(
    path, sample, external_ids, rows, candidates, imgt_records, arrest_records
) -> None:
    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(
        str(path), pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=16 * mm, bottomMargin=16 * mm,
    )
    story = [
        Paragraph("IGHV-SHM report draft", styles["Title"]),
        Paragraph(f"<b>Sample:</b> {sample}", styles["BodyText"]),
        Paragraph("<b>ANALYSIS:</b> LymphoTrack IGH SHM (HTS)", styles["BodyText"]),
        Paragraph(
            "<b>Analysis tools:</b> LymphoTrack, IMGT/V-QUEST"
            + (" and ARResT/AssignSubsets" if arrest_records else ""),
            styles["BodyText"],
        ),
    ]
    sample_rows = [row for row in rows if row.sample == sample]
    depths = {
        target: next((r.total_reads for r in sample_rows if r.target == target), None)
        for target in ("Leader", "FR1")
    }
    story.append(
        Paragraph(
            f"<b>Depth:</b> {depths['Leader'] or '-'} reads (Leader), "
            f"{depths['FR1'] or '-'} reads (FR1)", styles["BodyText"]
        )
    )
    for number, external_id in enumerate(external_ids, 1):
        candidate = candidates[external_id]
        local = rows[candidate.row_index]
        record = imgt_records[external_id]
        arrest = arrest_records.get(external_id)
        support_label = f"Leader-{local.source.rank}"
        fr1_support = [
            row.source.percent_total_reads
            for row in sample_rows
            if row.target == "FR1" and support_label in row.comment
        ]
        identity = (
            f"{record.v_identity_percent:.1f} %" if record.v_identity_percent is not None
            else "not calculated"
        )
        counts = (
            f"{record.v_identity_numerator}/{record.v_identity_denominator} nt"
            if record.v_identity_numerator is not None else "not available"
        )
        functionality = (
            "Functional (productive)" if record.productive is True
            else "Non-functional (unproductive)" if record.productive is False
            else record.functionality or "Not conclusively determined"
        )
        subset = (arrest.subset if arrest else "") or record.cll_subset or "Not detected"
        data = [
            ["Leader fraction", f"{local.source.percent_total_reads:.2f} %"],
            ["FR1 support", ", ".join(f"{value:.2f} %" for value in fr1_support) or "Not detected"],
            ["IGHV / IGHD / IGHJ", " / ".join(
                [_gene(record.v_call), _gene(record.d_call) or "-", _gene(record.j_call)]
            )],
            ["VH identity", f"{identity} ({counts})"],
            ["Functionality", functionality],
            ["CDR3 (AA)", record.cdr3_aa or record.junction_aa or "-"],
            ["CDR3 length", str(record.cdr3_aa_length or record.junction_aa_length or "-")],
            ["Insertion/deletion", "; ".join(filter(None, [record.insertions, record.deletions])) or "Not detected"],
            ["Subset", subset],
        ]
        table = Table(data, colWidths=[48 * mm, 112 * mm])
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#EAF0F5")),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#AAB7C2")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
        ]))
        story.extend([Spacer(1, 5 * mm), Paragraph(
            f"Rearrangering {number} - Leader-{local.source.rank}", styles["Heading2"]
        ), table])
    doc.build(story)
