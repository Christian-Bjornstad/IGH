from dataclasses import replace
import json
import zipfile
import pytest
from openpyxl import load_workbook

from igh_merge.external import create_external_batch, ImgtBatchResult, parse_imgt_full_result
from igh_merge.reports import generate_clinical_report_package, _sample_report_records
from igh_merge.evidence import EvidenceManifest
from test_external import merged_row
from test_imgt_observations import full_files


def results(batch):
    records = []
    for c in batch.candidates:
        files = full_files()
        files['1_Summary.txt'] = files['1_Summary.txt'].replace('SEQ-ABC123', c.external_id)
        files['5_AA-sequences.txt'] = files['5_AA-sequences.txt'].replace('SEQ-ABC123', c.external_id)
        records.extend(parse_imgt_full_result(files, replace(batch, candidates=(c,))).records)
    return ImgtBatchResult({'IMGT/V-QUEST program version': '3.8.3'}, tuple(records), '', '')


def test_report_target_and_exact_support():
    rows = [merged_row(), merged_row(), merged_row()]
    rows[0].source = replace(rows[0].source, rank=1)
    rows[1].source = replace(rows[1].source, rank=10)
    rows[2].target = 'FR1'
    rows[2].comment = '(Supports Leader-10)'
    batch = create_external_batch('2099_01_02', list(enumerate(rows)))
    data = _sample_report_records(rows, batch, results(batch), None)['SYN_LOCAL_ONLY']
    assert data[0]['fr1_support'] == 'Not detected'
    assert data[2]['rank_label'] == 'FR1-1'
    assert '99.2' in data[0]['identity']


def test_package_excel_and_unique_sample_names(tmp_path):
    rows = [merged_row(), merged_row()]
    rows[0].sample, rows[1].sample = 'SYN/A', 'SYN?A'
    batch = create_external_batch('2099_01_02', list(enumerate(rows)))
    directory = generate_clinical_report_package(tmp_path, rows, batch, results(batch), evidence=EvidenceManifest(()))
    assert len(list(directory.glob('*.docx'))) == 2
    assert len(list(directory.glob('*.pdf'))) == 2
    workbook = load_workbook(directory / 'analysis.xlsx')
    assert workbook.active.max_column == 24
    assert {workbook.active.cell(i, 1).value for i in (2, 3)} == set(batch.candidate_ids)
    with zipfile.ZipFile(next(directory.glob('*.docx'))) as z:
        text = z.read('word/document.xml').decode()
        assert 'manual assessment' in text
        assert 'IMGT evidence missing' in text
    again = generate_clinical_report_package(tmp_path, rows, batch, results(batch))
    assert again != directory


def test_report_partial_results_mark_missing(tmp_path):
    rows = [merged_row(), merged_row()]
    batch = create_external_batch('2099_01_02', list(enumerate(rows)))
    imgt = replace(results(batch), records=results(batch).records[:1])
    directory = generate_clinical_report_package(tmp_path, rows, batch, imgt)
    audit = json.loads((directory / 'report_data.audit.json').read_text())
    assert audit['complete'] is False
    assert audit['missing_imgt_ids'] == [batch.candidate_ids[1]]
