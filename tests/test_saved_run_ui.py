import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import json
from dataclasses import replace

from PyQt6.QtWidgets import QApplication

from conftest import write_summary
from igh_merge.gui import MainWindow
from igh_merge.saved_runs import RunSession, save_session
from igh_merge.qc import ControlLimits
from igh_merge.service import MergeService
from igh_merge.external import create_external_batch
from test_report_package import results


def test_open_restores_selection_results_and_exports_excel_without_network(run_factory, make_row, tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    root, leader, fr1 = run_factory()
    write_summary(leader, 'SYN', 1, [make_row(1, 'ACGT'*40)])
    write_summary(fr1, 'SYN', 1, [make_row(1, 'ACGT'*30)])
    result = MergeService().process(root, None)
    batch = create_external_batch(result.manifest.run_date, [(0, result.rows[0])])
    state = RunSession(result, batch, results(batch), selected=(0,), lymphotrack_version='old-version', limits=ControlLimits(positive_min=3.5))
    path = save_session(tmp_path/'saved.ighv', state)
    monkeypatch.setattr('igh_merge.gui.QFileDialog.getOpenFileName', lambda *a: (str(path), ''))
    monkeypatch.setattr('igh_merge.gui.QMessageBox.information', lambda *a: None)
    window = MainWindow()
    monkeypatch.setattr(window, '_start_external', lambda *a: __import__('pytest').fail('network request on reopen'))
    window._open_run()
    assert window.external_batch.candidate_ids == batch.candidate_ids
    assert window._selected_result_indices() == (0,)
    assert window.report_button.isEnabled()
    assert window.limit_inputs['positive_min'].value() == 3.5
    assert window.lymphotrack_version_edit.text() == 'old-version'
    assert window._ensure_external_batch() is window.external_batch
    window._generate_reports()
    assert list(tmp_path.glob('*_reports/**/*_IGHV_analysis.xlsx'))
    assert not list(tmp_path.glob('*_reports/**/*.docx'))
    window.close()


def test_settings_only_version_and_editable_limits_recompute_loaded_controls(run_factory, make_row, monkeypatch):
    app = QApplication.instance() or QApplication([])
    values = {}
    class Settings:
        def value(self, key, default=None): return values.get(key, default)
        def setValue(self, key, value): values[key] = value
    monkeypatch.setattr('igh_merge.gui.QSettings', lambda *a: Settings())
    monkeypatch.setattr('igh_merge.gui.QMessageBox.information', lambda *a: None)
    root, leader, fr1 = run_factory()
    for target in (leader, fr1):
        write_summary(target, 'IGH_POS', 1, [make_row(1, 'ACGT'*40, percent=3)])
    window = MainWindow()
    window.result = MergeService().process(root, None)
    window._populate_result()
    assert not hasattr(window, 'default_data_edit')
    assert not hasattr(window, 'expected_spin')
    assert not hasattr(window, 'view_evidence_button')
    window.limit_inputs['positive_min'].setValue(4)
    window._save_settings()
    assert window.result.qc.controls[2].status == 'FEIL'
    assert json.loads(values['controlLimits'])['positive_min'] == 4
    window.close()
    reopened = MainWindow()
    assert reopened.limit_inputs['positive_min'].value() == 4
    reopened.close()


def test_failed_open_keeps_existing_run(run_factory, make_row, tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    root, leader, fr1 = run_factory()
    for target in (leader, fr1):
        write_summary(target, 'SYN', 1, [make_row(1, 'ACGT'*40)])
    path = tmp_path/'broken.ighv'
    path.write_text('broken')
    monkeypatch.setattr('igh_merge.gui.QFileDialog.getOpenFileName', lambda *a: (str(path), ''))
    errors = []
    monkeypatch.setattr('igh_merge.gui.QMessageBox.critical', lambda *a: errors.append(a[-1]))
    window = MainWindow()
    window.result = MergeService().process(root, None)
    original = window.result
    window._populate_result()
    window._open_run()
    assert window.result is original and errors
    window.close()


def test_imgt_retry_only_sends_missing_and_keeps_previous_records(run_factory, make_row, monkeypatch):
    from igh_merge.analysis_jobs import AnalysisJobResult
    from PyQt6.QtWidgets import QDialog
    app = QApplication.instance() or QApplication([])
    root, leader, fr1 = run_factory()
    for target in (leader, fr1):
        write_summary(target, 'SYN', 1, [make_row(1, 'ACGT'*40)])
    window = MainWindow()
    window.result = MergeService().process(root, None)
    window._populate_result()
    batch = window._ensure_external_batch()
    full = results(batch)
    window.imgt_result = replace(full, records=full.records[:1])
    sent = []
    monkeypatch.setattr('igh_merge.gui.PayloadDialog.exec', lambda self: QDialog.DialogCode.Accepted)
    monkeypatch.setattr(window, '_start_external', lambda service, part: sent.append(part))
    window._confirm_and_start_external('IMGT', 'https://example.test')
    assert sent[0].candidate_ids == batch.candidate_ids[1:]
    response = replace(full, records=full.records[1:])
    job = AnalysisJobResult(((sent[0], response),), {})
    assert window._external_succeeded('IMGT', sent[0], job)
    assert set(r.external_id for r in window.imgt_result.records) == set(batch.candidate_ids)
    assert window._has_complete_imgt()
    window.close()
