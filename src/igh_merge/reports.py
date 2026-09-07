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

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.shared import Pt, RGBColor

from .external import ArrestBatchResult, ExternalBatch, ImgtBatchResult
from .models import MergedRow
from .privacy import ensure_outside_git


def _gene(value: str) -> str:
    match = re.search(r"(IGH[VDJ][A-Za-z0-9/-]+\*\d+)", value)
    return match.group(1) if match else value


def _sample_report_records(
    rows: tuple[MergedRow, ...] | list[MergedRow],
    batch: ExternalBatch,
    imgt: ImgtBatchResult,
    arrest: ArrestBatchResult | None,
) -> dict[str, list[dict[str, str]]]:
    """Group rows by sample and produce a serialisable record for each
    rearrangement (used by both the PDF and Word renderers)."""
    candidates = batch.by_id()
    imgt_records = {item.external_id: item for item in imgt.records}
    arrest_records = (
        {item.external_id: item for item in arrest.records} if arrest else {}
    )
    by_sample: dict[str, list[str]] = {}
    for external_id in batch.candidate_ids:
        by_sample.setdefault(
            candidates[external_id].sample, []
        ).append(external_id)
    result: dict[str, list[dict[str, str]]] = {}
    for sample, external_ids in by_sample.items():
        local_rows = [r for r in rows if r.sample == sample]
        depths = {
            target: next(
                (r.total_reads for r in local_rows if r.target == target), None
            )
            for target in ("Leader", "FR1")
        }
        sample_records: list[dict[str, str]] = []
        for external_id in external_ids:
            candidate = candidates[external_id]
            local = rows[candidate.row_index]
            record = imgt_records[external_id]
            arrest_record = arrest_records.get(external_id)
            support_label = f"Leader-{local.source.rank}"
            fr1_support = [
                row.source.percent_total_reads
                for row in local_rows
                if row.target == "FR1" and support_label in row.comment
            ]
            identity = (
                f"{record.v_identity_percent:.1f} %"
                if record.v_identity_percent is not None
                else "not calculated"
            )
            counts = (
                f"{record.v_identity_numerator}/{record.v_identity_denominator} nt"
                if record.v_identity_numerator is not None
                else "not available"
            )
            functionality = (
                "Functional (productive)"
                if record.productive is True
                else "Non-functional (unproductive)"
                if record.productive is False
                else record.functionality or "Not conclusively determined"
            )
            subset = (
                (arrest_record.subset if arrest_record else "")
                or record.cll_subset
                or "Not detected"
            )
            sample_records.append(
                {
                    "number": str(len(sample_records) + 1),
                    "rank_label": f"Leader-{local.source.rank}",
                    "leader_fraction": f"{local.source.percent_total_reads:.2f} %",
                    "fr1_support": (
                        ", ".join(
                            f"{value:.2f} %" for value in fr1_support
                        )
                        or "Not detected"
                    ),
                    "genes": " / ".join(
                        [
                            _gene(record.v_call),
                            _gene(record.d_call) or "-",
                            _gene(record.j_call),
                        ]
                    ),
                    "identity": f"{identity} ({counts})",
                    "functionality": functionality,
                    "cdr3": record.cdr3_aa or record.junction_aa or "-",
                    "cdr3_length": str(
                        record.cdr3_aa_length or record.junction_aa_length or "-"
                    ),
                    "indel": "; ".join(
                        filter(None, [record.insertions, record.deletions])
                    )
                    or "Not detected",
                    "subset": subset,
                    "external_id": record.external_id,
                    "depth_leader": str(depths.get("Leader") or "-"),
                    "depth_fr1": str(depths.get("FR1") or "-"),
                    "comment": local.comment or "",
                }
            )
        result[sample] = sample_records
    return result


def _write_sample_pdf(
    path: Path,
    sample: str,
    records: list[dict[str, str]],
    run_date: str,
    imgt_version: str,
    imgt_release: str,
    has_arrest: bool,
) -> None:
    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(
        str(path),
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
    )
    story = [
        Paragraph("IGHV-SHM report draft", styles["Title"]),
        Paragraph(f"<b>Sample:</b> {sample}", styles["BodyText"]),
        Paragraph(
            f"<b>Run date:</b> {run_date}",
            styles["BodyText"],
        ),
        Paragraph(
            "<b>Analysis:</b> LymphoTrack IGH SHM (HTS)",
            styles["BodyText"],
        ),
        Paragraph(
            "<b>Analysis tools:</b> LymphoTrack, IMGT/V-QUEST"
            + (" and ARResT/AssignSubsets" if has_arrest else ""),
            styles["BodyText"],
        ),
        Paragraph(
            f"<b>IMGT/V-QUEST version:</b> {imgt_version or 'unknown'}<br/>"
            f"<b>IMGT reference release:</b> {imgt_release or 'unknown'}",
            styles["BodyText"],
        ),
    ]
    if records:
        first = records[0]
        story.append(
            Paragraph(
                f"<b>Depth:</b> {first['depth_leader']} reads (Leader), "
                f"{first['depth_fr1']} reads (FR1)",
                styles["BodyText"],
            )
        )
    for rec in records:
        data = [
            ["External ID", rec["external_id"]],
            ["Leader fraction", rec["leader_fraction"]],
            ["FR1 support", rec["fr1_support"]],
            ["IGHV / IGHD / IGHJ", rec["genes"]],
            ["VH identity", rec["identity"]],
            ["Functionality", rec["functionality"]],
            ["CDR3 (AA)", rec["cdr3"]],
            ["CDR3 length", rec["cdr3_length"]],
            ["Insertion / deletion", rec["indel"]],
            ["Subset", rec["subset"]],
            ["Comment", rec["comment"] or "-"],
        ]
        table = Table(data, colWidths=[48 * mm, 112 * mm])
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#EDE7F6")),
                    ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#B6A6CA")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 9),
                ]
            )
        )
        story.extend(
            [
                Spacer(1, 5 * mm),
                Paragraph(
                    f"Rearrangement {rec['number']} - {rec['rank_label']}",
                    styles["Heading2"],
                ),
                table,
            ]
        )
        story.append(Spacer(1, 6 * mm))
        story.append(
            Paragraph(
                "<i>DRAFT - requires specialist approval before clinical use.</i>",
                styles["BodyText"],
            )
        )
        doc.build(story)


