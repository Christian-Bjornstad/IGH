"""Unit tests for the IGHV redesign: cDNA detection, external_id wiring,
Edge/CDP helpers, and the new Word report."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from igh_merge.edge_cdp import (
    IMGT_SCREENSHOT_SECTIONS,
    IMGT_SCREENSHOT_SPECS,
    EdgeCdpError,
    capture_imgt_evidence,
    edge_cdp_available,
    imgt_screenshot_specs,
    imgt_search_url,
    submit_imgt_detailed,
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


def test_imgt_screenshot_specs_match_requested_summary_1_to_6_and_9() -> None:
    by_key = {spec.key: spec for spec in IMGT_SCREENSHOT_SPECS}
    assert tuple(by_key) == (
        "00_summary",
        "01_v_gene",
        "02_d_gene",
        "03_j_gene",
        "04_leader",
        "05_constant",
        "06_junction",
        "09_v_region_translation",
    )
    # The summary crop starts at the yellow Result summary table and includes
    # the following warning list (including an IMGT '(a)' ambiguity warning).
    assert by_key["00_summary"].start_selector == "table.result_summary"
    assert by_key["00_summary"].end_selector == "h4#sequence1_alv"
    assert by_key["01_v_gene"].start_selector == "h4#sequence1_alv"
    assert by_key["03_j_gene"].start_selector == "h4#sequence1_alj"
    assert by_key["04_leader"].optional is True
    assert by_key["05_constant"].start_selector == "h4#sequence1_alC"
    assert by_key["06_junction"].start_selector == "h4#sequence1_junction"
    assert by_key["09_v_region_translation"].start_selector == "h4#sequence1_section7"


class _FakeImgtPage:
    def __init__(self, selectors: set[str], *, sequence_count: int = 1) -> None:
        self.selectors = selectors
        self.sequence_count = sequence_count
        self.captured: list[tuple[str, str | None, str]] = []
        self.navigated: list[str] = []
        self.evaluated: list[str] = []
        self.evaluate_args: list[object] = []

    def navigate(self, url: str, *, timeout_s: float = 60.0) -> None:
        self.navigated.append(url)

    def _wait_for_load(self, *, timeout_s: float) -> None:
        pass

    def evaluate(self, expression: str, *, args=None):
        self.evaluated.append(expression)
        self.evaluate_args.append(args)
        if "querySelectorAll('h3.sequence_title').length" in expression:
            return self.sequence_count
        if "h3.sequence_title" in expression and "innerText" in expression:
            return "Sequence : 1 SEQ-TEST-001"
        if "Boolean(document.querySelector(sel))" in expression:
            return args[0] in self.selectors
        if "form.submit()" in expression:
            return True
        return ""

    def capture_region(
        self,
        start_selector: str,
        path: Path,
        *,
        end_selector: str | None = None,
        padding: float = 12.0,
        max_height: float = 6_000.0,
    ) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"png")
        self.captured.append((start_selector, end_selector, path.name))
        return path

    def capture_full_page(self, path: Path) -> Path:
        path.write_bytes(b"png")
        return path


def _required_imgt_selectors() -> set[str]:
    return {
        spec.start_selector
        for spec in IMGT_SCREENSHOT_SPECS
        if not spec.optional
    }


def test_imgt_screenshot_specs_skip_optional_cdna_sections() -> None:
    page = _FakeImgtPage(_required_imgt_selectors())
    specs = imgt_screenshot_specs(page)  # type: ignore[arg-type]
    assert all(spec.key not in {"04_leader", "05_constant"} for spec in specs)


def test_capture_imgt_evidence_writes_named_crops(tmp_path: Path) -> None:
    page = _FakeImgtPage(_required_imgt_selectors())
    paths = capture_imgt_evidence(page, tmp_path)  # type: ignore[arg-type]
    names = {path.name for path in paths}
    assert "00_summary.png" in names
    assert "01_v_gene.png" in names
    assert "06_junction.png" in names
    assert "09_v_region_translation.png" in names
    assert "08_v_region_alignment.png" not in names
    assert "11_mutation_table.png" not in names
    assert "12_mutation_statistics.png" not in names
    assert "99_full_page.png" not in names


def test_capture_imgt_evidence_rejects_multi_sequence_page(tmp_path: Path) -> None:
    page = _FakeImgtPage(_required_imgt_selectors(), sequence_count=2)
    with pytest.raises(EdgeCdpError, match="exactly one"):
        capture_imgt_evidence(page, tmp_path)  # type: ignore[arg-type]


def test_submit_imgt_detailed_builds_single_sequence_form() -> None:
    page = _FakeImgtPage(_required_imgt_selectors())
    submit_imgt_detailed(  # type: ignore[arg-type]
        page,
        external_id="SEQ-TEST-001",
        sequence="ACGT" * 30,
        molecule_type="cDNA",
    )
    assert page.navigated == ["https://www.imgt.org/IMGT_vquest/analysis"]
    submit_index = next(
        index
        for index, expression in enumerate(page.evaluated)
        if "form.submit()" in expression
    )
    fields = page.evaluate_args[submit_index][0]
    assert fields["moleculeType"] == "cDNA"
    assert fields["resultType"] == "detailed"
    assert fields["sequences"].startswith(">SEQ-TEST-001\n")


def test_submit_imgt_detailed_rejects_invalid_sequence() -> None:
    page = _FakeImgtPage(_required_imgt_selectors())
    with pytest.raises(EdgeCdpError, match="invalid characters"):
        submit_imgt_detailed(  # type: ignore[arg-type]
            page,
            external_id="SEQ-TEST-001",
            sequence="ACGT-X",
            molecule_type="gDNA",
        )
