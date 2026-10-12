from __future__ import annotations

from igh_merge.external import parse_imgt_full_result
from igh_merge.reports import generate_clinical_report_package
import pytest

from test_external import SEQUENCE, candidate_batch, merged_row


def test_generates_local_word_excel_report_package(tmp_path):
    batch = candidate_batch()
    summary = (
        "Sequence ID\tV-DOMAIN Functionality\tV-GENE and allele\t"
        "V-REGION identity %\tV-REGION identity nt\tJ-GENE and allele\t"
        "D-GENE and allele\tCDR3-IMGT length\tAA JUNCTION\tJUNCTION frame\t"
        "Sequence\tCLL subset\n"
        f"SEQ-ABC123\tproductive\tHomsap IGHV3-21*01 F\t98.25\t"
        f"283/288 nt\tHomsap IGHJ6*02 F\tHomsap IGHD3-10*03 F\t9\t"
        f"CARDR\tin-frame\t{SEQUENCE}\tCLL subset #2\n"
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
        tmp_path, [merged_row()], batch, imgt
    )
    pdf = directory / "SYN_LOCAL_ONLY_IGHV_report_draft.pdf"
    assert not pdf.exists()
    assert (directory / 'SYN_LOCAL_ONLY_IGHV_report_draft.docx').is_file()
    assert (directory / 'SYN_LOCAL_ONLY_IGHV_analysis.xlsx').is_file()
    assert (directory / "report_data.audit.json").exists()


def test_report_presentation_uses_sequence_and_declared_versions(tmp_path):
    from docx import Document
    from test_report_package import results

    batch = candidate_batch()
    directory = generate_clinical_report_package(
        tmp_path, [merged_row()], batch, results(batch), lymphotrack_version='3.0.1',
    )
    document = Document(directory / 'SYN_LOCAL_ONLY_IGHV_report_draft.docx')
    text = '\n'.join(p.text for p in document.paragraphs)
    labels = [row.cells[0].text for table in document.tables for row in table.rows]
    assert 'LymphoTrack version: 3.0.1' in text
    assert '>SYN_LOCAL_ONLY-Leader-1' in text
    assert SEQUENCE in text.replace('\n', '')
    assert {'Target fraction', 'FR1 support'} <= set(labels)
    assert 'Identity source' not in labels
    assert 'Specialist assessment:' in text
    assert document.sections[0].page_width.mm == pytest.approx(210, abs=.02)
    assert document.sections[0].page_height.mm == pytest.approx(297, abs=.02)


def test_unknown_lymphotrack_version_is_explicit(tmp_path):
    from docx import Document
    from test_report_package import results

    batch = candidate_batch()
    directory = generate_clinical_report_package(tmp_path, [merged_row()], batch, results(batch))
    document = Document(directory / 'SYN_LOCAL_ONLY_IGHV_report_draft.docx')
    assert 'LymphoTrack version: not provided' in '\n'.join(p.text for p in document.paragraphs)


def test_reports_keep_five_imgt_crops_and_copyable_summary(tmp_path):
    import base64
    from docx import Document
    from igh_merge.evidence import save_evidence_manifest
    from test_report_package import results

    batch = candidate_batch()
    sections = ('00_summary', '01_v_gene', '02_d_gene', '03_j_gene', '06_junction', '09_v_region_translation')
    source = tmp_path / 'source'
    source.mkdir()
    paths = []
    for section in sections:
        image = source / (section + '.png')
        image.write_bytes(base64.b64decode(
            'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jXioAAAAASUVORK5CYII='
        ))
        paths.append(image)
    evidence = save_evidence_manifest(source, batch, batch.candidates[0],
                                      dict.fromkeys(sections, 'copyable source text'), paths, parameters={})
    directory = generate_clinical_report_package(tmp_path, [merged_row()], batch, results(batch), evidence=evidence)
    document = Document(directory / 'SYN_LOCAL_ONLY_IGHV_report_draft.docx')
    assert len(document.inline_shapes) == 5
    assert 'copyable source text' in '\n'.join(p.text for p in document.paragraphs)
    assert not document._element.xpath('.//w:br[@w:type="page"]')
    import json
    audit = json.loads((directory / 'report_data.audit.json').read_text(encoding='utf-8'))
    assert audit['evidence_coverage_complete'] is True
    assert audit['evidence_complete'] is True
    assert audit['missing_evidence_sections_by_id'] == {}


def test_reports_allow_long_source_comments_to_span_pages(tmp_path):
    from docx import Document
    from test_report_package import results

    row = merged_row()
    row.comment = 'Long factual source comment. ' * 500
    batch = candidate_batch()
    directory = generate_clinical_report_package(tmp_path, [row], batch, results(batch))
    document = Document(directory / 'SYN_LOCAL_ONLY_IGHV_report_draft.docx')
    assert any(row.comment == cells.cells[1].text for table in document.tables for cells in table.rows)
    assert not document._element.xpath('.//w:trHeight[@w:hRule="exact"]')
