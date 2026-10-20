from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtWidgets import QApplication, QComboBox, QDialog, QLabel, QLineEdit, QPushButton
from PyQt6.QtCore import QPoint, QRect, Qt
from PyQt6.QtTest import QTest

from igh_merge.gui import APP_ICON_PATH, MainWindow, PayloadDialog, application_icon
from igh_merge.service import MergeService

from conftest import write_summary


class _RunningThread:
    def isRunning(self):
        return True


def test_arrest_retry_sends_only_missing_and_merges_prior_results(run_factory, make_row, monkeypatch):
    from dataclasses import replace
    from igh_merge.external import ArrestBatchResult, parse_arrest_result
    from igh_merge.analysis_jobs import AnalysisJobResult
    from test_external import arrest_text
    app = QApplication.instance() or QApplication([])
    root, leader, fr1 = run_factory()
    sequence = 'ACGT' * 40
    write_summary(leader, 'SYN_LOCAL_ONLY', 1, [make_row(1, sequence)])
    write_summary(fr1, 'SYN_LOCAL_ONLY', 1, [make_row(1, sequence)])
    window = MainWindow()
    window.result = MergeService().process(root, expected_samples=1)
    window._populate_result()
    for i in range(window.candidate_table.rowCount()):
        window.candidate_table.item(i, 0).setCheckState(Qt.CheckState.Checked)
    batch = window._ensure_external_batch()
    first, second = [replace(batch, candidates=(c,)) for c in batch.candidates]
    record = parse_arrest_result(arrest_text().replace('SEQ-ABC123', first.candidate_ids[0]), first).records[0]
    window.arrest_result = ArrestBatchResult((record,), '', '')
    submitted = []
    monkeypatch.setattr('igh_merge.gui.PayloadDialog.exec', lambda self: QDialog.DialogCode.Accepted)
    monkeypatch.setattr(window, '_start_external', lambda service, part: submitted.append(part))
    window._confirm_and_start_external('ARResT', 'https://example.test')
    assert submitted[0].candidate_ids == second.candidate_ids
    failed = AnalysisJobResult((), {second.candidate_ids[0]: 'service unavailable'})
    assert not window._external_succeeded('ARResT', second, failed)
    assert window.arrest_result.records == (record,)
    second_record = replace(record, external_id=second.candidate_ids[0])
    job = AnalysisJobResult(((second, ArrestBatchResult((second_record,), '', '')),), {})
    assert window._external_succeeded('ARResT', second, job)
    assert {r.external_id for r in window.arrest_result.records} == set(batch.candidate_ids)
    messages = []
    monkeypatch.setattr('igh_merge.gui.QMessageBox.information', lambda *a: messages.append(a[-1]))
    window._confirm_and_start_external('ARResT', 'https://example.test')
    assert len(submitted) == 1 and messages
    window._external_progressed(1, 2)
    assert window.external_progress.maximum() == 2 and window.external_progress.value() == 1
    window.close()
    assert app is not None


def test_validation_does_not_replace_run_during_external_analysis(monkeypatch):
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window._external_thread = _RunningThread()
    monkeypatch.setattr(window.service, "process", lambda *_args: pytest.fail("run changed"))
    monkeypatch.setattr("igh_merge.gui.QMessageBox.information", lambda *_args: None)

    window._validate()

    assert window.result is None
    window._external_thread = None
    window.close()
    assert app is not None


def test_candidate_selection_does_not_replace_batch_during_external_analysis(
    run_factory, make_row
):
    app = QApplication.instance() or QApplication([])
    root, leader, fr1 = run_factory()
    write_summary(leader, "SYN_LOCAL_ONLY", 1, [make_row(1, "ACGT" * 40)])
    write_summary(fr1, "SYN_LOCAL_ONLY", 1, [make_row(1, "ACGT" * 30)])
    window = MainWindow()
    window.result = MergeService().process(root, expected_samples=1)
    window._populate_result()
    window.candidate_table.item(0, 0).setCheckState(Qt.CheckState.Checked)
    original_batch = window._ensure_external_batch()
    window._external_thread = _RunningThread()

    with pytest.raises(ValueError, match="in progress"):
        window._ensure_external_batch()

    assert window.external_batch is original_batch
    window._external_thread = None
    window.close()
    assert app is not None


def test_gui_has_required_tabs():
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    # Check nav buttons instead of tabs (new sidebar navigation)
    nav_labels = [btn.text() for btn in window.nav_buttons]
    assert nav_labels == [
        "Run",
        "Controls",
        "IMGT & ARResT",
        "Export",
        "Settings",
    ]
    assert window.export_button.isEnabled() is False
    assert window.send_imgt_button.isEnabled() is False
    assert window.send_arrest_button.isEnabled() is False
    assert window.highlight_excel_checkbox.text() == (
        "Highlight app's yellow candidate rows in Excel"
    )
    assert window.highlight_excel_checkbox.isChecked() is False
    export_intro = next(
        label for label in window.findChildren(QLabel) if "EXPORT" in label.text()
    )
    assert "24 columns" in export_intro.text()
    assert "24 columns" in window.highlight_excel_checkbox.toolTip()
    assert APP_ICON_PATH.is_file()
    assert application_icon().isNull() is False
    assert window.windowIcon().isNull() is False
    assert window.minimumWidth() == 1040
    assert window.status_badge.property("tone") == "neutral"
    assert window.status_badge.accessibleName() == "Application status"
    assert window.external_progress.isHidden() is True
    assert window.external_progress.accessibleName() == "External analysis in progress"
    window.close()
    assert app is not None