def _write_sample_docx(
    path: Path,
    sample: str,
    records: list[dict[str, str]],
    run_date: str,
    imgt_version: str,
    imgt_release: str,
    has_arrest: bool,
) -> None:
    document = Document()
    title = document.add_heading("IGHV-SHM report draft", level=0)
    title.alignment = 1  # centered
    document.add_paragraph()
    p = document.add_paragraph()
    p.add_run("Sample: ").bold = True
    p.add_run(sample)
    p = document.add_paragraph()
    p.add_run("Run date: ").bold = True
    p.add_run(run_date)
    p = document.add_paragraph()
    p.add_run("Analysis: ").bold = True
    p.add_run("LymphoTrack IGH SHM (HTS)")
    p = document.add_paragraph()
    p.add_run("Analysis tools: ").bold = True
    p.add_run(
        "LymphoTrack, IMGT/V-QUEST"
        + (" and ARResT/AssignSubsets" if has_arrest else "")
    )
    p = document.add_paragraph()
    p.add_run("IMGT/V-QUEST version: ").bold = True
    p.add_run(imgt_version or "unknown")
    p.add_run("    ")
    p.add_run("Reference release: ").bold = True
    p.add_run(imgt_release or "unknown")
    if records:
        first = records[0]
        p = document.add_paragraph()
        p.add_run("Depth: ").bold = True
        p.add_run(f"{first['depth_leader']} reads (Leader), "
                  f"{first['depth_fr1']} reads (FR1)")
    for rec in records:
        document.add_heading(
            f"Rearrangement {rec['number']} - {rec['rank_label']}",
            level=2,
        )
        table = document.add_table(rows=0, cols=2)
        table.style = "Light Grid Accent 4"
        table.alignment = WD_TABLE_ALIGNMENT.LEFT
        rows = [
            ("External ID", rec["external_id"]),
            ("Leader fraction", rec["leader_fraction"]),
            ("FR1 support", rec["fr1_support"]),
            ("IGHV / IGHD / IGHJ", rec["genes"]),
            ("VH identity", rec["identity"]),
            ("Functionality", rec["functionality"]),
            ("CDR3 (AA)", rec["cdr3"]),
            ("CDR3 length", rec["cdr3_length"]),
            ("Insertion / deletion", rec["indel"]),
            ("Subset", rec["subset"]),
            ("Comment", rec["comment"] or "-"),
        ]
        for label, value in rows:
            cells = table.add_row().cells
            cells[0].text = label
            cells[1].text = value
            for run in cells[0].paragraphs[0].runs:
                run.bold = True
                run.font.size = Pt(10)
            for run in cells[1].paragraphs[0].runs:
                run.font.size = Pt(10)
    document.add_paragraph()
    p = document.add_paragraph()
    run = p.add_run("DRAFT - requires specialist approval before clinical use.")
    run.italic = True
    run.font.color.rgb = RGBColor(0xB4, 0x53, 0x09)
    document.save(str(path))


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
    by_sample = _sample_report_records(rows, batch, imgt, arrest)
    safe_names = {
        sample: re.sub(r"[^A-Za-z0-9_.-]", "_", sample)
        for sample in by_sample
    }
    for sample, records in by_sample.items():
        name = safe_names[sample]
        _write_sample_pdf(
            output / f"{name}_IGHV_report_draft.pdf",
            sample,
            records,
            batch.run_date,
            imgt.program_version,
            imgt.reference_release,
            has_arrest=bool(arrest),
        )
        _write_sample_docx(
            output / f"{name}_IGHV_report_draft.docx",
            sample,
            records,
            batch.run_date,
            imgt.program_version,
            imgt.reference_release,
            has_arrest=bool(arrest),
        )
    audit = {
        "schema_version": 1,
        "status": "DRAFT - requires specialist approval",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_date": batch.run_date,
        "session_id": batch.session_id,
        "imgt_version": imgt.program_version,
        "imgt_reference_release": imgt.reference_release,
        "imgt_records": [asdict(item) for item in imgt.records],
        "arrest_records": [asdict(item) for item in arrest.records]
        if arrest
        else [],
    }
    (output / "report_data.audit.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return output
