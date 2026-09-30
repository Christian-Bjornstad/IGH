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
