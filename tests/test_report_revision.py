from dataclasses import replace

from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QApplication

from igh_merge.external import create_external_batch, parse_arrest_result
from igh_merge.gui import MainWindow
from igh_merge.reports import _sample_report_records, _result_fields
from test_external import merged_row
from test_external import arrest_text, candidate_batch
from test_report_package import results


def test_unproductive_and_independent_fr1_get_their_own_named_results():
    leader = merged_row('ACGT' * 40)
    leader.source = replace(leader.source, rank=3)
    orphan = merged_row('TGCA' * 30)
    orphan.target = 'FR1'
    orphan.source = replace(orphan.source, rank=3)
    rows = [leader, orphan]
    batch = create_external_batch('2099_01_02', list(enumerate(rows)))
    imgt = results(batch)
    imgt = replace(imgt, records=(replace(imgt.records[0], productive=False), imgt.records[1]))
    data = _sample_report_records(rows, batch, imgt, None)['SYN_LOCAL_ONLY']
    assert [r['rank_label'] for r in data] == ['Leader-3 (Ufunksjonell)', 'FR1-3']
    assert data[0]['fasta'].startswith('>SYN_LOCAL_ONLY-Leader-3\n')
    assert {r['external_id'] for r in data} == set(batch.candidate_ids)


def test_report_percent_fields_include_low_exact_fr1_support_without_analyzing_it():
    leader = merged_row('ACGT' * 40)
    leader.source = replace(leader.source, percent_total_reads=18.75)
    low_support = merged_row('ACGT' * 20)
    low_support.target = 'FR1'
    low_support.source = replace(low_support.source, percent_total_reads=0.75)
    other_sample = merged_row('ACGT' * 20)
    other_sample.target = 'FR1'
    other_sample.sample = 'SYN_OTHER'
    batch = create_external_batch('2099_01_02', [(0, leader)])
    rec = _sample_report_records([leader, low_support, other_sample], batch, results(batch), None)['SYN_LOCAL_ONLY'][0]
    assert rec['leader_fraction'] == '18.75 %'
    assert rec['fr1_support'] == '0.75 %'
    assert rec['supporting_external_ids'] == []
    fields = dict(_result_fields(rec))
    assert fields['Target fraction'] == '18.75 %'
    assert fields['FR1 support'] == '0.75 %'


def test_report_observations_keep_coordinates_without_repeated_manual_provenance():
    row = merged_row()
    batch = create_external_batch('2099_01_02', [(0, row)])
    rec = _sample_report_records([row], batch, results(batch), None)['SYN_LOCAL_ONLY'][0]
    assert 'manual assessment' not in rec['observations']
    assert '4_IMGT-gapped-AA-sequences.txt' not in rec['observations']
    assert 'AA position 118' in rec['observations']
    assert '\n' in rec['observations']


def test_seqcure_messages_and_advice_are_presented_separately():
    batch = candidate_batch()
    arrest = parse_arrest_result(arrest_text(), batch)
    record = arrest.records[0]
    object.__setattr__(record, 'seqcure_messages', ('FR3-IMGT shows mutational load imbalance (60.00% ratio)',))
    object.__setattr__(record, 'seqcure_advice', ('Analyze this rearrangement separately with IMGT insertion/deletion search.',))
    object.__setattr__(record, 'seqcure_details_status', 'available')
    rec = _sample_report_records([merged_row()], batch, results(batch), arrest)['SYN_LOCAL_ONLY'][0]
    assert '60.00%' in rec['arrest_seqcure_details']
    assert 'insertion/deletion' in rec['arrest_seqcure_advice']
    assert rec['arrest_seqcure_status'] == 'available'
    assert 'ARResT SeqCure details' in dict(_result_fields(rec))


def test_settings_start_with_current_lymphotrack_version_and_preserve_override(tmp_path, monkeypatch):
    settings = QSettings(str(tmp_path / 'settings.ini'), QSettings.Format.IniFormat)
    monkeypatch.setattr('igh_merge.gui.QSettings', lambda *args: settings)
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    assert window.lymphotrack_version_edit.text() == '2.4.6'
    window.close()
    settings.setValue('lymphotrackVersion', '2.5.0')
    next_window = MainWindow()
    assert next_window.lymphotrack_version_edit.text() == '2.5.0'
    next_window.close()
    assert app is not None
