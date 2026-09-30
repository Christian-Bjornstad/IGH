import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

from igh_merge.gui import MainWindow
from igh_merge.service import MergeService
from conftest import write_summary


def test_filter_and_counter_preserve_selection(run_factory, make_row):
    app = QApplication.instance() or QApplication([])
    root, leader, fr1 = run_factory()
    write_summary(leader, 'SYN_LONG_NAME', 1, [make_row(1, 'ACGT' * 40, percent=2.5)])
    write_summary(fr1, 'SYN_LONG_NAME', 1, [make_row(1, 'ACGT' * 30, percent=2.499)])
    window = MainWindow()
    window.result = MergeService().process(root, 1)
    window._populate_result()
    window.candidate_search.setText('FR1')
    assert window.candidate_table.isRowHidden(0)
    assert not window.candidate_table.isRowHidden(1)
    assert window._selected_result_indices() == (0,)
    assert '1 selected' in window.selection_count.text()
    window.candidate_search.setText('NO_MATCH')
    assert all(window.candidate_table.isRowHidden(i) for i in range(2))
    window.close()


def test_validated_run_offers_edge_without_http(run_factory, make_row):
    app = QApplication.instance() or QApplication([])
    root, leader, fr1 = run_factory()
    write_summary(leader, 'SYN', 1, [make_row(1, 'ACGT' * 40, percent=3)])
    write_summary(fr1, 'SYN', 1, [make_row(1, 'ACGT' * 40)])
    window = MainWindow()
    window.result = MergeService().process(root, 1)
    window._populate_result()
    assert window.imgt_result is None
    assert window.capture_button.isEnabled()
    window.close()


def test_disk_failure_is_not_reported_as_completed(run_factory, make_row, monkeypatch):
    from igh_merge.analysis_jobs import AnalysisJobResult
    from test_report_package import results
    app = QApplication.instance() or QApplication([])
    root, leader, fr1 = run_factory()
    write_summary(leader, 'SYN', 1, [make_row(1, 'ACGT' * 40, percent=3)])
    write_summary(fr1, 'SYN', 1, [make_row(1, 'ACGT' * 40)])
    window = MainWindow()
    window.result = MergeService().process(root, 1)
    window._populate_result()
    batch = window._ensure_external_batch()
    def fail(*args):
        raise OSError('disk full')
    monkeypatch.setattr('igh_merge.gui.save_imgt_result', fail)
    monkeypatch.setattr('igh_merge.gui.QMessageBox.critical', lambda *args: None)
    window._external_succeeded('IMGT', batch, AnalysisJobResult(((batch, results(batch)),), {}))
    assert not window.report_button.isEnabled()
    assert window.imgt_result is None
    assert '0 completed' in window.external_status.text()
    assert 'failed' in window.external_status.text()
    window.close()


def test_cached_batch_rechecks_sequence_hash(run_factory, make_row):
    from dataclasses import replace
    app = QApplication.instance() or QApplication([])
    root, leader, fr1 = run_factory()
    write_summary(leader, 'SYN', 1, [make_row(1, 'ACGT' * 40, percent=3)])
    write_summary(fr1, 'SYN', 1, [make_row(1, 'ACGT' * 40)])
    window = MainWindow()
    window.result = MergeService().process(root, 1)
    window._populate_result()
    first = window._ensure_external_batch()
    row = window.result.rows[0]
    row.source = replace(row.source, sequence='TGCA' * 40)
    second = window._ensure_external_batch()
    assert second.candidate_ids[0] != first.candidate_ids[0]
    window.close()


def test_refresh_keeps_reads_and_status_columns(run_factory, make_row):
    app = QApplication.instance() or QApplication([])
    root, leader, fr1 = run_factory()
    write_summary(leader, 'SYN', 1, [make_row(1, 'ACGT' * 40, percent=3)])
    write_summary(fr1, 'SYN', 1, [make_row(1, 'ACGT' * 30)])
    window = MainWindow()
    window.result = MergeService().process(root, 1)
    window._populate_result()
    reads = window.candidate_table.item(0, 6).text()
    window._imgt_status_by_row[0] = 'productive'
    window._arrest_status_by_row[0] = 'unassigned'
    window.result.rows[0].subset = '2'
    window._refresh_external_table()
    assert window.candidate_table.item(0, 6).text() == reads
    assert window.candidate_table.item(0, 7).text() == 'productive'
    assert window.candidate_table.item(0, 8).text() == 'unassigned'
    assert window.candidate_table.item(0, 9).text() == '2'
    window.close()


def test_arrest_cleanup_restores_report_button(run_factory, make_row):
    from test_report_package import results
    app = QApplication.instance() or QApplication([])
    root, leader, fr1 = run_factory()
    write_summary(leader, 'SYN', 1, [make_row(1, 'ACGT' * 40, percent=3)])
    write_summary(fr1, 'SYN', 1, [make_row(1, 'ACGT' * 40)])
    window = MainWindow()
    window.result = MergeService().process(root, 1)
    window._populate_result()
    batch = window._ensure_external_batch()
    window.imgt_result = results(batch)
    window.report_button.setEnabled(False)
    window._external_finished()
    assert window.report_button.isEnabled()
    window.close()
