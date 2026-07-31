from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QDialog
from PyQt6.QtCore import Qt

from igh_merge.gui import MainWindow, PayloadDialog
from igh_merge.service import MergeService

from conftest import write_summary


def test_gui_has_required_norwegian_tabs():
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    labels = [window.tabs.tabText(index) for index in range(window.tabs.count())]
    assert labels == [
        "Kjøring",
        "Kontroller",
        "IMGT og ARResT",
        "Eksport",
        "Innstillinger",
    ]
    assert window.export_button.isEnabled() is False
    assert window.send_imgt_button.isEnabled() is False
    assert window.send_arrest_button.isEnabled() is False
    assert window.highlight_excel_checkbox.text() == (
        "Marker appens gule kandidatrader i Excel"
    )
    assert window.highlight_excel_checkbox.isChecked() is False
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


def test_gui_yellow_selection_excludes_nonfunctional_high_read_row(
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
    assert window.candidate_table.item(1, 0).checkState() == Qt.CheckState.Unchecked
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


def test_gui_yellow_selection_includes_low_leader_with_exact_fr1_support(
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

    assert window.result.rows[1].comment == "(Støtter Leader-1)"
    assert window.candidate_table.item(0, 0).checkState() == Qt.CheckState.Checked
    assert (
        window.candidate_table.item(0, 0).background().color().name().upper()
        == "#FFFF00"
    )
    window.close()
    assert app is not None
