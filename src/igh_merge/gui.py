from __future__ import annotations

from functools import partial
from dataclasses import replace
from pathlib import Path

from PyQt6.QtCore import QObject, QSettings, QTemporaryDir, QThread, Qt, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QColor, QIcon
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
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
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
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
    sequence_sha256,
)
from .edge_cdp import (
    EdgeCdpError,
    EdgeCdpTimeout,
    capture_imgt_evidence,
    edge_cdp_available,
    submit_imgt_detailed,
)
from .candidates import analysis_candidate_indices, is_functional_group_candidate
from .excel import HEADERS
from .io import ValidationError
from .models import MergeResult, QcItem
from .privacy import PrivacyError, ensure_outside_git
from .reports import generate_clinical_report_package
from .analysis_jobs import AnalysisJobResult, run_analysis_job
from .evidence_ui import EvidenceWorker, EvidenceDialog
from .evidence import EvidenceManifest
from .service import MergeService


from .theme import Palette


APP_ICON_PATH = Path(__file__).resolve().parent / "assets" / "igh-merge-icon.ico"


def application_icon() -> QIcon:
    return QIcon(str(APP_ICON_PATH)) if APP_ICON_PATH.is_file() else QIcon()


class MetricCard(QFrame):
    def __init__(self, label: str, color: str):
        super().__init__()
        self.setObjectName("MetricCard")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 8, 16, 8)
        layout.setSpacing(12)
        self.setMinimumHeight(64)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        text_layout = QVBoxLayout()
        text_layout.setSpacing(2)
        eyebrow = QLabel(label)
        eyebrow.setObjectName("MetricLabel")
        self.value = QLabel("0")
        self.value.setObjectName("MetricValue")
        self.value.setStyleSheet(f"color: {color}")
        self.value.setAccessibleName(label)
        text_layout.addWidget(eyebrow)
        layout.addLayout(text_layout, 1)
        layout.addWidget(self.value)


class TableSection(QFrame):
    """Give a result table a stable heading and an actionable empty state."""

    def __init__(self, table: QTableWidget, title: str, empty_message: str, noun: str):
        super().__init__()
        self.setObjectName("TableSection")
        self.table = table
        self.empty_message = empty_message
        self.noun = noun
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        header = QHBoxLayout()
        heading = QLabel(title)
        heading.setObjectName("SectionTitle")
        self.summary = QLabel("Not validated")
        self.summary.setObjectName("SecondaryText")
        header.addWidget(heading)
        header.addStretch()
        header.addWidget(self.summary)
        layout.addLayout(header)
        self.stack = QStackedWidget()
        self.stack.addWidget(table)
        self.empty = QLabel(empty_message)
        self.empty.setObjectName("TableEmptyState")
        self.empty.setWordWrap(True)
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setAccessibleName(f"{title}: empty state")
        self.stack.addWidget(self.empty)
        self.stack.setMinimumHeight(140)
        layout.addWidget(self.stack, 1)
        table.model().rowsInserted.connect(self.refresh)
        table.model().rowsRemoved.connect(self.refresh)
        table.model().modelReset.connect(self.refresh)
        self.refresh()

    def refresh(self, *_args) -> None:
        total = self.table.rowCount()
        visible = sum(not self.table.isRowHidden(row) for row in range(total))
        self.summary.setText(
            f"{total} {self.noun}" if visible == total else f"{visible} of {total} {self.noun} shown"
        )
        self.empty.setText(
            "No candidates match these filters."
            if total and not visible else self.empty_message
        )
        self.stack.setCurrentWidget(self.table if visible else self.empty)


