from __future__ import annotations

import json
import re
import hashlib
import shutil
from html import escape
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle, Image, PageBreak

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.shared import Pt, RGBColor, Inches

from .external import ArrestBatchResult, ExternalBatch, ImgtBatchResult, ImgtRecord, sequence_sha256
from .models import MergedRow
from .privacy import ensure_outside_git
from .evidence import EvidenceManifest, validate_evidence_manifest
from .excel import ExcelReportWriter
from .imgt_observations import j_call_notes, record_observation_text


def _gene(value: str) -> str:
    match = re.search(r"(IGH[VDJ][A-Za-z0-9/-]+\*\d+)", value)
    return match.group(1) if match else value


def _sample_report_records(
    rows: tuple[MergedRow, ...] | list[MergedRow],
    batch: ExternalBatch,
    imgt: ImgtBatchResult,
    arrest: ArrestBatchResult | None,
    evidence: EvidenceManifest | None = None,
) -> dict[str, list[dict[str, str]]]:
    """Group rows by sample and produce a serialisable record for each
    rearrangement (used by both the PDF and Word renderers)."""
    candidates = batch.by_id()
    evidence_by_id = {e.external_id: e for e in evidence.entries} if evidence else {}
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
            if (local.sample != candidate.sample or local.target != candidate.target
                or local.source.rank != candidate.rank or sequence_sha256(local.source.sequence) != candidate.sequence_sha256):
                raise ValueError('Report row does not match candidate ID/sequence/target/rank')
            record = imgt_records.get(external_id)
            missing_imgt = record is None
            if record is None:
                record = ImgtRecord(external_id, None, None, None, '', '', '', None, '', '', '', '', '')
            entry = evidence_by_id.get(external_id)
            arrest_record = arrest_records.get(external_id)
            support_label = f"Leader-{local.source.rank}"
            fr1_support = [
                row.source.percent_total_reads
                for row in local_rows
                if local.target == "Leader" and row.target == "FR1" and
                re.search(r"(?<![A-Za-z0-9-])" + re.escape(support_label) + r"(?![A-Za-z0-9-])", row.comment)
            ]
            identity = (
                f"{record.selected_identity_percent:.1f} %"
                if record.selected_identity_percent is not None
                else "not calculated"
            )
            counts = (
                f"{record.selected_identity_counts[0]}/{record.selected_identity_counts[1]} nt"
                if record.selected_identity_counts[0] is not None
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
                    "rank_label": f"{local.target}-{local.source.rank}",
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
                            record.j_call,
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
                    "imgt_subset": record.cll_subset or 'Not assigned / not analyzed',
                    "arrest_subset": arrest_record.subset if arrest_record else 'ARResT analysis missing',
                    "identity_source": record.selected_identity_source,
                    "raw_identities": f'{record.raw_identity_percent or "-"}; with indel events: {record.raw_identity_with_indel_events or "-"}',
                    "observations": record_observation_text(record),
                    "j_notes": j_call_notes(record.j_call) or '-',
                    "analysis_status": 'IMGT analysis missing' if missing_imgt else 'IMGT result available',
                    "summary_text": entry.sections.get('00_summary', '') if entry else 'IMGT evidence missing',
                    "images": entry.images if entry else (),
                    "missing_evidence": '; '.join(f'{k}: {v}' for k,v in entry.missing_sections.items()) if entry else 'IMGT evidence missing',
                    "sequence_sha256": candidate.sequence_sha256,
                    "session_id": batch.session_id,
                    "molecule_type": candidate.molecule_type,
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
        Paragraph(f"<b>Sample:</b> {escape(sample)}", styles["BodyText"]),
        Paragraph(
            f"<b>Run date:</b> {escape(run_date)}",
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
            f"<b>IMGT/V-QUEST version:</b> {escape(imgt_version or 'unknown')}<br/>"
            f"<b>IMGT reference release:</b> {escape(imgt_release or 'unknown')}",
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
            ["Target fraction", rec["leader_fraction"]],
            ["FR1 support", rec["fr1_support"]],
            ["IGHV / IGHD / IGHJ", rec["genes"]],
            ["VH identity", rec["identity"]],
            ["Functionality", rec["functionality"]],
            ["CDR3 (AA)", rec["cdr3"]],
            ["CDR3 length", rec["cdr3_length"]],
            ["Insertion / deletion", rec["indel"]],
            ["IMGT subset", rec["imgt_subset"]],
            ["ARResT subset", rec["arrest_subset"]],
            ["Identity source", rec["identity_source"]],
            ["Raw identities", rec["raw_identities"]],
            ["J call notes", rec["j_notes"]],
            ["Manual observations", rec["observations"]],
            ["Analysis status", rec["analysis_status"]],
            ["Molecule type", rec["molecule_type"]],
            ["Comment", rec["comment"] or "-"],
        ]
        data = [[Paragraph(escape(str(value)), styles['BodyText']) for value in row] for row in data]
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
                    f"Rearrangement {rec['number']} - {escape(rec['rank_label'])}",
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
        story.append(Paragraph('IMGT summary', styles['Heading2']))
        for line in rec['summary_text'].splitlines():
            story.append(Paragraph(escape(line) or ' ', styles['BodyText']))
        story.append(Paragraph(escape(rec['missing_evidence']), styles['BodyText']))
        for filename in rec['images']:
            image = Image(filename)
            factor = min(160 * mm / image.imageWidth, 210 * mm / image.imageHeight, 1)
            image.drawWidth, image.drawHeight = image.imageWidth * factor, image.imageHeight * factor
            story.extend([PageBreak(), Paragraph(escape(Path(filename).stem), styles['Heading2']), image])
        story.extend([Spacer(1, 5 * mm), Paragraph('Specialist assessment: __________________________', styles['BodyText'])])
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
            ("Target fraction", rec["leader_fraction"]),
            ("FR1 support", rec["fr1_support"]),
            ("IGHV / IGHD / IGHJ", rec["genes"]),
            ("VH identity", rec["identity"]),
            ("Functionality", rec["functionality"]),
            ("CDR3 (AA)", rec["cdr3"]),
            ("CDR3 length", rec["cdr3_length"]),
            ("Insertion / deletion", rec["indel"]),
            ("IMGT subset", rec["imgt_subset"]),
            ("ARResT subset", rec["arrest_subset"]),
            ("Identity source", rec["identity_source"]),
            ("Raw identities", rec["raw_identities"]),
            ("J call notes", rec["j_notes"]),
            ("Manual observations", rec["observations"]),
            ("Analysis status", rec["analysis_status"]),
            ("Molecule type", rec["molecule_type"]),
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
        document.add_heading('IMGT summary', level=2)
        document.add_paragraph(rec['summary_text'])
        document.add_paragraph(rec['missing_evidence'])
        for filename in rec['images']:
            document.add_page_break()
            document.add_heading(Path(filename).stem, level=2)
            from docx.image.image import Image as DocxImage
            image = DocxImage.from_file(filename)
            width, height = image.px_width, image.px_height
            factor = min(6.3 / width, 8.3 / height)
            document.add_picture(filename, width=Inches(width * factor), height=Inches(height * factor))
        document.add_paragraph('Specialist assessment: __________________________')
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
    *, evidence: EvidenceManifest | None = None,
) -> Path:
    output = run_directory.resolve() / f"{batch.run_date}_reports" / batch.session_id
    ensure_outside_git(output)
    if evidence:
        validate_evidence_manifest(evidence, batch)
    if output.exists():
        output = output / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    output.mkdir(parents=True, exist_ok=False)
    by_sample = _sample_report_records(rows, batch, imgt, arrest, evidence)
    export_rows = [replace(row) for row in rows]
    for candidate in batch.candidates:
        export_rows[candidate.row_index].external_id = candidate.external_id
    ExcelReportWriter().write(export_rows, output / 'analysis.xlsx')
    if evidence:
        evidence_directory = output / 'evidence'
        evidence_directory.mkdir()
        for entry in evidence.entries:
            directory = evidence_directory / entry.external_id
            directory.mkdir()
            (directory / 'summary.txt').write_text(entry.sections.get('00_summary', ''), encoding='utf-8')
            (directory / 'evidence.audit.json').write_text(json.dumps(asdict(entry), ensure_ascii=False, indent=2), encoding='utf-8')
            for filename in entry.images:
                shutil.copy2(filename, directory / Path(filename).name)
    safe_names = {
        sample: re.sub(r"[^A-Za-z0-9_.-]", "_", sample)
        for sample in by_sample
    }
    counts = {}
    for sample, name in list(safe_names.items()):
        key = name.casefold()
        counts[key] = counts.get(key, 0) + 1
    for sample, name in list(safe_names.items()):
        if counts[name.casefold()] > 1:
            safe_names[sample] = name + '_' + hashlib.sha256(sample.encode()).hexdigest()[:8]
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
        "complete": set(batch.candidate_ids) == {r.external_id for r in imgt.records},
        "missing_imgt_ids": [i for i in batch.candidate_ids if i not in {r.external_id for r in imgt.records}],
        "evidence_ids": [e.external_id for e in evidence.entries] if evidence else [],
        "mapping": [asdict(c) for c in batch.candidates],
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
