from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtWidgets import QApplication, QDialog, QLabel
from PyQt6.QtCore import Qt

from igh_merge.gui import APP_ICON_PATH, MainWindow, PayloadDialog, application_icon
from igh_merge.service import MergeService

from conftest import write_summary


class _RunningThread:
    def isRunning(self):
        return True


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
