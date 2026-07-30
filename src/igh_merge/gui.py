from __future__ import annotations

from functools import partial
from pathlib import Path

from PyQt6.QtCore import QObject, QSettings, QThread, Qt, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .external import (
    ARREST_URL,
    IMGT_URL,
    ArrestBatchResult,
    ArrestClient,
    ExternalAnalysisError,
    ExternalBatch,
    ImgtBatchResult,
    ImgtClient,
    apply_arrest_result,
    apply_imgt_result,
    create_external_batch,
    save_arrest_result,
    save_batch_mapping,
    save_imgt_result,
)
from .io import ValidationError
from .models import MergeResult, QcItem
from .privacy import PrivacyError, ensure_outside_git
from .reports import generate_clinical_report_package
from .service import MergeService


class Palette:
    ink = "#17212B"
    muted = "#5E6A73"
    panel = "#FFFFFF"
    app_bg = "#F4F7F9"
    border = "#CBD7E1"
    navy = "#163B5C"
    blue = "#2F75B5"
    green = "#3E7D4A"
    red = "#A92525"
    pale_green = "#EAF5ED"
    pale_red = "#F8E8E8"
    functional_yellow = "#FFFF00"
    excluded_gray = "#D9D9D9"


class MetricCard(QFrame):
    def __init__(self, label: str, color: str):
        super().__init__()
        self.setObjectName("MetricCard")
        layout = QVBoxLayout(self)
        self.value = QLabel("0")
        self.value.setFont(QFont("Segoe UI", 22, QFont.Weight.Bold))
        self.value.setStyleSheet(f"color: {color}")
        caption = QLabel(label)
        caption.setStyleSheet(f"color: {Palette.muted}")
        layout.addWidget(self.value)
        layout.addWidget(caption)