def test_payload_dialog_send_button_is_immediately_available():
    app = QApplication.instance() or QApplication([])
    dialog = PayloadDialog("IMGT", "https://example.test", ">SEQ-001\nACGT")

    assert dialog.send_button.isEnabled() is True
    dialog.send_button.click()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert app is not None


def test_navigation_updates_title_and_keeps_one_active_page():
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.show()
    app.processEvents()
    for index, button in enumerate(window.nav_buttons):
        button.setFocus()
        QTest.keyClick(button, Qt.Key.Key_Space)
        assert window.page_stack.currentIndex() == index
        assert window.page_title.text() == button.text()
        assert [item.isChecked() for item in window.nav_buttons] == [
            position == index for position in range(len(window.nav_buttons))
        ]
        # Reopening the active page must retain its selected navigation state.
        QTest.keyClick(button, Qt.Key.Key_Space)
        assert button.isChecked()
    window.close()


@pytest.mark.parametrize("size", [(1040, 720), (1380, 900)])
def test_all_page_actions_fit_supported_window_sizes(size):
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.resize(*size)
    window.show()
    app.processEvents()
    assert (window.width(), window.height()) == size
    for index in range(window.page_stack.count()):
        window._switch_page(index)
        app.processEvents()
        page = window.page_stack.currentWidget()
        for widget_type in (QPushButton, QLineEdit, QComboBox):
            for widget in page.findChildren(widget_type):
                if not widget.isVisible():
                    continue
                bounds = QRect(widget.mapTo(page, QPoint(0, 0)), widget.size())
                assert page.rect().contains(bounds), widget.accessibleName()
    window._switch_page(2)
    app.processEvents()
    assert window.candidate_section.stack.height() >= 140
    window.close()


def test_gui_creates_pseudonymous_external_payload(run_factory, make_row):
    app = QApplication.instance() or QApplication([])
    root, leader, fr1 = run_factory()
    write_summary(leader, "SYN_LOCAL_ONLY", 1, [make_row(1, "ACGT" * 40)])
    write_summary(fr1, "SYN_LOCAL_ONLY", 1, [make_row(1, "ACGT" * 30)])

    window = MainWindow()
    window.result = MergeService().process(root, expected_samples=1)
    window._populate_result()
    window.candidate_table.item(0, 0).setCheckState(Qt.CheckState.Checked)
    batch = window._ensure_external_batch()

    assert "SYN_LOCAL_ONLY" not in batch.fasta
    assert batch.fasta.startswith(">SEQ-")
    assert window.candidate_table.item(0, 1).text().startswith("SEQ-")
    assert (
        window.candidate_table.item(0, 0).background().color().name().upper()
        == "#FFFF00"
    )
    window.close()
    assert app is not None


def test_gui_analysis_includes_nonfunctional_high_read_row(
    run_factory, make_row
):
    app = QApplication.instance() or QApplication([])
    root, leader, fr1 = run_factory()
    write_summary(
        leader,
        "SYN_FUNCTION",
        1,
        [
            make_row(1, "ACGT" * 40, percent=4.0),
            make_row(
                2,
                "TGCA" * 40,
                percent=3.0,
                in_frame="N/A",
                no_stop="N",
            ),
        ],
    )
    write_summary(fr1, "SYN_FUNCTION", 1, [make_row(1, "ACGT" * 30)])

    window = MainWindow()
    window.result = MergeService().process(root, expected_samples=1)
    window._populate_result()

    assert window.candidate_table.item(0, 0).checkState() == Qt.CheckState.Checked
    assert window.candidate_table.item(1, 0).checkState() == Qt.CheckState.Checked
    assert window.candidate_table.rowCount() == 3
    assert window.candidate_table.item(2, 4).text() == "FR1"
    assert window.candidate_table.item(1, 6).font().bold()
    assert (
        window.candidate_table.item(0, 0).background().color().name().upper()
        == "#FFFF00"
    )
    assert (
        window.candidate_table.item(1, 0).background().color().name().upper()
        == "#D9D9D9"
    )
    window.close()
    assert app is not None


def test_gui_yellow_support_does_not_override_analysis_threshold(
    run_factory, make_row
):
    app = QApplication.instance() or QApplication([])
    root, leader, fr1 = run_factory()
    write_summary(
        leader,
        "SYN_SUPPORTED",
        1,
        [make_row(1, "ACGT" * 40, percent=1.7)],
    )
    write_summary(
        fr1,
        "SYN_SUPPORTED",
        1,
        [make_row(1, "ACGT" * 30, percent=4.0)],
    )

    window = MainWindow()
    window.result = MergeService().process(root, expected_samples=1)
    window._populate_result()

    assert window.result.rows[1].comment == "(Supports Leader-1)"
    assert window.candidate_table.item(0, 0).checkState() == Qt.CheckState.Unchecked
    assert window.candidate_table.item(1, 0).checkState() == Qt.CheckState.Checked
    assert (
        window.candidate_table.item(0, 0).background().color().name().upper()
        == "#FFFF00"
    )
    window.close()
    assert app is not None
