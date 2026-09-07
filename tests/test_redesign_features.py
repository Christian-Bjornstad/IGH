"""Unit tests for the IGHV redesign: cDNA detection, external_id wiring,
Edge/CDP helpers, and the new Word report."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from igh_merge.edge_cdp import (
    IMGT_SCREENSHOT_SECTIONS,
    edge_cdp_available,
    imgt_search_url,
)
from igh_merge.io import SummaryReader, detect_molecule_type
from igh_merge.models import MergedRow, SourceRow


# ---------------------------------------------------------------------------
# cDNA detection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "sample,expected",
    [
        ("SYN_PATIENT_A", "gDNA"),
        ("SYN_PATIENT_A_cdna", "cDNA"),
        ("SYN_PATIENT_A_cDNA", "cDNA"),
        ("SYN_PATIENT_A_cdna_S2", "cDNA"),
        ("SYN_PATIENT_A_CDNA_2", "cDNA"),
        ("SYNTH_cdna_only", "cDNA"),
        ("SYNTH_cd", "gDNA"),  # short token must not match
        ("SYNTH_acdnab", "gDNA"),  # embedded substring must not match
        ("", "gDNA"),
    ],
)
def test_detect_molecule_type(sample: str, expected: str) -> None:
    assert detect_molecule_type(sample) == expected


def test_summary_reader_propagates_molecule_type(tmp_path: Path) -> None:
    """When a sample name ends in _cdna, the SampleFile reports cDNA."""
    from tests.conftest import _row, write_summary

    target = tmp_path / "leader"
    write_summary(
        target,
        "SYN_PATIENT_A_cdna",
        1,
        [_row(1, "A" * 100)],
    )
    file = next(target.glob("*.tsv"))
    sample_file = SummaryReader().read(file, "Leader")
    assert sample_file.molecule_type == "cDNA"
    assert sample_file.sample == "SYN_PATIENT_A_cdna"


# ---------------------------------------------------------------------------
# Excel layout includes External ID + Molecule columns
# ---------------------------------------------------------------------------


def test_excel_layout_includes_external_id_and_molecule(tmp_path: Path) -> None:
    from openpyxl import load_workbook

    from igh_merge.excel import HEADERS, ExcelReportWriter
    from igh_merge.models import MergedRow, SourceRow

    source = SourceRow(
        1, "ACGT" * 35, 140, 1000, "IGHV1-2_01", "IGHJ4_02",
        3.0, 3.0, 2.0, "Y", "Y", 100.0, "CARDR",
    )
    row = MergedRow(
        source, "SYN_PATIENT_A_cdna", 1, 123_456, "Leader", "cDNA", "2026_09_07",
        external_id="SEQ-ABC123",
    )
    out = tmp_path / "merged.xlsx"
    ExcelReportWriter().write([row], out)
    workbook = load_workbook(out, data_only=False)
    sheet = workbook["Sheet1"]
    assert HEADERS[0] == "External ID"
    assert "Molecule" in HEADERS
    # External ID is column A (1), Molecule is column S (19)
    assert sheet["A2"].value == "SEQ-ABC123"
    assert sheet["S2"].value == "cDNA"
    workbook.close()


# ---------------------------------------------------------------------------
# Word report is generated alongside the PDF
# ---------------------------------------------------------------------------


def test_report_package_writes_word_and_pdf(tmp_path: Path) -> None:
    from igh_merge.external import parse_imgt_full_result

    sys_path = Path(__file__).parents[1] / "src"
    import sys
    if str(sys_path) not in sys.path:
        sys.path.insert(0, str(sys_path))
    from tests.test_external import candidate_batch, merged_row
    from igh_merge.reports import generate_clinical_report_package

    batch = candidate_batch()
    summary = (
        "Sequence ID\tV-DOMAIN Functionality\tV-GENE and allele\t"
        "V-REGION identity %\tV-REGION identity nt\tJ-GENE and allele\t"
        "D-GENE and allele\tCDR3-IMGT length\tAA JUNCTION\tJUNCTION frame\t"
        "Sequence\tCLL subset\n"
        "SEQ-ABC123\tproductive\tHomsap IGHV3-21*01 F\t98.25\t"
        "283/288 nt\tHomsap IGHJ6*02 F\tHomsap IGHD3-10*03 F\t9\t"
        "CARDR\tin-frame\t" + "ACGT" * 40 + "\tCLL subset #2\n"
    )
    imgt = parse_imgt_full_result(
        {
            "1_Summary.txt": summary,
            "5_AA-sequences.txt": "Sequence ID\tCDR3-IMGT\nSEQ-ABC123\tARD\n",
            "11_Parameters.txt": (
                "IMGT/V-QUEST program version\t3.8.2\n"
                "IMGT/V-QUEST reference directory release\t209901-1\n"
            ),
        },
        batch,
    )
    directory = generate_clinical_report_package(
        tmp_path, [merged_row()], batch, imgt,
    )
    pdf = directory / "SYN_LOCAL_ONLY_IGHV_report_draft.pdf"
    docx = directory / "SYN_LOCAL_ONLY_IGHV_report_draft.docx"
    assert pdf.exists() and pdf.stat().st_size > 1_000
    assert docx.exists() and docx.stat().st_size > 5_000
    # Word file is a valid zip (docx) and contains the External ID we used.
    import zipfile
    with zipfile.ZipFile(docx) as archive:
        document_xml = archive.read("word/document.xml").decode("utf-8")
    assert "SEQ-ABC123" in document_xml
    # The audit file is still written for traceability.
    assert (directory / "report_data.audit.json").exists()


# ---------------------------------------------------------------------------
# Edge/CDP helpers
# ---------------------------------------------------------------------------


def test_imgt_search_url_uses_correct_molecule_type() -> None:
    g = imgt_search_url("ACGT", molecule_type="gDNA")
    c = imgt_search_url("ACGT", molecule_type="cDNA")
    assert "receptorOrLocusType=IGH" in g
    assert "moleculeType=gDNA" in g
    assert "moleculeType=cDNA" in c
    assert "species=human" in c


def test_imgt_screenshot_sections_are_1_to_6_and_9() -> None:
    assert IMGT_SCREENSHOT_SECTIONS == (1, 2, 3, 4, 5, 6, 9)


def test_edge_cdp_available_returns_bool() -> None:
    result = edge_cdp_available()
    assert isinstance(result, bool)