class PayloadDialog(QDialog):
    def __init__(self, service: str, endpoint: str, payload: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Bekreft sending til {service}")
        self.resize(760, 620)
        layout = QVBoxLayout(self)
        description = QLabel(
            f"Mottaker: {endpoint}\n"
            "Dette er nøyaktig innholdet som sendes. Prøvenummer og filnavn er ikke med."
        )
        description.setWordWrap(True)
        layout.addWidget(description)
        preview = QPlainTextEdit()
        preview.setReadOnly(True)
        preview.setPlainText(payload)
        preview.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        layout.addWidget(preview, 1)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok
        )
        self.send_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.send_button.setText("Send")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class PreviewDialog(QDialog):
    def __init__(self, payload: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Forhåndsvis pseudonymisert FASTA")
        self.resize(760, 620)
        layout = QVBoxLayout(self)
        label = QLabel("Dette er payloaden som kan lagres eller sendes. Ingen data sendes nå.")
        label.setWordWrap(True)
        layout.addWidget(label)
        preview = QPlainTextEdit()
        preview.setReadOnly(True)
        preview.setPlainText(payload)
        preview.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        layout.addWidget(preview, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class ExternalWorker(QObject):
    succeeded = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, service: str, batch: ExternalBatch):
        super().__init__()
        self.service = service
        self.batch = batch

    @pyqtSlot()
    def run(self) -> None:
        try:
            result = (
                ImgtClient().submit(self.batch)
                if self.service == "IMGT"
                else ArrestClient().submit(self.batch)
            )
        except (ExternalAnalysisError, OSError, ValueError) as exc:
            self.failed.emit(str(exc))
            return
        self.succeeded.emit(result)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = QSettings("IGH", "IGH Merge")
        self.service = MergeService()
        self.result: MergeResult | None = None
        self.external_batch: ExternalBatch | None = None
        self.imgt_result: ImgtBatchResult | None = None
        self.arrest_result: ArrestBatchResult | None = None
        self._imgt_status_by_row: dict[int, str] = {}
        self._arrest_status_by_row: dict[int, str] = {}
        self._external_thread: QThread | None = None
        self._external_worker: ExternalWorker | None = None
        self.setWindowTitle("IGH Merge")
        self.resize(1320, 850)
        self._build()
        self._style()

    def _build(self) -> None:
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(12)

        header = QHBoxLayout()
        title_box = QVBoxLayout()
        title = QLabel("IGH Merge")
        title.setFont(QFont("Segoe UI", 24, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {Palette.navy}")
        subtitle = QLabel("Lokal sammenslåing og kontroll av IGHV-SHM")
        subtitle.setStyleSheet(f"color: {Palette.muted}")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        header.addLayout(title_box)
        header.addStretch()
        self.status_badge = QLabel("Klar")
        self.status_badge.setObjectName("StatusBadge")
        header.addWidget(self.status_badge)
        layout.addLayout(header)

        cards = QHBoxLayout()
        self.row_card = MetricCard("Merged-rader", Palette.navy)
        self.control_card = MetricCard("Kontrollfeil", Palette.red)
        self.support_card = MetricCard("FR1-støtte", Palette.green)
        for card in (self.row_card, self.control_card, self.support_card):
            cards.addWidget(card)
        layout.addLayout(cards)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._run_tab(), "Kjøring")
        self.tabs.addTab(self._controls_tab(), "Kontroller")
        self.tabs.addTab(self._external_tab(), "IMGT og ARResT")
        self.tabs.addTab(self._export_tab(), "Eksport")
        self.tabs.addTab(self._settings_tab(), "Innstillinger")
        layout.addWidget(self.tabs, 1)
        self.setCentralWidget(root)

    def _run_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        group = QGroupBox("Kjøringsmappe")
        grid = QGridLayout(group)
        self.run_edit = QLineEdit(
            self.settings.value("defaultDataDirectory", str(Path.home() / "Documents" / "IGH-data"))
        )
        browse = QPushButton("Velg mappe")
        browse.clicked.connect(self._browse_run)
        self.validate_button = QPushButton("Valider kjøring")
        self.validate_button.setObjectName("PrimaryButton")
        self.validate_button.clicked.connect(self._validate)
        grid.addWidget(QLabel("Mappe"), 0, 0)
        grid.addWidget(self.run_edit, 0, 1)
        grid.addWidget(browse, 0, 2)
        grid.addWidget(self.validate_button, 1, 2)
        layout.addWidget(group)

        self.file_table = QTableWidget(0, 5)
        self.file_table.setHorizontalHeaderLabels(["S-nr.", "Prøve", "Leader-rader", "FR1-rader", "Status"])
        self.file_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.file_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        layout.addWidget(self.file_table, 1)
        self.run_message = QLabel("Velg en kjøringsmappe og valider før eksport.")
        self.run_message.setWordWrap(True)
        layout.addWidget(self.run_message)
        return page

    def _controls_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self.control_table = QTableWidget(0, 4)
        self.control_table.setHorizontalHeaderLabels(["Kontroll", "Target", "Status", "Detaljer"])
        self.control_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.control_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        layout.addWidget(QLabel("Kontroller"))
        layout.addWidget(self.control_table, 1)
        return page

    def _external_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        information = QLabel(
            "Velg Leader-sekvenser. Før sending erstattes prøvenummeret med en tilfeldig "
            "ekstern ID. Kun FASTA-headeren og nukleotidsekvensen sendes."
        )
        information.setWordWrap(True)
        layout.addWidget(information)

        self.candidate_table = QTableWidget(0, 10)
        self.candidate_table.setHorizontalHeaderLabels(
            [
                "Velg",
                "Ekstern ID",
                "Prøve (kun lokal)",
                "Target",
                "Rang",
                "% reads",
                "IMGT",
                "ARResT",
                "Subset",
                "Gruppe / kommentar",
            ]
        )
        self.candidate_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.candidate_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        layout.addWidget(self.candidate_table, 1)

        actions = QHBoxLayout()
        self.select_candidates_button = QPushButton("Velg gule Leader-kandidater")
        self.select_candidates_button.clicked.connect(self._select_candidates)
        preview_fasta = QPushButton("Forhåndsvis FASTA")
        preview_fasta.clicked.connect(self._preview_fasta)
        export_fasta = QPushButton("Lagre FASTA lokalt")
        export_fasta.clicked.connect(self._export_fasta)
        self.send_imgt_button = QPushButton("Send til IMGT")
        self.send_imgt_button.setObjectName("PrimaryButton")
        self.send_imgt_button.setEnabled(False)
        self.send_imgt_button.clicked.connect(self._send_imgt)
        self.send_arrest_button = QPushButton("Send til ARResT")
        self.send_arrest_button.setObjectName("PrimaryButton")
        self.send_arrest_button.setEnabled(False)
        self.send_arrest_button.clicked.connect(self._send_arrest)
        self.report_button = QPushButton("Lag rapportutkast")
        self.report_button.setEnabled(False)
        self.report_button.clicked.connect(self._generate_reports)
        for button in (
            self.select_candidates_button,
            preview_fasta,
            export_fasta,
            self.send_imgt_button,
            self.send_arrest_button,
            self.report_button,
        ):
            actions.addWidget(button)
        actions.addStretch()
        layout.addLayout(actions)

        self.external_status = QLabel(
            "Ingen sekvenser er sendt. Maksimalt 50 sekvenser per batch."
        )
        self.external_status.setWordWrap(True)
        layout.addWidget(self.external_status)
        return page

    def _export_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        excel_group = QGroupBox("Merged Excel")
        grid = QGridLayout(excel_group)
        self.output_edit = QLineEdit()
        output_browse = QPushButton("Velg fil")
        output_browse.clicked.connect(self._browse_output)
        self.export_button = QPushButton("Eksporter merged.xlsx")
        self.export_button.setObjectName("PrimaryButton")
        self.export_button.setEnabled(False)
        self.export_button.clicked.connect(self._export_excel)
        grid.addWidget(QLabel("Output"), 0, 0)
        grid.addWidget(self.output_edit, 0, 1)
        grid.addWidget(output_browse, 0, 2)
        grid.addWidget(self.export_button, 1, 2)
        layout.addWidget(excel_group)
        layout.addStretch()
        return page

    def _settings_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        group = QGroupBox("Lokale innstillinger")
        form = QFormLayout(group)
        self.default_data_edit = QLineEdit(
            self.settings.value("defaultDataDirectory", str(Path.home() / "Documents" / "IGH-data"))
        )
        self.expected_spin = QSpinBox()
        self.expected_spin.setRange(1, 96)
        self.expected_spin.setValue(int(self.settings.value("expectedSamples", 24)))
        save = QPushButton("Lagre innstillinger")
        save.setObjectName("PrimaryButton")
        save.clicked.connect(self._save_settings)
        form.addRow("Standard datamappe", self.default_data_edit)
        form.addRow("Forventet antall per target", self.expected_spin)
        form.addRow("", save)
        layout.addWidget(group)

        rules = QGroupBox("Kontrollgrenser (skrivebeskyttet)")
        rules_layout = QVBoxLayout(rules)
        rules_layout.addWidget(
            QLabel(
                "IGH-PK ≥2,5 % | IGH-SHM ≥2,5 % og mutasjon ≥2,0 % | "
                "NGS NEG <1,0 % | NTC <10 000 reads\n"
                "Leader og FR1 kontrolleres separat. Prøver vurderes manuelt."
            )
        )
        layout.addWidget(rules)
        layout.addStretch()
        return page

    def _browse_run(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Velg IGHV-kjøring", self.run_edit.text())
        if path:
            self.run_edit.setText(path)

    def _browse_output(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Lagre merged-fil", self.output_edit.text(), "Excel (*.xlsx)"
        )
        if path:
            self.output_edit.setText(path if path.lower().endswith(".xlsx") else f"{path}.xlsx")

    def _validate(self) -> None:
        self.status_badge.setText("Validerer")
        QApplication.processEvents()
        self.external_batch = None
        self.imgt_result = None
        self.arrest_result = None
        self._imgt_status_by_row.clear()
        self._arrest_status_by_row.clear()
        try:
            self.result = self.service.process(Path(self.run_edit.text()), self.expected_spin.value())
        except (ValidationError, OSError) as exc:
            self.result = None
            self.export_button.setEnabled(False)
            self.send_imgt_button.setEnabled(False)
            self.send_arrest_button.setEnabled(False)
            self.status_badge.setText("Validering feilet")
            QMessageBox.critical(self, "Validering feilet", str(exc))
            return
        self._populate_result()
        self.status_badge.setText("Validert")
        self.export_button.setEnabled(True)
        self.send_imgt_button.setEnabled(True)
        self.send_arrest_button.setEnabled(True)
        default_output = (
            self.result.manifest.run_directory / f"{self.result.manifest.run_date}_merged.xlsx"
        )
        self.output_edit.setText(str(default_output))
        if self.result.manifest.warnings:
            self.run_message.setText("\n".join(self.result.manifest.warnings))
        else:
            self.run_message.setText("Kjøringen er strukturelt validert og klar for eksport.")

    def _populate_result(self) -> None:
        assert self.result is not None
        manifest = self.result.manifest
        pairs: dict[tuple[str, int], dict[str, int]] = {}
        for item in manifest.sample_files:
            pairs.setdefault((item.sample, item.sample_number), {})[item.target] = len(item.rows)
        self.file_table.setRowCount(0)
        for (sample, number), counts in sorted(pairs.items(), key=lambda item: item[0][1]):
            row = self.file_table.rowCount()
            self.file_table.insertRow(row)
            values = [number, sample, counts.get("Leader", 0), counts.get("FR1", 0), "OK"]
            for column, value in enumerate(values):
                self.file_table.setItem(row, column, QTableWidgetItem(str(value)))

        self._fill_control_table(self.result.qc.controls)
        self._fill_candidates()
        self.row_card.value.setText(str(len(self.result.rows)))
        self.control_card.value.setText(
            str(sum(item.status == "FEIL" for item in self.result.qc.controls))
        )
        self.support_card.value.setText(
            str(sum(bool(row.comment) for row in self.result.rows if row.target == "FR1"))
        )

    def _fill_control_table(self, items: tuple[QcItem, ...]) -> None:
        self.control_table.setRowCount(0)
        for item in items:
            row = self.control_table.rowCount()
            self.control_table.insertRow(row)
            values = [item.sample, item.target, item.status, item.message]
            for column, value in enumerate(values):
                cell = QTableWidgetItem(str(value))
                if item.status == "FEIL":
                    cell.setBackground(QColor(Palette.pale_red))
                else:
                    cell.setBackground(QColor(Palette.pale_green))
                self.control_table.setItem(row, column, cell)

    def _fill_candidates(self) -> None:
        assert self.result is not None
        self.candidate_table.setRowCount(0)
        for result_index, item in enumerate(self.result.rows):
            if item.target != "Leader":
                continue
            row = self.candidate_table.rowCount()
            self.candidate_table.insertRow(row)
            check = QTableWidgetItem()
            check.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            is_functional_group = self._is_functional_group_candidate(result_index)
            check.setCheckState(
                Qt.CheckState.Checked
                if is_functional_group
                else Qt.CheckState.Unchecked
            )
            check.setData(Qt.ItemDataRole.UserRole, result_index)
            self.candidate_table.setItem(row, 0, check)
            values = [
                "",
                item.sample,
                item.target,
                item.source.rank,
                item.source.percent_total_reads,
                self._imgt_status_by_row.get(result_index, ""),
                self._arrest_status_by_row.get(result_index, ""),
                item.subset,
                item.comment,
            ]
            for column, value in enumerate(values, start=1):
                self.candidate_table.setItem(row, column, QTableWidgetItem(str(value)))
            if is_functional_group:
                for column in range(self.candidate_table.columnCount()):
                    self.candidate_table.item(row, column).setBackground(
                        QColor(Palette.functional_yellow)
                    )
                    self.candidate_table.item(row, column).setToolTip(
                        "Foreløpig funksjonell gruppe: Y/Y og enten ≥2,5 % reads "
                        "eller eksakt FR1-støtte ≥2,5 %."
                    )
            elif (
                item.source.percent_total_reads >= 2.5
                and (
                    item.source.in_frame.strip().upper() != "Y"
                    or item.source.no_stop_codon.strip().upper() != "Y"
                )
            ):
                for column in range(self.candidate_table.columnCount()):
                    self.candidate_table.item(row, column).setBackground(
                        QColor(Palette.excluded_gray)
                    )
                    self.candidate_table.item(row, column).setToolTip(
                        "Ikke gul: LymphoTrack viser ikke både In-frame=Y og "
                        "No Stop codon=Y."
                    )

    def _select_candidates(self) -> None:
        for row in range(self.candidate_table.rowCount()):
            result_index = int(
                self.candidate_table.item(row, 0).data(Qt.ItemDataRole.UserRole)
            )
            self.candidate_table.item(row, 0).setCheckState(
                Qt.CheckState.Checked
                if self._is_functional_group_candidate(result_index)
                else Qt.CheckState.Unchecked
            )

    def _is_functional_group_candidate(self, result_index: int) -> bool:
        """Mirror the yellow-row convention without making a clinical decision."""
        if not self.result:
            return False
        leader = self.result.rows[result_index]
        source = leader.source
        if (
            leader.target != "Leader"
            or source.in_frame.strip().upper() != "Y"
            or source.no_stop_codon.strip().upper() != "Y"
        ):
            return False
        if source.percent_total_reads >= 2.5:
            return True

        label = f"Leader-{source.rank}"
        return any(
            row.sample == leader.sample
            and row.target == "FR1"
            and row.source.percent_total_reads >= 2.5
            and row.source.in_frame.strip().upper() == "Y"
            and row.source.no_stop_codon.strip().upper() == "Y"
            and label in row.comment.replace("(", "").replace(")", "").split()
            for row in self.result.rows
        )

    def _selected_result_indices(self) -> tuple[int, ...]:
        indices: list[int] = []
        for row in range(self.candidate_table.rowCount()):
            check = self.candidate_table.item(row, 0)
            if check.checkState() == Qt.CheckState.Checked:
                indices.append(int(check.data(Qt.ItemDataRole.UserRole)))
        return tuple(indices)

    def _ensure_external_batch(self) -> ExternalBatch:
        if not self.result:
            raise ValueError("Valider en kjøring før du velger sekvenser")
        selected = self._selected_result_indices()
        if not selected:
            raise ValueError("Velg minst én Leader-sekvens")
        if (
            self.external_batch is not None
            and tuple(item.row_index for item in self.external_batch.candidates) == selected
        ):
            return self.external_batch
        self.external_batch = create_external_batch(
            self.result.manifest.run_date,
            [(index, self.result.rows[index]) for index in selected],
        )
        self.imgt_result = None
        self.arrest_result = None
        self.report_button.setEnabled(False)
        external_ids = {
            candidate.row_index: candidate.external_id
            for candidate in self.external_batch.candidates
        }
        for table_row in range(self.candidate_table.rowCount()):
            result_index = int(
                self.candidate_table.item(table_row, 0).data(Qt.ItemDataRole.UserRole)
            )
            self.candidate_table.item(table_row, 1).setText(
                external_ids.get(result_index, "")
            )
        return self.external_batch

    def _preview_fasta(self) -> None:
        try:
            batch = self._ensure_external_batch()
        except ValueError as exc:
            QMessageBox.warning(self, "Kan ikke lage FASTA", str(exc))
            return
        PreviewDialog(batch.fasta, self).exec()

    def _send_imgt(self) -> None:
        self._confirm_and_start_external("IMGT", IMGT_URL)

    def _send_arrest(self) -> None:
        self._confirm_and_start_external("ARResT", ARREST_URL)

    def _confirm_and_start_external(self, service: str, endpoint: str) -> None:
        if self._external_thread and self._external_thread.isRunning():
            QMessageBox.information(
                self, "Analyse pågår", "Vent til den pågående analysen er ferdig."
            )
            return
        try:
            batch = self._ensure_external_batch()
        except ValueError as exc:
            QMessageBox.warning(self, "Kan ikke sende", str(exc))
            return
        dialog = PayloadDialog(service, endpoint, batch.fasta, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._start_external(service, batch)

    def _start_external(self, service: str, batch: ExternalBatch) -> None:
        assert self.result is not None
        try:
            save_batch_mapping(self.result.manifest.run_directory, batch)
        except (OSError, PrivacyError) as exc:
            QMessageBox.critical(
                self,
                "Kan ikke starte ekstern analyse",
                f"Den lokale ID-koblingen kunne ikke lagres:\n{exc}",
            )
            return
        self.send_imgt_button.setEnabled(False)
        self.send_arrest_button.setEnabled(False)
        self.external_status.setText(
            f"Sender {len(batch.candidates)} pseudonymiserte sekvenser til {service} …"
        )
        self.status_badge.setText(f"{service} pågår")
        thread = QThread(self)
        worker = ExternalWorker(service, batch)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.succeeded.connect(partial(self._external_succeeded, service, batch))
        worker.failed.connect(partial(self._external_failed, service))
        worker.succeeded.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(self._external_finished)
        self._external_thread = thread
        self._external_worker = worker
        thread.start()

    def _external_succeeded(
        self,
        service: str,
        batch: ExternalBatch,
        result: object,
    ) -> None:
        if not self.result:
            return
        try:
            if service == "IMGT":
                if not isinstance(result, ImgtBatchResult):
                    raise TypeError("Uventet IMGT-resultattype")
                save_path = save_imgt_result(
                    self.result.manifest.run_directory, batch, result
                )
                apply_imgt_result(self.result.rows, batch, result)
                self.imgt_result = result
                self.report_button.setEnabled(True)
                for record in result.records:
                    row_index = batch.by_id()[record.external_id].row_index
                    status = (
                        "productive"
                        if record.productive is True
                        else "not productive"
                        if record.productive is False
                        else "ukjent"
                    )
                    self._imgt_status_by_row[row_index] = status
                version = result.program_version or "ukjent versjon"
                message = (
                    f"IMGT {version} fullført for {len(result.records)} sekvenser. "
                    f"Resultatet er lagret i {save_path.parent}."
                )
            else:
                if not isinstance(result, ArrestBatchResult):
                    raise TypeError("Uventet ARResT-resultattype")
                save_path = save_arrest_result(
                    self.result.manifest.run_directory, batch, result
                )
                apply_arrest_result(self.result.rows, batch, result)
                self.arrest_result = result
                for record in result.records:
                    row_index = batch.by_id()[record.external_id].row_index
                    status = record.subset or "ukjent"
                    if record.confidence:
                        status += f" ({record.confidence})"
                    self._arrest_status_by_row[row_index] = status
                message = (
                    f"ARResT fullført for {len(result.records)} sekvenser. "
                    f"Resultatet er lagret i {save_path.parent}."
                )
        except (OSError, PrivacyError, TypeError, ValueError) as exc:
            self.external_status.setText(f"{service}-resultatet kunne ikke lagres: {exc}")
            QMessageBox.critical(self, f"{service} feilet", str(exc))
            return
        self._refresh_external_table()
        self.external_status.setText(message)
        self.status_badge.setText(f"{service} fullført")

    def _generate_reports(self) -> None:
        if not self.result or not self.external_batch or not self.imgt_result:
            QMessageBox.warning(self, "Rapport", "IMGT må være fullført først.")
            return
        try:
            directory = generate_clinical_report_package(
                self.result.manifest.run_directory,
                self.result.rows,
                self.external_batch,
                self.imgt_result,
                self.arrest_result,
            )
        except (OSError, PrivacyError, ValueError) as exc:
            QMessageBox.critical(self, "Rapport feilet", str(exc))
            return
        QMessageBox.information(
            self,
            "Rapporter laget",
            f"Rapportutkast og auditdata er lagret i:\n{directory}",
        )

    def _external_failed(self, service: str, message: str) -> None:
        self.external_status.setText(f"{service} feilet: {message}")
        self.status_badge.setText(f"{service} feilet")
        QMessageBox.critical(self, f"{service} feilet", message)

    def _external_finished(self) -> None:
        self.send_imgt_button.setEnabled(True)
        self.send_arrest_button.setEnabled(True)
        if self._external_worker:
            self._external_worker.deleteLater()
        if self._external_thread:
            self._external_thread.deleteLater()
        self._external_worker = None
        self._external_thread = None

    def _refresh_external_table(self) -> None:
        if not self.result:
            return
        external_ids = (
            {
                candidate.row_index: candidate.external_id
                for candidate in self.external_batch.candidates
            }
            if self.external_batch
            else {}
        )
        for table_row in range(self.candidate_table.rowCount()):
            result_index = int(
                self.candidate_table.item(table_row, 0).data(Qt.ItemDataRole.UserRole)
            )
            values = {
                1: external_ids.get(result_index, ""),
                6: self._imgt_status_by_row.get(result_index, ""),
                7: self._arrest_status_by_row.get(result_index, ""),
                8: self.result.rows[result_index].subset,
                9: self.result.rows[result_index].comment,
            }
            for column, value in values.items():
                self.candidate_table.item(table_row, column).setText(value)

    def _export_excel(self) -> None:
        if not self.result:
            return
        if self.result.manifest.warnings:
            answer = QMessageBox.question(
                self,
                "Bekreft prøveantall",
                "\n".join(self.result.manifest.warnings) + "\nVil du likevel eksportere?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        output = Path(self.output_edit.text())
        overwrite = False
        if output.exists():
            answer = QMessageBox.question(
                self, "Filen finnes", f"{output.name} finnes allerede. Overskrive?"
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            overwrite = True
        try:
            written = self.service.export(self.result, output, overwrite=overwrite)
        except (OSError, PrivacyError, FileExistsError) as exc:
            QMessageBox.critical(self, "Eksport feilet", str(exc))
            return
        self.status_badge.setText("Eksportert")
        QMessageBox.information(
            self,
            "Eksport fullført",
            f"Skrev {len(self.result.rows)} rader til:\n{written}",
        )

    def _export_fasta(self) -> None:
        try:
            batch = self._ensure_external_batch()
        except ValueError as exc:
            QMessageBox.warning(self, "Kan ikke lage FASTA", str(exc))
            return
        default = ""
        if self.result:
            default = str(self.result.manifest.run_directory / f"{self.result.manifest.run_date}_arbeidsliste.fasta")
        path, _ = QFileDialog.getSaveFileName(self, "Lagre lokal FASTA", default, "FASTA (*.fasta)")
        if not path:
            return
        output = Path(path)
        if output.exists():
            QMessageBox.warning(self, "Filen finnes", "Velg et nytt filnavn; FASTA overskrives ikke.")
            return
        try:
            ensure_outside_git(output)
        except PrivacyError as exc:
            QMessageBox.critical(self, "Ugyldig lagringssted", str(exc))
            return
        output.write_text(
            batch.fasta,
            encoding="utf-8",
        )
        QMessageBox.information(
            self,
            "FASTA lagret lokalt",
            f"Lagret {len(batch.candidates)} pseudonymiserte sekvenser. "
            "Ingen data er sendt eksternt.",
        )

    def closeEvent(self, event) -> None:
        if self._external_thread and self._external_thread.isRunning():
            QMessageBox.information(
                self,
                "Analyse pågår",
                "Vent til den eksterne analysen er ferdig før appen lukkes.",
            )
            event.ignore()
            return
        super().closeEvent(event)

    def _save_settings(self) -> None:
        self.settings.setValue("defaultDataDirectory", self.default_data_edit.text())
        self.settings.setValue("expectedSamples", self.expected_spin.value())
        self.run_edit.setText(self.default_data_edit.text())
        QMessageBox.information(self, "Innstillinger", "Lokale innstillinger er lagret.")

    def _style(self) -> None:
        self.setStyleSheet(
            f"""
            QMainWindow, QWidget {{ background: {Palette.app_bg}; color: {Palette.ink}; font-family: "Segoe UI"; }}
            QGroupBox {{ background: {Palette.panel}; border: 1px solid {Palette.border}; border-radius: 6px;
                         margin-top: 10px; padding: 12px; font-weight: 600; }}
            QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 5px; }}
            QLineEdit, QSpinBox, QTableWidget {{ background: white; border: 1px solid {Palette.border}; }}
            QPushButton {{ background: white; border: 1px solid {Palette.border}; border-radius: 4px; padding: 7px 12px; }}
            QPushButton:hover {{ border-color: {Palette.blue}; }}
            QPushButton#PrimaryButton {{ background: {Palette.navy}; color: white; font-weight: 600; }}
            QPushButton:disabled {{ color: #8B949C; background: #E9EEF2; }}
            QFrame#MetricCard {{ background: white; border: 1px solid {Palette.border}; border-radius: 7px; }}
            QLabel#StatusBadge {{ background: {Palette.navy}; color: white; padding: 7px 12px; border-radius: 12px; }}
            QHeaderView::section {{ background: {Palette.navy}; color: white; padding: 6px; border: 0; }}
            QTabWidget::pane {{ border: 1px solid {Palette.border}; background: white; }}
            QTabBar::tab {{ padding: 8px 16px; background: #E7EDF2; }}
            QTabBar::tab:selected {{ background: white; color: {Palette.navy}; font-weight: 600; }}
            """
        )
