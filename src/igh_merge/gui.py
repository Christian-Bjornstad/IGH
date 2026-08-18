from __future__ import annotations

from functools import partial
from pathlib import Path

from PyQt6.QtCore import QObject, QSettings, QThread, Qt, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QColor, QFont, QIcon
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
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
    QProgressBar,
    QPushButton,
    QSpinBox,
    QStackedWidget,
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
from .candidates import is_functional_group_candidate
from .io import ValidationError
from .models import MergeResult, QcItem
from .privacy import PrivacyError, ensure_outside_git
from .reports import generate_clinical_report_package
from .service import MergeService


class Palette:
    ink = "#0F172A"
    muted = "#475569"
    panel = "#FFFFFF"
    app_bg = "#F8FAFC"
    subtle = "#F1F5F9"
    border = "#CBD5E1"
    navy = "#1E3A5F"
    blue = "#2563EB"
    blue_hover = "#1D4ED8"
    green = "#15803D"
    red = "#B91C1C"
    amber = "#B45309"
    pale_blue = "#EFF6FF"
    pale_green = "#F0FDF4"
    pale_red = "#FEF2F2"
    pale_amber = "#FFFBEB"
    functional_yellow = "#FFFF00"
    excluded_gray = "#D9D9D9"


APP_ICON_PATH = Path(__file__).resolve().parent / "assets" / "igh-merge-icon.ico"


def application_icon() -> QIcon:
    return QIcon(str(APP_ICON_PATH)) if APP_ICON_PATH.is_file() else QIcon()