class PayloadDialog(QDialog):
    def __init__(self, service: str, endpoint: str, payload: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Confirm sending to {service}")
        self.resize(760, 620)
        layout = QVBoxLayout(self)
        description = QLabel(f"Recipient: {endpoint}")
        description.setWordWrap(True)
        layout.addWidget(description)
        if service == 'ARResT':
            sequences = sum(line.startswith('>') for line in payload.splitlines())
            groups = (sequences + 49) // 50
            layout.addWidget(QLabel(f'{sequences} sequences in {groups} group(s), up to 50 per group.'))
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
    progress = pyqtSignal(int, int)

    def __init__(self, service: str, batch: ExternalBatch):
        super().__init__()
        self.service = service
        self.batch = batch

    @pyqtSlot()
    def run(self) -> None:
        try:
            client = ImgtClient() if self.service == "IMGT" else ArrestClient()
            result = run_analysis_job(self.service, self.batch, client, self.progress.emit)
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
        sidebar.setFixedWidth(208)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(16, 24, 16, 16)
        sidebar_layout.setSpacing(8)

        # App brand in sidebar
        brand_container = QWidget()
        brand_layout = QHBoxLayout(brand_container)
        brand_layout.setContentsMargins(0, 0, 0, 24)
        brand_layout.setSpacing(8)
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

        navigation_label = QLabel("WORKSPACE")
        navigation_label.setObjectName("SidebarSectionLabel")
        sidebar_layout.addWidget(navigation_label)

        # Navigation labels and actions remain stable across the workflow.
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
            btn.setAccessibleName(label)
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
        self.status_badge.setWordWrap(True)
        self.status_badge.setMinimumHeight(36)
        self.status_badge.setAccessibleName("Application status")
        sidebar_layout.addWidget(self.status_badge)

        # Version info
        version_label = QLabel("IGHV  ·  v0.2.0")
        version_label.setObjectName("SidebarVersion")
        version_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sidebar_layout.addWidget(version_label)

        main_layout.addWidget(sidebar)

        # Main content area
        content = QWidget()
        content.setObjectName("ContentArea")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(24, 20, 24, 16)
        content_layout.setSpacing(16)

        # A persistent page title makes the current stage explicit.
        top_bar = QHBoxLayout()
        top_bar.setSpacing(16)
        title_column = QVBoxLayout()
        title_column.setSpacing(2)
        self.page_title = QLabel("Run")
        self.page_title.setObjectName("PageTitle")
        self.page_title.setAccessibleName("Current page")
        title_column.addWidget(self.page_title)
        top_bar.addLayout(title_column, 1)
        content_layout.addLayout(top_bar)

        # Metric cards
        cards = QHBoxLayout()
        cards.setSpacing(12)
        self.row_card = MetricCard("Merged rows", Palette.ink)
        self.control_card = MetricCard("Control errors", Palette.error)
        self.support_card = MetricCard("FR1 support", Palette.success)
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

        main_layout.addWidget(content, 1)
        self.setCentralWidget(root)

    def _run_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        group = QGroupBox("Run folder")
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
        self.run_edit.setPlaceholderText("Choose a folder with Leader and FR1 files")
        grid.addWidget(self.run_edit, 0, 0)
        grid.addWidget(browse, 0, 1)
        grid.addWidget(self.validate_button, 0, 2)
        grid.setColumnStretch(0, 1)
        layout.addWidget(group)

        self.file_table = QTableWidget(0, 5)
        self.file_table.setHorizontalHeaderLabels(["S-no.", "Sample", "Leader rows", "FR1 rows", "Status"])
        self._configure_table(self.file_table)
        self.file_table.setAccessibleName("Detected sample files")
        self.file_section = TableSection(
            self.file_table, "Detected samples",
            "Validate a run to load samples.",
            "samples",
        )
        layout.addWidget(self.file_section, 1)
        self.run_message = QLabel("No run validated.")
        self.run_message.setObjectName("InfoCallout")
        self.run_message.setWordWrap(True)
        layout.addWidget(self.run_message)
        return page

    def _controls_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        self.control_table = QTableWidget(0, 4)
        self.control_table.setHorizontalHeaderLabels(["Control", "Target", "Status", "Details"])
        self._configure_table(self.control_table)
        self.control_table.setAccessibleName("Run controls")
        self.control_section = TableSection(
            self.control_table, "Quality controls",
            "Validate a run to load controls.",
            "controls",
        )
        self.control_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        for column in range(3):
            self.control_table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.control_section, 1)
        return page

    def _external_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        filter_bar = QHBoxLayout()
        self.candidate_search = QLineEdit()
        self.candidate_search.setPlaceholderText('Search sample or target')
        self.candidate_search.setClearButtonEnabled(True)
        self.candidate_search.setAccessibleName('Search analysis candidates')
        self.target_filter = QComboBox()
        self.target_filter.addItems(['All targets', 'Leader', 'FR1'])
        self.target_filter.setAccessibleName('Filter target')
        self.target_filter.setMinimumWidth(128)
        self.target_filter.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.selection_count = QLabel('0 selected')
        self.selection_count.setObjectName("SelectionCount")
        self.selection_count.setAccessibleName("Selected analysis candidates")
        self.selection_count.setToolTip("The selection includes candidates hidden by the current filters.")
        self.select_candidates_button = QPushButton("Select reads ≥2.5 %")
        self.select_candidates_button.setEnabled(False)
        self.select_candidates_button.setToolTip("Select all rows meeting the analysis threshold, including rows hidden by filters.")
        self.select_candidates_button.clicked.connect(self._select_candidates)
        filter_bar.addWidget(self.candidate_search, 1)
        filter_bar.addWidget(self.target_filter)
        filter_bar.addWidget(self.selection_count)
        filter_bar.addWidget(self.select_candidates_button)
        layout.addLayout(filter_bar)
        self.candidate_search.textChanged.connect(self._filter_candidates)
        self.target_filter.currentTextChanged.connect(self._filter_candidates)
        self.candidate_table = QTableWidget(0, 11)
        self.candidate_table.itemChanged.connect(self._update_selection_count)
        self.candidate_table.setHorizontalHeaderLabels(
            [
                "Select",
                "External ID",
                "Molecule",
                "Sample",
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
        candidate_header.setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)
        candidate_header.setSectionResizeMode(10, QHeaderView.ResizeMode.Interactive)
        self.candidate_table.setColumnWidth(3, 164)
        self.candidate_table.setColumnWidth(10, 220)
        candidate_header.setMinimumSectionSize(54)
        candidate_header.setStretchLastSection(True)
        self.candidate_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.candidate_table.setAccessibleName("Leader and FR1 candidates for external analysis")
        self.candidate_section = TableSection(
            self.candidate_table, "Sequence candidates",
            "Validate a run to load sequences.",
            "candidates",
        )
        layout.addWidget(self.candidate_section, 1)

        # Separate sequence submission from the evidence and report workflow.
        action_groups = QHBoxLayout()
        action_groups.setSpacing(12)
        analysis_group = QGroupBox("Analysis")
        analysis_grid = QGridLayout(analysis_group)
        analysis_grid.setSpacing(8)
        self.preview_fasta_button = QPushButton("Preview FASTA")
        self.preview_fasta_button.setEnabled(False)
        self.preview_fasta_button.clicked.connect(self._preview_fasta)
        self.save_fasta_button = QPushButton("Save FASTA locally")
        self.save_fasta_button.setEnabled(False)
        self.save_fasta_button.clicked.connect(self._export_fasta)
        self.send_imgt_button = QPushButton("Send to IMGT")
        self.send_imgt_button.setObjectName("PrimaryButton")
        self.send_imgt_button.setEnabled(False)
        self.send_imgt_button.clicked.connect(self._send_imgt)
        self.send_arrest_button = QPushButton("Send to ARResT")
        self.send_arrest_button.setEnabled(False)
        self.send_arrest_button.clicked.connect(self._send_arrest)
        self.capture_button = QPushButton("Capture IMGT evidence (Edge)")
        self.capture_button.setToolTip(
            "Open Microsoft Edge with the IGHV profile and capture IMGT result-page "
            "screenshots (sections 1-6 and 9) for the selected sequences."
        )
        self.capture_button.setEnabled(False)
        self.capture_button.clicked.connect(self._capture_imgt_evidence)
        self.view_evidence_button = QPushButton('View evidence')
        self.view_evidence_button.setAccessibleName("View IMGT evidence")
        self.view_evidence_button.setEnabled(False)
        self.view_evidence_button.clicked.connect(self._view_evidence)
        self.evidence_manifest = None
        self.report_button = QPushButton("Report draft")
        self.report_button.setAccessibleName("Generate report draft")
        self.report_button.setToolTip("Generate Word and Excel reports per sample.")
        self.report_button.setEnabled(False)
        self.report_button.clicked.connect(self._generate_reports)
        analysis_grid.addWidget(self.preview_fasta_button, 0, 0)
        analysis_grid.addWidget(self.save_fasta_button, 0, 1)
        analysis_grid.addWidget(self.send_imgt_button, 1, 0)
        analysis_grid.addWidget(self.send_arrest_button, 1, 1)
        analysis_grid.setColumnStretch(0, 1)
        analysis_grid.setColumnStretch(1, 1)
        documentation_group = QGroupBox("Reports and images")
        documentation_grid = QGridLayout(documentation_group)
        documentation_grid.setSpacing(8)
        documentation_grid.addWidget(self.capture_button, 0, 0, 1, 2)
        documentation_grid.addWidget(self.view_evidence_button, 1, 0)
        documentation_grid.addWidget(self.report_button, 1, 1)
        documentation_grid.setColumnStretch(0, 1)
        documentation_grid.setColumnStretch(1, 1)
        action_groups.addWidget(analysis_group, 1)
        action_groups.addWidget(documentation_group, 1)
        layout.addLayout(action_groups)

        self.external_progress = QProgressBar()
        self.external_progress.setRange(0, 0)
        self.external_progress.setTextVisible(False)
        self.external_progress.setFixedHeight(4)
        self.external_progress.setVisible(False)
        self.external_progress.setAccessibleName("External analysis in progress")
        layout.addWidget(self.external_progress)

        self.external_status = QLabel("No analysis started.")
        self.external_status.setObjectName("StatusCallout")
        self.external_status.setWordWrap(True)
        layout.addWidget(self.external_status)
        return page

    def _export_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        excel_group = QGroupBox("Excel file")
        grid = QGridLayout(excel_group)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(12)
        self.output_edit = QLineEdit()
        self.output_edit.setClearButtonEnabled(True)
        self.output_edit.setAccessibleName("Filename for merged Excel")
        self.output_edit.setPlaceholderText("Select an .xlsx file")
        output_browse = QPushButton("Select file")
        output_browse.clicked.connect(self._browse_output)
        self.export_button = QPushButton("Export merged.xlsx")
        self.export_button.setObjectName("PrimaryButton")
        self.export_button.setEnabled(False)
        self.export_button.clicked.connect(self._export_excel)
        self.highlight_excel_checkbox = QCheckBox(
            "Highlight candidate rows in yellow"
        )
        self.highlight_excel_checkbox.setToolTip(
            f"Colors the same preliminary Leader candidates yellow across all {len(HEADERS)} columns."
        )
        grid.addWidget(QLabel("Output"), 0, 0)
        grid.addWidget(self.output_edit, 0, 1)
        grid.addWidget(output_browse, 0, 2)
        grid.setColumnStretch(1, 1)
        layout.addWidget(excel_group)
        formatting_group = QGroupBox("Formatting")
        formatting_layout = QVBoxLayout(formatting_group)
        formatting_layout.addWidget(self.highlight_excel_checkbox)
        layout.addWidget(formatting_group)
        export_row = QHBoxLayout()
        self.export_readiness = QLabel("Validate a run on the Run page before exporting.")
        self.export_readiness.setObjectName("SecondaryText")
        self.export_readiness.setWordWrap(True)
        export_row.addWidget(self.export_readiness, 1)
        export_row.addWidget(self.export_button)
        layout.addLayout(export_row)
        layout.addStretch()
        return page

    def _settings_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        group = QGroupBox("Defaults")
        form = QFormLayout(group)
        self.default_data_edit = QLineEdit(
            self.settings.value("defaultDataDirectory", str(Path.home() / "Documents" / "IGHV-data"))
        )
        self.default_data_edit.setClearButtonEnabled(True)
        self.default_data_edit.setAccessibleName("Default data folder")
        self.expected_spin = QSpinBox()
        self.expected_spin.setRange(1, 96)
        self.expected_spin.setValue(int(self.settings.value("expectedSamples", 24)))
        self.expected_spin.setAccessibleName("Expected samples per target")
        self.lymphotrack_version_edit = QLineEdit(self.settings.value("lymphotrackVersion", "2.4.6"))
        self.lymphotrack_version_edit.setAccessibleName("LymphoTrack version")
        self.lymphotrack_version_edit.setPlaceholderText("e.g. 2.4.6")
        self.lymphotrack_version_edit.setToolTip(
            "LymphoTrack version used for this run."
        )
        save = QPushButton("Save settings")
        save.setObjectName("PrimaryButton")
        save.setMinimumWidth(210)
        save.clicked.connect(self._save_settings)
        save_row = QHBoxLayout()
        save_row.addStretch()
        save_row.addWidget(save)
        form.addRow("Default data folder", self.default_data_edit)
        form.addRow("Expected samples per target", self.expected_spin)
        form.addRow("LymphoTrack version", self.lymphotrack_version_edit)
        form.addRow("", save_row)
        layout.addWidget(group)

        rules = QGroupBox("Control limits (write-protected)")
        rules_layout = QVBoxLayout(rules)
        rules_text = QLabel(
                "IGH-PK ≥2.5 % | IGH-SHM ≥2.5 % and mutation ≥2.0 % | "
                "NGS NEG <1.0 % | NTC <10 000 reads"
        )
        rules_text.setWordWrap(True)
        rules_layout.addWidget(rules_text)
        layout.addWidget(rules)
        layout.addStretch()
        return page

    def _configure_table(self, table: QTableWidget) -> None:
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        table.horizontalHeader().setMinimumHeight(34)
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(30)
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
        self.page_title.setText(self.nav_buttons[index].text())
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
        if self._external_thread and self._external_thread.isRunning():
            QMessageBox.information(
                self, "Analysis in progress", "Wait for the ongoing analysis to finish."
            )
            return
        self._set_status("Validating …", "busy")
        self.validate_button.setEnabled(False)
        self.validate_button.setText("Validating …")
        QApplication.processEvents()
        self.external_batch = None
        self.imgt_result = None
        self.arrest_result = None
        self._imgt_status_by_row.clear()
        self._arrest_status_by_row.clear()
        self.capture_button.setEnabled(False)
        self.report_button.setEnabled(False)
        self.view_evidence_button.setEnabled(False)
        self.evidence_manifest = None
        try:
            self.result = self.service.process(Path(self.run_edit.text()), self.expected_spin.value())
        except (ValidationError, OSError) as exc:
            self.result = None
            self._clear_result_views()
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

    def _clear_result_views(self) -> None:
        """Discard visual results when the newly requested run cannot be validated."""
        for table in (self.file_table, self.control_table, self.candidate_table):
            table.setRowCount(0)
        for card in (self.row_card, self.control_card, self.support_card):
            card.value.setText("0")
        self._update_selection_count()
        self.external_status.setText("No validated run is loaded. Validate a run before analysis.")
        self.run_message.setText("Validation failed. Check the folder and validate the run again.")
        self.export_readiness.setText("Validate a run on the Run page before exporting.")
        for button in (self.select_candidates_button, self.preview_fasta_button, self.save_fasta_button):
            button.setEnabled(False)

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
        self.capture_button.setEnabled(True)
        for button in (self.select_candidates_button, self.preview_fasta_button, self.save_fasta_button):
            button.setEnabled(True)
        self.export_readiness.setText(
            f"{len(self.result.rows)} merged rows ready. Review controls before exporting."
        )
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
                    cell.setBackground(QColor(Palette.pale_error))
                else:
                    cell.setBackground(QColor(Palette.pale_success))
                self.control_table.setItem(row, column, cell)

    def _fill_candidates(self) -> None:
        assert self.result is not None
        self.candidate_table.setRowCount(0)
        for result_index, item in enumerate(self.result.rows):
            row = self.candidate_table.rowCount()
            self.candidate_table.insertRow(row)
            check = QTableWidgetItem()
            check.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            is_functional_group = self._is_functional_group_candidate(result_index)
            check.setCheckState(
                Qt.CheckState.Checked
                if result_index in analysis_candidate_indices(self.result.rows)
                else Qt.CheckState.Unchecked
            )
            check.setData(Qt.ItemDataRole.UserRole, result_index)
            self.candidate_table.setItem(row, 0, check)
            values = [
                "",
                item.molecule_type,
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
            font = self.candidate_table.item(row, 6).font()
            font.setBold(item.source.percent_total_reads >= 2.5)
            self.candidate_table.item(row, 6).setFont(font)
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
            self.candidate_table.item(row, 3).setToolTip(item.sample)
        self._filter_candidates()
        self._update_selection_count()

    def _filter_candidates(self) -> None:
        query = self.candidate_search.text().casefold().strip()
        target = self.target_filter.currentText()
        for row in range(self.candidate_table.rowCount()):
            sample_cell = self.candidate_table.item(row, 3)
            target_cell = self.candidate_table.item(row, 4)
            if sample_cell and target_cell:
                matches = query in (sample_cell.text() + ' ' + target_cell.text()).casefold()
                self.candidate_table.setRowHidden(row, not matches or (target != 'All targets' and target_cell.text() != target))
        self.candidate_section.refresh()

    def _update_selection_count(self) -> None:
        count = sum(self.candidate_table.item(row, 0) is not None and
                    self.candidate_table.item(row, 0).checkState() == Qt.CheckState.Checked
                    for row in range(self.candidate_table.rowCount()))
        self.selection_count.setText(f'{count} selected / {self.candidate_table.rowCount()}')

    def _select_candidates(self) -> None:
        for row in range(self.candidate_table.rowCount()):
            result_index = int(
                self.candidate_table.item(row, 0).data(Qt.ItemDataRole.UserRole)
            )
            self.candidate_table.item(row, 0).setCheckState(
                Qt.CheckState.Checked
                if self.result and result_index in analysis_candidate_indices(self.result.rows)
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
        if self._external_thread and self._external_thread.isRunning():
            raise ValueError("External analysis in progress; wait before changing selection")
        if not self.result:
            raise ValueError("Validate a run before selecting sequences")
        selected = self._selected_result_indices()
        if not selected:
            raise ValueError("Select at least one sequence")
        if (
            self.external_batch is not None
            and tuple(item.row_index for item in self.external_batch.candidates) == selected
            and all(candidate.sequence_sha256 == sequence_sha256(self.result.rows[candidate.row_index].source.sequence)
                    and candidate.molecule_type == self.result.rows[candidate.row_index].molecule_type
                    and candidate.target == self.result.rows[candidate.row_index].target
                    and candidate.rank == self.result.rows[candidate.row_index].source.rank
                    and candidate.sample == self.result.rows[candidate.row_index].sample
                    for candidate in self.external_batch.candidates)
        ):
            return self.external_batch
        self.external_batch = create_external_batch(
            self.result.manifest.run_date,
            [(index, self.result.rows[index]) for index in selected],
        )
        self.imgt_result = None
        self.arrest_result = None
        self.report_button.setEnabled(False)
        self.capture_button.setEnabled(bool(self.result))
        self.view_evidence_button.setEnabled(False)
        self.evidence_manifest = None
        self._imgt_status_by_row.clear()
        self._arrest_status_by_row.clear()
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
        if service == 'ARResT' and self.arrest_result:
            completed = {record.external_id for record in self.arrest_result.records}
            batch = replace(batch, candidates=tuple(
                candidate for candidate in batch.candidates if candidate.external_id not in completed
            ))
            if not batch.candidates:
                QMessageBox.information(self, 'ARResT complete',
                                        'All selected sequences already have an ARResT result.')
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
        self.validate_button.setEnabled(False)
        self.capture_button.setEnabled(False)
        self.report_button.setEnabled(False)
        self.candidate_table.setEnabled(False)
        self.select_candidates_button.setEnabled(False)
        self.external_status.setText(
            f"Sending {len(batch.candidates)} pseudonymized sequences to {service} …"
        )
        self.external_progress.setVisible(True)
        self.external_progress.setRange(0, 0)
        self.external_progress.setFormat('Analyzing groups …')
        self._set_status(f"{service} in progress", "busy")
        thread = QThread(self)
        worker = ExternalWorker(service, batch)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.succeeded.connect(partial(self._external_succeeded, service, batch))
        worker.failed.connect(partial(self._external_failed, service))
        worker.progress.connect(self._external_progressed)
        worker.succeeded.connect(thread.quit)
        worker.failed.connect(thread.quit)
        worker.succeeded.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        thread.finished.connect(self._external_finished)
        self._external_thread = thread
        self._external_worker = worker
        thread.start()

    @pyqtSlot(int, int)
    def _external_progressed(self, completed: int, total: int) -> None:
        self.external_progress.setRange(0, total)
        self.external_progress.setValue(completed)
        self.external_progress.setFormat(f'Groups completed: {completed} / {total}')

    def _external_succeeded(
        self,
        service: str,
        batch: ExternalBatch,
        result: object,
    ) -> bool:
        if not self.result:
            return
        if isinstance(result, AnalysisJobResult):
            previous_arrest = self.arrest_result
            accepted = []
            errors = dict(result.errors)
            for part, part_result in result.parts:
                if self._external_succeeded(service, part, part_result):
                    accepted.append((part, part_result))
                else:
                    errors.update({c.external_id: 'Local result could not be saved/applied' for c in part.candidates})
            statuses = self._imgt_status_by_row if service == "IMGT" else self._arrest_status_by_row
            for external_id, error in errors.items():
                statuses[batch.by_id()[external_id].row_index] = f"Failed: {error}"
            if service == "IMGT":
                records = tuple(record for _, part in accepted for record in part.records)
                first = accepted[0][1] if accepted else None
                self.imgt_result = ImgtBatchResult(first.parameters, records, '', '') if first else None
                self.capture_button.setEnabled(bool(records))
                self.report_button.setEnabled(not errors and bool(records))
            else:
                selected_ids = set((self.external_batch or batch).candidate_ids)
                merged_records = {record.external_id: record for record in previous_arrest.records
                                  if record.external_id in selected_ids} if previous_arrest else {}
                merged_records.update({record.external_id: record
                                       for _, part in accepted for record in part.records})
                records = tuple(merged_records.values())
                self.arrest_result = ArrestBatchResult(records, '', '') if records else None
                self.report_button.setEnabled(self._has_complete_imgt())
            self._refresh_external_table()
            self.external_status.setText(f"{service}: {len(records)} completed, {len(errors)} failed")
            self._set_status(f"{service} partial failure" if errors else f"{service} completed",
                             "error" if errors else "success")
            return not errors
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
                self.capture_button.setEnabled(True)
                for record in result.records:
                    row_index = batch.by_id()[record.external_id].row_index
                    status = (
                        "productive"
                        if record.productive is True
                        else "not productive"
                        if record.productive is False
                        else "unknown"
                    )
                    if record.selected_identity_percent is not None:
                        status += f"; {record.selected_identity_percent:g}%"
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
            return False
        self._refresh_external_table()
        self.external_status.setText(message)
        self._set_status(f"{service} completed", "success")
        return True

    def _has_complete_imgt(self) -> bool:
        return bool(self.imgt_result and self.external_batch and
                    set(record.external_id for record in self.imgt_result.records) == set(self.external_batch.candidate_ids))

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
                evidence=self.evidence_manifest,
                lymphotrack_version=self.lymphotrack_version_edit.text().strip(),
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
        self.validate_button.setEnabled(True)
        self.candidate_table.setEnabled(True)
        self.select_candidates_button.setEnabled(True)
        self.capture_button.setEnabled(bool(self.result))
        self.report_button.setEnabled(self._has_complete_imgt())
        if self._external_thread:
            self._external_thread.deleteLater()
        self._external_worker = None
        self._external_thread = None

    def _capture_imgt_evidence(self) -> None:
        if self._external_thread and self._external_thread.isRunning():
            return
        if not self.result:
            return
        try:
            batch = self._ensure_external_batch()
        except ValueError as exc:
            QMessageBox.warning(self, 'IMGT evidence', str(exc))
            return
        if not edge_cdp_available():
            QMessageBox.critical(self, 'IMGT evidence', 'Microsoft Edge is not available.')
            return
        if PayloadDialog('IMGT Detailed evidence', IMGT_URL, batch.fasta, self).exec() != QDialog.DialogCode.Accepted:
            return
        from datetime import datetime, timezone
        directory = (self.result.manifest.run_directory / f'{self.external_batch.run_date}_imgt_evidence'
                     / self.external_batch.session_id / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
        try:
            ensure_outside_git(directory)
            save_batch_mapping(self.result.manifest.run_directory, self.external_batch)
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, 'IMGT evidence', str(exc))
            return
        for control in (self.send_imgt_button, self.send_arrest_button, self.validate_button,
                        self.candidate_table, self.select_candidates_button, self.capture_button, self.report_button):
            control.setEnabled(False)
        self.external_progress.setVisible(True)
        self._set_status('IMGT evidence in progress', 'busy')
        thread = QThread(self)
        worker = EvidenceWorker(self.external_batch, directory)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self.external_status.setText)
        worker.succeeded.connect(self._evidence_succeeded)
        worker.failed.connect(partial(self._external_failed, 'IMGT evidence'))
        worker.succeeded.connect(thread.quit)
        worker.failed.connect(thread.quit)
        worker.succeeded.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        thread.finished.connect(self._external_finished)
        self._external_thread, self._external_worker = thread, worker
        thread.start()

    def _evidence_succeeded(self, result) -> None:
        manifest, errors = result
        self.evidence_manifest = manifest
        self.view_evidence_button.setEnabled(bool(manifest.entries))
        self.report_button.setEnabled(bool(self.imgt_result and self.external_batch and
            set(r.external_id for r in self.imgt_result.records) == set(self.external_batch.candidate_ids)))
        self.external_status.setText(f'IMGT evidence: {len(manifest.entries)} captured; {len(errors)} failed. '
                                     + '; '.join(f'{key}: {value}' for key, value in errors.items()))
        self._set_status('IMGT evidence partial failure' if errors else 'IMGT evidence captured',
                         'error' if errors else 'success')

    def _view_evidence(self) -> None:
        if self.evidence_manifest and self.evidence_manifest.entries:
            EvidenceDialog(self.evidence_manifest, self).exec()

    def _molecule_for(self, external_id: str) -> str:
        if not self.external_batch:
            return "gDNA"
        for candidate in self.external_batch.candidates:
            if candidate.external_id == external_id:
                return candidate.molecule_type
        return "gDNA"

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
                7: self._imgt_status_by_row.get(result_index, ""),
                8: self._arrest_status_by_row.get(result_index, ""),
                9: self.result.rows[result_index].subset,
                10: self.result.rows[result_index].comment,
            }
            for column, value in values.items():
                self.candidate_table.item(table_row, column).setText(value)
            comment_cell = self.candidate_table.item(table_row, 10)
            comment_cell.setForeground(QColor(Palette.error if 'IGHJ5*03: pseudogene' in comment_cell.text() else Palette.ink))
            comment_cell.setToolTip(comment_cell.text())

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
        self.settings.setValue("lymphotrackVersion", self.lymphotrack_version_edit.text().strip())
        self.run_edit.setText(self.default_data_edit.text())
        QMessageBox.information(self, "Settings", "Local settings saved.")

    def _style(self) -> None:
        # Qt stylesheets replace the platform arrow renderer. Keep small vector
        # arrows available for the lifetime of this window, including offscreen QA.
        self._control_icons = QTemporaryDir()
        arrow_directory = Path(self._control_icons.path()) if self._control_icons.isValid() else None
        for name, points in (("down", "1,1 5,5 9,1"), ("up", "1,5 5,1 9,5")):
            if arrow_directory is None:
                break
            (arrow_directory / f"{name}.svg").write_text(
                f'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="6" viewBox="0 0 10 6">'
                f'<polyline points="{points}" fill="none" stroke="{Palette.ink}" stroke-width="1.5" '
                'stroke-linecap="round" stroke-linejoin="round"/></svg>',
                encoding="utf-8",
            )
        down_arrow = (arrow_directory / "down.svg").as_posix() if arrow_directory else ""
        up_arrow = (arrow_directory / "up.svg").as_posix() if arrow_directory else ""
        self.setStyleSheet(
            f"""
            QMainWindow, QDialog {{ background: {Palette.app_bg}; }}
            QWidget {{ color: {Palette.ink}; font-family: "Segoe UI"; font-size: 10pt; }}
            QWidget#AppRoot, QWidget#ContentArea {{ background: {Palette.app_bg}; }}
            QFrame#Sidebar {{ background: {Palette.sidebar}; border: 0; }}
            QLabel#SidebarBrandIcon {{ background: {Palette.panel}; border-radius: 8px; }}
            QLabel#SidebarAppTitle {{ color: {Palette.sidebar_text}; font-size: 18pt; font-weight: 700; }}
            QLabel#SidebarAppSubtitle {{ color: {Palette.sidebar_muted}; font-size: 8pt; }}
            QLabel#SidebarSectionLabel {{ color: {Palette.sidebar_muted}; font-size: 8pt; font-weight: 600; padding: 0 8px 4px; }}
            QPushButton#NavButton {{
                background: transparent; color: {Palette.sidebar_text}; border: 2px solid transparent;
                border-radius: 6px; padding: 10px 12px; text-align: left; font-weight: 600;
            }}
            QPushButton#NavButton:hover {{ background: {Palette.sidebar_hover}; }}
            QPushButton#NavButton:checked {{ background: {Palette.accent}; color: white; }}
            QPushButton#NavButton:checked:hover {{ background: {Palette.accent_hover}; }}
            QPushButton#NavButton:focus {{ border-color: {Palette.sidebar_muted}; }}
            QLabel#SidebarStatusBadge {{
                background: {Palette.sidebar_hover}; color: {Palette.sidebar_text};
                border: 1px solid {Palette.sidebar_hover}; border-radius: 6px;
                padding: 6px 8px; font-weight: 600; font-size: 9pt;
            }}
            QLabel#SidebarStatusBadge[tone="busy"] {{ background: {Palette.accent_soft}; color: {Palette.accent_hover}; }}
            QLabel#SidebarStatusBadge[tone="success"] {{ background: {Palette.pale_success}; color: {Palette.success}; }}
            QLabel#SidebarStatusBadge[tone="error"] {{ background: {Palette.pale_error}; color: {Palette.error}; }}
            QLabel#SidebarVersion {{ color: {Palette.sidebar_muted}; font-size: 8pt; padding-top: 4px; }}
            QLabel#PageTitle {{ color: {Palette.ink}; font-size: 22pt; font-weight: 700; }}
            QFrame#MetricCard {{ background: {Palette.panel}; border: 1px solid {Palette.border}; border-radius: 6px; }}
            QLabel#MetricLabel {{ color: {Palette.ink}; font-size: 9pt; font-weight: 600; }}
            QLabel#MetricValue {{ font-size: 22pt; font-weight: 600; }}
            QLabel#SectionTitle {{ color: {Palette.ink}; font-size: 10pt; font-weight: 600; }}
            QLabel#SecondaryText {{ color: {Palette.muted}; font-size: 9pt; }}
            QLabel#SelectionCount {{ color: {Palette.accent_hover}; font-size: 9pt; font-weight: 600; padding: 0 4px; }}
            QLabel#InfoCallout, QLabel#StatusCallout {{
                border-radius: 4px; padding: 8px 10px; font-size: 9pt;
            }}
            QLabel#InfoCallout, QLabel#StatusCallout {{
                background: {Palette.subtle}; color: {Palette.muted}; border: 1px solid {Palette.border};
            }}
            QLabel#TableEmptyState {{
                background: {Palette.panel}; color: {Palette.muted}; border: 1px solid {Palette.border};
                border-radius: 6px; padding: 24px; font-size: 10pt;
            }}
            QGroupBox {{
                background: {Palette.panel}; color: {Palette.ink}; border: 1px solid {Palette.border};
                border-radius: 6px; margin-top: 10px; padding: 12px 10px 10px; font-weight: 600;
            }}
            QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; background: {Palette.app_bg}; }}
            QLineEdit, QSpinBox, QPlainTextEdit, QComboBox {{
                background: {Palette.panel}; color: {Palette.ink}; border: 1px solid {Palette.border_strong};
                border-radius: 4px; padding: 6px 8px; min-height: 20px;
                selection-background-color: {Palette.accent}; selection-color: white;
            }}
            QLineEdit:hover, QSpinBox:hover, QPlainTextEdit:hover, QComboBox:hover {{ border-color: {Palette.accent}; }}
            QLineEdit:focus, QSpinBox:focus, QPlainTextEdit:focus, QComboBox:focus {{
                border: 2px solid {Palette.accent}; padding: 5px 7px;
            }}
            QComboBox {{ padding-right: 24px; }}
            QComboBox:focus {{ padding-right: 23px; }}
            QComboBox::drop-down {{ width: 22px; border: 0; }}
            QComboBox::down-arrow {{ image: url("{down_arrow}"); width: 10px; height: 6px; }}
            QSpinBox {{ padding-right: 24px; }}
            QSpinBox:focus {{ padding-right: 23px; }}
            QSpinBox::up-button {{ subcontrol-origin: border; subcontrol-position: top right; width: 20px; border: 0; }}
            QSpinBox::down-button {{ subcontrol-origin: border; subcontrol-position: bottom right; width: 20px; border: 0; }}
            QSpinBox::up-arrow {{ image: url("{up_arrow}"); width: 10px; height: 6px; }}
            QSpinBox::down-arrow {{ image: url("{down_arrow}"); width: 10px; height: 6px; }}
            QComboBox QAbstractItemView {{
                background: {Palette.panel}; color: {Palette.ink}; border: 1px solid {Palette.border_strong};
                selection-background-color: {Palette.accent_soft}; selection-color: {Palette.ink};
            }}
            QPushButton {{
                background: {Palette.panel}; color: {Palette.ink}; border: 1px solid {Palette.border_strong};
                border-radius: 4px; padding: 6px 10px; min-height: 20px; font-weight: 600; font-size: 9pt;
            }}
            QPushButton:hover {{ background: {Palette.pale_accent}; border-color: {Palette.accent}; color: {Palette.accent_hover}; }}
            QPushButton:pressed {{ background: {Palette.accent_soft}; border-color: {Palette.accent}; }}
            QPushButton:focus {{ border: 2px solid {Palette.accent}; padding: 5px 9px; }}
            QPushButton#PrimaryButton {{ background: {Palette.accent}; color: white; border-color: {Palette.accent}; }}
            QPushButton#PrimaryButton:hover, QPushButton#PrimaryButton:pressed {{ background: {Palette.accent_hover}; color: white; }}
            QPushButton#PrimaryButton:focus {{ border-color: {Palette.ink}; }}
            QPushButton:disabled {{ color: {Palette.disabled_text}; background: {Palette.disabled_bg}; border-color: {Palette.border}; }}
            QLineEdit:disabled, QSpinBox:disabled, QComboBox:disabled {{ color: {Palette.disabled_text}; background: {Palette.disabled_bg}; }}
            QCheckBox {{ color: {Palette.ink}; spacing: 8px; padding: 4px; border: 2px solid transparent; }}
            QCheckBox:focus {{ border-color: {Palette.accent}; border-radius: 4px; }}
            QCheckBox::indicator {{ width: 18px; height: 18px; }}
            QTableWidget {{
                background: {Palette.panel}; alternate-background-color: {Palette.app_bg};
                border: 1px solid {Palette.border}; border-radius: 4px; gridline-color: transparent;
                selection-background-color: {Palette.accent_soft}; selection-color: {Palette.ink};
            }}
            QTableWidget:focus {{ border: 2px solid {Palette.accent}; }}
            QTableWidget::item {{ padding: 3px 6px; }}
            QHeaderView::section {{
                background: {Palette.subtle}; color: {Palette.ink}; padding: 7px 6px;
                border: 0; border-bottom: 1px solid {Palette.border}; border-right: 1px solid {Palette.border};
                font-size: 9pt; font-weight: 600;
            }}
            QTableCornerButton::section {{ background: {Palette.subtle}; border: 0; }}
            QStackedWidget#PageStack {{ background: transparent; border: 0; }}
            QTabWidget::pane {{ border: 1px solid {Palette.border}; background: {Palette.panel}; border-radius: 4px; }}
            QTabBar::tab {{ background: {Palette.subtle}; color: {Palette.muted}; border: 1px solid {Palette.border}; padding: 8px 16px; }}
            QTabBar::tab:selected {{ background: {Palette.panel}; color: {Palette.accent_hover}; border-bottom: 2px solid {Palette.accent}; }}
            QTabBar::tab:focus {{ border-color: {Palette.accent}; }}
            QProgressBar {{ background: {Palette.accent_soft}; border: 0; border-radius: 2px; }}
            QProgressBar::chunk {{ background: {Palette.accent}; border-radius: 2px; }}
            QScrollArea {{ background: {Palette.panel}; border: 1px solid {Palette.border}; border-radius: 4px; }}
            QLabel#EvidenceImage {{ background: {Palette.panel}; color: {Palette.muted}; }}
            QScrollBar:vertical {{ background: {Palette.subtle}; width: 12px; margin: 0; }}
            QScrollBar:horizontal {{ background: {Palette.subtle}; height: 12px; margin: 0; }}
            QScrollBar::handle {{ background: {Palette.border_strong}; border-radius: 4px; min-height: 24px; min-width: 24px; }}
            QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
            QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
            QToolTip {{ background: {Palette.sidebar}; color: {Palette.sidebar_text}; border: 0; padding: 6px; }}
            """
        )