class MetricCard(QFrame):
    def __init__(self, label: str, description: str, color: str):
        super().__init__()
        self.setObjectName("MetricCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(3)
        eyebrow = QLabel(label.upper())
        eyebrow.setObjectName("MetricLabel")
        self.value = QLabel("0")
        self.value.setFont(QFont("Segoe UI", 24, QFont.Weight.Bold))
        self.value.setStyleSheet(f"color: {color}")
        caption = QLabel(description)
        caption.setObjectName("MetricDescription")
        layout.addWidget(eyebrow)
        layout.addWidget(self.value)
        layout.addWidget(caption)


class PayloadDialog(QDialog):
    def __init__(self, service: str, endpoint: str, payload: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Confirm sending to {service}")
        self.resize(760, 620)
        layout = QVBoxLayout(self)
        description = QLabel(
            f"Recipient: {endpoint}\n"
            "This is the exact content being sent. Sample numbers and filenames are not included."
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
        self.setWindowTitle("Preview Pseudonymized FASTA")
        self.resize(760, 620)
        layout = QVBoxLayout(self)
        label = QLabel("This is the payload that can be saved or sent. No data is sent yet.")
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
        self.settings = QSettings("IGHV", "IGHV")
        self.service = MergeService()
        self.result: MergeResult | None = None
        self.external_batch: ExternalBatch | None = None
        self.imgt_result: ImgtBatchResult | None = None
        self.arrest_result: ArrestBatchResult | None = None
        self._imgt_status_by_row: dict[int, str] = {}
        self._arrest_status_by_row: dict[int, str] = {}
        self._external_thread: QThread | None = None
        self._external_worker: ExternalWorker | None = None
        self.setWindowTitle("IGHV")
        self.setWindowIcon(application_icon())
        self.setMinimumSize(1040, 720)
        self.resize(1380, 900)
        self._build()
        self._style()
        self._set_status("Ready", "neutral")
        self._apply_interaction_cursors()

    def _build(self) -> None:
        root = QWidget()
        root.setObjectName("AppRoot")
        main_layout = QHBoxLayout(root)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Left sidebar navigation
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(240)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(16, 24, 16, 24)
        sidebar_layout.setSpacing(8)

        # App brand in sidebar
        brand_container = QWidget()
        brand_layout = QHBoxLayout(brand_container)
        brand_layout.setContentsMargins(8, 8, 8, 16)
        brand_layout.setSpacing(12)
        brand_icon = QLabel()
        brand_icon.setObjectName("SidebarBrandIcon")
        brand_icon.setFixedSize(40, 40)
        brand_icon.setPixmap(application_icon().pixmap(36, 36))
        brand_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        brand_layout.addWidget(brand_icon)
        brand_text = QVBoxLayout()
        brand_text.setSpacing(0)
        app_title = QLabel("IGHV")
        app_title.setObjectName("SidebarAppTitle")
        app_subtitle = QLabel("Molecular Pathology")
        app_subtitle.setObjectName("SidebarAppSubtitle")
        brand_text.addWidget(app_title)
        brand_text.addWidget(app_subtitle)
        brand_layout.addLayout(brand_text)
        brand_layout.addStretch()
        sidebar_layout.addWidget(brand_container)

        # Navigation buttons
        self.nav_buttons = []
        nav_items = [
            ("Run", "Run validation & file detection"),
            ("Controls", "QC controls for Leader & FR1"),
            ("IMGT & ARResT", "External sequence analysis"),
            ("Export", "Generate merged Excel workbook"),
            ("Settings", "Local preferences & defaults"),
        ]
        for idx, (label, tooltip) in enumerate(nav_items):
            btn = QPushButton(label)
            btn.setObjectName("NavButton")
            btn.setCheckable(True)
            btn.setToolTip(tooltip)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(partial(self._switch_page, idx))
            self.nav_buttons.append(btn)
            sidebar_layout.addWidget(btn)
        self.nav_buttons[0].setChecked(True)

        sidebar_layout.addStretch()

        # Status badge in sidebar
        self.status_badge = QLabel("Ready")
        self.status_badge.setObjectName("SidebarStatusBadge")
        self.status_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_badge.setFixedHeight(32)
        self.status_badge.setAccessibleName("Application status")
        sidebar_layout.addWidget(self.status_badge)

        # Version info
        version_label = QLabel("v0.2.0  •  Python 3.11+")
        version_label.setObjectName("SidebarVersion")
        version_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sidebar_layout.addWidget(version_label)

        main_layout.addWidget(sidebar)

        # Main content area
        content = QWidget()
        content.setObjectName("ContentArea")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(32, 24, 32, 24)
        content_layout.setSpacing(20)

        # Top bar with privacy badge
        top_bar = QHBoxLayout()
        top_bar.setSpacing(16)
        privacy = QLabel("LOCAL AND TRACEABLE")
        privacy.setObjectName("PrivacyBadge")
        privacy.setToolTip(
            "Raw files and linkage data are stored locally. External sending requires explicit confirmation."
        )
        privacy.setFixedHeight(32)
        top_bar.addWidget(privacy)
        top_bar.addStretch()
        content_layout.addLayout(top_bar)

        # Metric cards
        cards = QHBoxLayout()
        cards.setSpacing(16)
        self.row_card = MetricCard("Merged rows", "Leader + FR1", Palette.navy)
        self.control_card = MetricCard("Control errors", "Requires follow-up", Palette.red)
        self.support_card = MetricCard("FR1 support", "Exact overlaps", Palette.green)
        for card in (self.row_card, self.control_card, self.support_card):
            cards.addWidget(card)
        content_layout.addLayout(cards)

        # Stacked widget for pages
        self.page_stack = QStackedWidget()
        self.page_stack.setObjectName("PageStack")
        self.page_stack.addWidget(self._run_tab())
        self.page_stack.addWidget(self._controls_tab())
        self.page_stack.addWidget(self._external_tab())
        self.page_stack.addWidget(self._export_tab())
        self.page_stack.addWidget(self._settings_tab())
        content_layout.addWidget(self.page_stack, 1)

        # Footer
        footer = QHBoxLayout()
        footer_text = QLabel(
            "IGHV  •  raw files are never modified  •  external sending requires confirmation"
        )
        footer_text.setObjectName("FooterText")
        footer.addWidget(footer_text)
        footer.addStretch()
        content_layout.addLayout(footer)

        main_layout.addWidget(content, 1)
        self.setCentralWidget(root)

    def _run_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 18, 20, 20)
        layout.setSpacing(14)
        intro = QLabel(
            "1  RUN   Select the folder containing Leader and FR1 output. "
            "The app reads files without modifying raw data."
        )
        intro.setObjectName("PageIntro")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        group = QGroupBox("Select and validate run folder")
        grid = QGridLayout(group)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)
        self.run_edit = QLineEdit(
            self.settings.value("defaultDataDirectory", str(Path.home() / "Documents" / "IGHV-data"))
        )
        self.run_edit.setClearButtonEnabled(True)
        self.run_edit.setAccessibleName("Run folder")
        browse = QPushButton("Browse folder")
        browse.clicked.connect(self._browse_run)
        self.validate_button = QPushButton("Validate run")
        self.validate_button.setObjectName("PrimaryButton")
        self.validate_button.clicked.connect(self._validate)
        grid.addWidget(QLabel("Folder"), 0, 0)
        grid.addWidget(self.run_edit, 0, 1)
        grid.addWidget(browse, 0, 2)
        grid.addWidget(self.validate_button, 0, 3)
        layout.addWidget(group)

        self.file_table = QTableWidget(0, 5)
        self.file_table.setHorizontalHeaderLabels(["S-no.", "Sample", "Leader rows", "FR1 rows", "Status"])
        self._configure_table(self.file_table)
        self.file_table.setAccessibleName("Detected sample files")
        layout.addWidget(self.file_table, 1)
        self.run_message = QLabel("Select a run folder and validate before export.")
        self.run_message.setObjectName("InfoCallout")
        self.run_message.setWordWrap(True)
        layout.addWidget(self.run_message)
        return page

    def _controls_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 18, 20, 20)
        layout.setSpacing(14)
        intro = QLabel(
            "2  CONTROLS   Run controls are shown separately for Leader and FR1. "
            "Status must be assessed according to local procedure."
        )
        intro.setObjectName("PageIntro")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.control_table = QTableWidget(0, 4)
        self.control_table.setHorizontalHeaderLabels(["Control", "Target", "Status", "Details"])
        self._configure_table(self.control_table)
        self.control_table.setAccessibleName("Run controls")
        layout.addWidget(self.control_table, 1)
        return page

    def _external_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 18, 20, 20)
        layout.setSpacing(12)

        information = QLabel(
            "3  EXTERNAL ANALYSIS   Select Leader sequences. Before sending, "
            "the sample number is replaced with a random external ID. Only the FASTA header and "
            "nucleotide sequence are sent."
        )
        information.setObjectName("PrivacyCallout")
        information.setWordWrap(True)
        layout.addWidget(information)

        self.candidate_table = QTableWidget(0, 10)
        self.candidate_table.setHorizontalHeaderLabels(
            [
                "Select",
                "External ID",
                "Sample (local only)",
                "Target",
                "Rank",
                "% reads",
                "IMGT",
                "ARResT",
                "Subset",
                "Group / comment",
            ]
        )
        self._configure_table(self.candidate_table)
        candidate_header = self.candidate_table.horizontalHeader()
        candidate_header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        candidate_header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        candidate_header.setSectionResizeMode(9, QHeaderView.ResizeMode.Stretch)
        candidate_header.setMinimumSectionSize(58)
        self.candidate_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.candidate_table.setAccessibleName("Leader candidates for external analysis")
        layout.addWidget(self.candidate_table, 1)

        action_bar = QFrame()
        action_bar.setObjectName("ActionBar")
        action_grid = QGridLayout(action_bar)
        action_grid.setContentsMargins(12, 10, 12, 10)
        action_grid.setHorizontalSpacing(8)
        action_grid.setVerticalSpacing(8)
        local_label = QLabel("LOCAL")
        local_label.setObjectName("ActionLabel")
        external_label = QLabel("EXTERNAL")
        external_label.setObjectName("ActionLabel")
        self.select_candidates_button = QPushButton("Select yellow Leader candidates")
        self.select_candidates_button.clicked.connect(self._select_candidates)
        preview_fasta = QPushButton("Preview FASTA")
        preview_fasta.clicked.connect(self._preview_fasta)
        export_fasta = QPushButton("Save FASTA locally")
        export_fasta.clicked.connect(self._export_fasta)
        self.send_imgt_button = QPushButton("Send to IMGT")
        self.send_imgt_button.setObjectName("PrimaryButton")
        self.send_imgt_button.setEnabled(False)
        self.send_imgt_button.clicked.connect(self._send_imgt)
        self.send_arrest_button = QPushButton("Send to ARResT")
        self.send_arrest_button.setObjectName("PrimaryButton")
        self.send_arrest_button.setEnabled(False)
        self.send_arrest_button.clicked.connect(self._send_arrest)
        self.report_button = QPushButton("Generate report draft")
        self.report_button.setEnabled(False)
        self.report_button.clicked.connect(self._generate_reports)
        action_grid.addWidget(local_label, 0, 0)
        action_grid.addWidget(self.select_candidates_button, 0, 1)
        action_grid.addWidget(preview_fasta, 0, 2)
        action_grid.addWidget(export_fasta, 0, 3)
        action_grid.addWidget(external_label, 1, 0)
        action_grid.addWidget(self.send_imgt_button, 1, 1)
        action_grid.addWidget(self.send_arrest_button, 1, 2)
        action_grid.addWidget(self.report_button, 1, 3)
        action_grid.setColumnStretch(4, 1)
        layout.addWidget(action_bar)

        self.external_progress = QProgressBar()
        self.external_progress.setRange(0, 0)
        self.external_progress.setTextVisible(False)
        self.external_progress.setFixedHeight(4)
        self.external_progress.setVisible(False)
        self.external_progress.setAccessibleName("External analysis in progress")
        layout.addWidget(self.external_progress)

        self.external_status = QLabel(
            "No sequences have been sent. Maximum 50 sequences per batch."
        )
        self.external_status.setObjectName("StatusCallout")
        self.external_status.setWordWrap(True)
        layout.addWidget(self.external_status)
        return page

    def _export_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 18, 20, 20)
        layout.setSpacing(14)
        intro = QLabel(
            "4  EXPORT   Create a single compatible merged sheet with 22 columns. "
            "Existing files are overwritten only after confirmation."
        )
        intro.setObjectName("PageIntro")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        excel_group = QGroupBox("Merged Excel workbook")
        grid = QGridLayout(excel_group)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(12)
        self.output_edit = QLineEdit()
        self.output_edit.setClearButtonEnabled(True)
        self.output_edit.setAccessibleName("Filename for merged Excel")
        output_browse = QPushButton("Select file")
        output_browse.clicked.connect(self._browse_output)
        self.export_button = QPushButton("Export merged.xlsx")
        self.export_button.setObjectName("PrimaryButton")
        self.export_button.setEnabled(False)
        self.export_button.clicked.connect(self._export_excel)
        self.highlight_excel_checkbox = QCheckBox(
            "Highlight app's yellow candidate rows in Excel"
        )
        self.highlight_excel_checkbox.setToolTip(
            "Colors the same preliminary Leader candidates yellow across all 22 columns."
        )
        grid.addWidget(QLabel("Output"), 0, 0)
        grid.addWidget(self.output_edit, 0, 1)
        grid.addWidget(output_browse, 0, 2)
        grid.addWidget(self.highlight_excel_checkbox, 1, 0, 1, 2)
        grid.addWidget(self.export_button, 1, 2)
        layout.addWidget(excel_group)
        export_note = QLabel(
            "The Excel file contains a single sheet, formulas, and conditional formatting. "
            "Select yellow highlighting if candidates should also be visible in the workbook."
        )
        export_note.setObjectName("InfoCallout")
        export_note.setWordWrap(True)
        layout.addWidget(export_note)
        layout.addStretch()
        return page

    def _settings_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 18, 20, 20)
        layout.setSpacing(14)
        intro = QLabel(
            "SETTINGS   Local default choices for this Windows user. "
            "Clinical control limits are versioned and write-protected."
        )
        intro.setObjectName("PageIntro")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        group = QGroupBox("Local settings")
        form = QFormLayout(group)
        self.default_data_edit = QLineEdit(
            self.settings.value("defaultDataDirectory", str(Path.home() / "Documents" / "IGHV-data"))
        )
        self.default_data_edit.setClearButtonEnabled(True)
        self.default_data_edit.setAccessibleName("Default data folder")
        self.expected_spin = QSpinBox()
        self.expected_spin.setRange(1, 96)
        self.expected_spin.setValue(int(self.settings.value("expectedSamples", 24)))
        save = QPushButton("Save settings")
        save.setObjectName("PrimaryButton")
        save.setMinimumWidth(210)
        save.clicked.connect(self._save_settings)
        save_row = QHBoxLayout()
        save_row.addStretch()
        save_row.addWidget(save)
        form.addRow("Default data folder", self.default_data_edit)
        form.addRow("Expected samples per target", self.expected_spin)
        form.addRow("", save_row)
        layout.addWidget(group)

        rules = QGroupBox("Control limits (write-protected)")
        rules_layout = QVBoxLayout(rules)
        rules_layout.addWidget(
            QLabel(
                "IGH-PK ≥2.5 % | IGH-SHM ≥2.5 % and mutation ≥2.0 % | "
                "NGS NEG <1.0 % | NTC <10 000 reads\n"
                "Leader and FR1 are controlled separately. Samples are assessed manually."
            )
        )
        layout.addWidget(rules)
        layout.addStretch()
        return page

    def _configure_table(self, table: QTableWidget) -> None:
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        table.horizontalHeader().setMinimumHeight(38)
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(34)
        table.setAlternatingRowColors(True)
        table.setShowGrid(False)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)

    def _set_status(self, text: str, tone: str) -> None:
        self.status_badge.setText(text)
        self.status_badge.setProperty("tone", tone)
        self.status_badge.style().unpolish(self.status_badge)
        self.status_badge.style().polish(self.status_badge)

    def _apply_interaction_cursors(self) -> None:
        for widget_type in (QPushButton, QCheckBox):
            for widget in self.findChildren(widget_type):
                widget.setCursor(Qt.CursorShape.PointingHandCursor)

    def _switch_page(self, index: int) -> None:
        self.page_stack.setCurrentIndex(index)
        for i, btn in enumerate(self.nav_buttons):
            btn.setChecked(i == index)

    def _browse_run(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Select IGHV run", self.run_edit.text())
        if path:
            self.run_edit.setText(path)

    def _browse_output(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Save merged file", self.output_edit.text(), "Excel (*.xlsx)"
        )
        if path:
            self.output_edit.setText(path if path.lower().endswith(".xlsx") else f"{path}.xlsx")

    def _validate(self) -> None:
        self._set_status("Validating …", "busy")
        self.validate_button.setEnabled(False)
        self.validate_button.setText("Validating …")
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
            self._set_status("Validation failed", "error")
            QMessageBox.critical(self, "Validation failed", str(exc))
            return
        finally:
            self.validate_button.setEnabled(True)
            self.validate_button.setText("Validate run")
        self._populate_result()
        self._set_status("Validated", "success")
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
            self.run_message.setText("Run is structurally validated and ready for export.")

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
                        "Preliminary functional group: Y/Y and either ≥2.5 % reads "
                        "or exact FR1 support ≥2.5 %."
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
                        "Not yellow: LymphoTrack does not show both In-frame=Y and "
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
        return is_functional_group_candidate(self.result.rows, result_index)

    def _selected_result_indices(self) -> tuple[int, ...]:
        indices: list[int] = []
        for row in range(self.candidate_table.rowCount()):
            check = self.candidate_table.item(row, 0)
            if check.checkState() == Qt.CheckState.Checked:
                indices.append(int(check.data(Qt.ItemDataRole.UserRole)))
        return tuple(indices)

    def _ensure_external_batch(self) -> ExternalBatch:
        if not self.result:
            raise ValueError("Validate a run before selecting sequences")
        selected = self._selected_result_indices()
        if not selected:
            raise ValueError("Select at least one Leader sequence")
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
            QMessageBox.warning(self, "Cannot create FASTA", str(exc))
            return
        PreviewDialog(batch.fasta, self).exec()

    def _send_imgt(self) -> None:
        self._confirm_and_start_external("IMGT", IMGT_URL)

    def _send_arrest(self) -> None:
        self._confirm_and_start_external("ARResT", ARREST_URL)

    def _confirm_and_start_external(self, service: str, endpoint: str) -> None:
        if self._external_thread and self._external_thread.isRunning():
            QMessageBox.information(
                self, "Analysis in progress", "Wait for the ongoing analysis to finish."
            )
            return
        try:
            batch = self._ensure_external_batch()
        except ValueError as exc:
            QMessageBox.warning(self, "Cannot send", str(exc))
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
                "Cannot start external analysis",
                f"The local ID mapping could not be saved:\n{exc}",
            )
            return
        self.send_imgt_button.setEnabled(False)
        self.send_arrest_button.setEnabled(False)
        self.external_status.setText(
            f"Sending {len(batch.candidates)} pseudonymized sequences to {service} …"
        )
        self.external_progress.setVisible(True)
        self._set_status(f"{service} in progress", "busy")
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
                    raise TypeError("Unexpected IMGT result type")
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
                        else "unknown"
                    )
                    self._imgt_status_by_row[row_index] = status
                version = result.program_version or "unknown version"
                message = (
                    f"IMGT {version} completed for {len(result.records)} sequences. "
                    f"Result saved in {save_path.parent}."
                )
            else:
                if not isinstance(result, ArrestBatchResult):
                    raise TypeError("Unexpected ARResT result type")
                save_path = save_arrest_result(
                    self.result.manifest.run_directory, batch, result
                )
                apply_arrest_result(self.result.rows, batch, result)
                self.arrest_result = result
                for record in result.records:
                    row_index = batch.by_id()[record.external_id].row_index
                    status = record.subset or "unknown"
                    if record.confidence:
                        status += f" ({record.confidence})"
                    self._arrest_status_by_row[row_index] = status
                message = (
                    f"ARResT completed for {len(result.records)} sequences. "
                    f"Result saved in {save_path.parent}."
                )
        except (OSError, PrivacyError, TypeError, ValueError) as exc:
            self.external_status.setText(f"{service} result could not be saved: {exc}")
            QMessageBox.critical(self, f"{service} failed", str(exc))
            return
        self._refresh_external_table()
        self.external_status.setText(message)
        self._set_status(f"{service} completed", "success")

    def _generate_reports(self) -> None:
        if not self.result or not self.external_batch or not self.imgt_result:
            QMessageBox.warning(self, "Report", "IMGT must be completed first.")
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
            QMessageBox.critical(self, "Report failed", str(exc))
            return
        QMessageBox.information(
            self,
            "Reports created",
            f"Report drafts and audit data saved in:\n{directory}",
        )

    def _external_failed(self, service: str, message: str) -> None:
        self.external_status.setText(f"{service} failed: {message}")
        self._set_status(f"{service} failed", "error")
        QMessageBox.critical(self, f"{service} failed", message)

    def _external_finished(self) -> None:
        self.external_progress.setVisible(False)
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
                "Confirm sample count",
                "\n".join(self.result.manifest.warnings) + "\nDo you still want to export?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        output = Path(self.output_edit.text())
        overwrite = False
        if output.exists():
            answer = QMessageBox.question(
                self, "File exists", f"{output.name} already exists. Overwrite?"
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            overwrite = True
        try:
            written = self.service.export(
                self.result,
                output,
                overwrite=overwrite,
                highlight_functional_rows=self.highlight_excel_checkbox.isChecked(),
            )
        except (OSError, PrivacyError, FileExistsError) as exc:
            QMessageBox.critical(self, "Export failed", str(exc))
            return
        self._set_status("Exported", "success")
        QMessageBox.information(
            self,
            "Export completed",
            f"Wrote {len(self.result.rows)} rows to:\n{written}",
        )

    def _export_fasta(self) -> None:
        try:
            batch = self._ensure_external_batch()
        except ValueError as exc:
            QMessageBox.warning(self, "Cannot create FASTA", str(exc))
            return
        default = ""
        if self.result:
            default = str(self.result.manifest.run_directory / f"{self.result.manifest.run_date}_worklist.fasta")
        path, _ = QFileDialog.getSaveFileName(self, "Save local FASTA", default, "FASTA (*.fasta)")
        if not path:
            return
        output = Path(path)
        if output.exists():
            QMessageBox.warning(self, "File exists", "Choose a new filename; FASTA is not overwritten.")
            return
        try:
            ensure_outside_git(output)
        except PrivacyError as exc:
            QMessageBox.critical(self, "Invalid save location", str(exc))
            return
        output.write_text(
            batch.fasta,
            encoding="utf-8",
        )
        QMessageBox.information(
            self,
            "FASTA saved locally",
            f"Saved {len(batch.candidates)} pseudonymized sequences. "
            "No data sent externally.",
        )

    def closeEvent(self, event) -> None:
        if self._external_thread and self._external_thread.isRunning():
            QMessageBox.information(
                self,
                "Analysis in progress",
                "Wait for the external analysis to finish before closing the app.",
            )
            event.ignore()
            return
        super().closeEvent(event)

    def _save_settings(self) -> None:
        self.settings.setValue("defaultDataDirectory", self.default_data_edit.text())
        self.settings.setValue("expectedSamples", self.expected_spin.value())
        self.run_edit.setText(self.default_data_edit.text())
        QMessageBox.information(self, "Settings", "Local settings saved.")

    def _style(self) -> None:
        self.setStyleSheet(
            f"""
            QMainWindow {{ background: {Palette.app_bg}; }}
            QWidget {{
                color: {Palette.ink};
                font-family: "Segoe UI";
                font-size: 10pt;
            }}
            QWidget#AppRoot {{ background: {Palette.app_bg}; }}
            QWidget#ContentArea {{ background: {Palette.app_bg}; }}

            QFrame#Sidebar {{
                background: {Palette.panel};
                border-right: 1px solid {Palette.border};
            }}
            QLabel#SidebarBrandIcon {{
                background: {Palette.pale_blue};
                border: 1px solid #BFDBFE;
                border-radius: 8px;
            }}
            QLabel#SidebarAppTitle {{
                color: {Palette.navy};
                font-family: "Segoe UI";
                font-size: 16pt;
                font-weight: 700;
            }}
            QLabel#SidebarAppSubtitle {{
                color: {Palette.muted};
                font-size: 8pt;
                font-weight: 500;
            }}
            QPushButton#NavButton {{
                background: transparent;
                color: {Palette.ink};
                border: none;
                border-radius: 8px;
                padding: 12px 16px;
                text-align: left;
                font-weight: 600;
                font-size: 10pt;
            }}
            QPushButton#NavButton:hover {{
                background: {Palette.pale_blue};
                color: {Palette.blue};
            }}
            QPushButton#NavButton:checked {{
                background: {Palette.blue};
                color: white;
            }}
            QPushButton#NavButton:checked:hover {{
                background: {Palette.blue_hover};
            }}
            QLabel#SidebarStatusBadge {{
                background: {Palette.subtle};
                color: {Palette.navy};
                border: 1px solid {Palette.border};
                border-radius: 8px;
                padding: 6px 12px;
                font-weight: 700;
                font-size: 9pt;
            }}
            QLabel#SidebarStatusBadge[tone="busy"] {{
                background: {Palette.pale_blue}; color: {Palette.blue}; border-color: #BFDBFE;
            }}
            QLabel#SidebarStatusBadge[tone="success"] {{
                background: {Palette.pale_green}; color: {Palette.green}; border-color: #BBF7D0;
            }}
            QLabel#SidebarStatusBadge[tone="error"] {{
                background: {Palette.pale_red}; color: {Palette.red}; border-color: #FECACA;
            }}
            QLabel#SidebarVersion {{
                color: {Palette.muted};
                font-size: 8pt;
            }}

            QLabel#PrivacyBadge {{
                background: {Palette.pale_green};
                color: {Palette.green};
                border: 1px solid #BBF7D0;
                border-radius: 8px;
                padding: 6px 12px;
                font-size: 8pt;
                font-weight: 700;
            }}

            QFrame#MetricCard {{
                background: {Palette.panel};
                border: 1px solid {Palette.border};
                border-radius: 10px;
            }}

            QLabel#PageIntro, QLabel#InfoCallout, QLabel#PrivacyCallout,
            QLabel#StatusCallout {{
                border-radius: 8px;
                padding: 11px 13px;
            }}
            QLabel#PageIntro {{
                background: {Palette.pale_blue};
                color: {Palette.navy};
                border: 1px solid #BFDBFE;
                font-weight: 600;
            }}
            QLabel#InfoCallout, QLabel#StatusCallout {{
                background: {Palette.subtle};
                color: {Palette.muted};
                border: 1px solid {Palette.border};
            }}
            QLabel#PrivacyCallout {{
                background: {Palette.pale_green};
                color: #166534;
                border: 1px solid #BBF7D0;
                font-weight: 600;
            }}

            QGroupBox {{
                background: {Palette.panel};
                border: 1px solid {Palette.border};
                border-radius: 10px;
                margin-top: 12px;
                padding: 16px 14px 14px 14px;
                font-weight: 700;
                color: {Palette.navy};
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 6px;
                background: {Palette.panel};
            }}
            QFrame#ActionBar {{
                background: {Palette.subtle};
                border: 1px solid {Palette.border};
                border-radius: 9px;
            }}
            QLabel#ActionLabel {{
                color: {Palette.muted};
                font-size: 8pt;
                font-weight: 700;
            }}

            QLineEdit, QSpinBox, QPlainTextEdit {{
                background: {Palette.panel};
                color: {Palette.ink};
                border: 1px solid {Palette.border};
                border-radius: 7px;
                padding: 8px 10px;
                selection-background-color: {Palette.blue};
                min-height: 20px;
            }}
            QLineEdit:hover, QSpinBox:hover, QPlainTextEdit:hover {{ border-color: #94A3B8; }}
            QLineEdit:focus, QSpinBox:focus, QPlainTextEdit:focus {{
                border: 2px solid {Palette.blue};
                padding: 7px 9px;
            }}

            QPushButton {{
                background: {Palette.panel};
                color: {Palette.navy};
                border: 1px solid {Palette.border};
                border-radius: 7px;
                padding: 8px 13px;
                min-height: 20px;
                font-weight: 600;
            }}
            QPushButton:hover {{ background: {Palette.pale_blue}; border-color: #93C5FD; color: {Palette.blue_hover}; }}
            QPushButton:pressed {{ background: #DBEAFE; border-color: {Palette.blue}; }}
            QPushButton:focus {{ border: 2px solid {Palette.blue}; padding: 7px 12px; }}
            QPushButton#PrimaryButton {{
                background: {Palette.blue};
                color: white;
                border-color: {Palette.blue};
                font-weight: 700;
            }}
            QPushButton#PrimaryButton:hover {{ background: {Palette.blue_hover}; border-color: {Palette.blue_hover}; color: white; }}
            QPushButton#PrimaryButton:pressed {{ background: {Palette.navy}; }}
            QPushButton:disabled {{
                color: #94A3B8;
                background: #E2E8F0;
                border-color: #E2E8F0;
            }}

            QCheckBox {{ color: {Palette.ink}; spacing: 8px; padding: 4px 0; }}
            QCheckBox::indicator {{ width: 18px; height: 18px; }}
            QCheckBox::indicator:unchecked {{
                background: white; border: 1px solid #94A3B8; border-radius: 4px;
            }}
            QCheckBox::indicator:checked {{
                background: {Palette.blue}; border: 1px solid {Palette.blue}; border-radius: 4px;
            }}

            QTableWidget {{
                background: {Palette.panel};
                alternate-background-color: {Palette.app_bg};
                border: 1px solid {Palette.border};
                border-radius: 8px;
                gridline-color: transparent;
                selection-background-color: #DBEAFE;
                selection-color: {Palette.ink};
            }}
            QTableWidget:focus {{ border: 2px solid {Palette.blue}; }}
            QHeaderView::section {{
                background: {Palette.navy};
                color: white;
                padding: 8px 7px;
                border: 0;
                border-right: 1px solid #345575;
                font-weight: 700;
            }}
            QTableCornerButton::section {{ background: {Palette.navy}; border: 0; }}

            QStackedWidget#PageStack {{
                background: transparent;
                border: none;
            }}

            QProgressBar {{ background: #DBEAFE; border: 0; border-radius: 2px; }}
            QProgressBar::chunk {{ background: {Palette.blue}; border-radius: 2px; }}

            QLabel#FooterText {{
                color: {Palette.muted};
                font-size: 8pt;
            }}

            QToolTip {{
                background: {Palette.navy}; color: white; border: 0; padding: 6px;
            }}
            """
        )
