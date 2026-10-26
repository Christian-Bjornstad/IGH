from pathlib import Path

from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot, Qt, QUrl
from PyQt6.QtGui import QPixmap, QDesktopServices
from PyQt6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QPlainTextEdit,
    QPushButton, QScrollArea, QTabWidget, QVBoxLayout, QWidget,
)

from .edge_cdp import launch_edge, submit_imgt_detailed, capture_imgt_evidence, extract_imgt_text
from .evidence import EvidenceManifest, save_evidence_manifest, verify_imgt_page
from .privacy import ensure_outside_git


class EvidenceWorker(QObject):
    succeeded = pyqtSignal(object)
    failed = pyqtSignal(str)
    progress = pyqtSignal(str)

    def __init__(self, batch, directory):
        super().__init__()
        self.batch, self.directory = batch, Path(directory)

    @pyqtSlot()
    def run(self):
        entries, errors = [], {}
        try:
            ensure_outside_git(self.directory)
            with launch_edge(self.directory / 'edge-profile', background=False) as session:
                for index, candidate in enumerate(self.batch.candidates):
                    self.progress.emit(f'IMGT evidence {index + 1}/{len(self.batch.candidates)}: {candidate.external_id}')
                    directory = self.directory / candidate.external_id
                    try:
                        submit_imgt_detailed(session.page, external_id=candidate.external_id,
                                             sequence=candidate.sequence, molecule_type=candidate.molecule_type)
                        verify_imgt_page(session.page, candidate)
                        sections = extract_imgt_text(session.page)
                        directory.mkdir(parents=True, exist_ok=True)
                        try:
                            images = capture_imgt_evidence(session.page, directory)
                        except Exception:
                            # Keep verified text and already captured crops even if
                            # a later optional region or browser call fails.
                            save_evidence_manifest(directory, self.batch, candidate, sections,
                                tuple(directory.glob('*.png')), parameters={'moleculeType': candidate.molecule_type})
                            raise
                        manifest = save_evidence_manifest(directory, self.batch, candidate, sections, images,
                            parameters={'species': 'human', 'receptorOrLocusType': 'IGH',
                                        'moleculeType': candidate.molecule_type, 'resultType': 'detailed',
                                        'V_REGIONsearchIndel': 'true'})
                        entries.extend(manifest.entries)
                    except Exception as exc:
                        errors[candidate.external_id] = str(exc)
                self.succeeded.emit((EvidenceManifest(tuple(entries)), errors))
        except Exception as exc:
            self.failed.emit(str(exc))


class EvidenceDialog(QDialog):
    def __init__(self, manifest, parent=None):
        super().__init__(parent)
        self.setWindowTitle('IMGT evidence')
        self.resize(900, 750)
        self.setMinimumSize(660, 480)
        self.manifest = manifest
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 16)
        layout.setSpacing(12)
        title = QLabel('IMGT evidence')
        title.setObjectName('PageTitle')
        layout.addWidget(title)
        candidate_row = QHBoxLayout()
        candidate_label = QLabel('Sequence')
        self.candidate = QComboBox()
        self.candidate.setAccessibleName('Evidence sequence')
        candidate_label.setBuddy(self.candidate)
        self.candidate.addItems([entry.external_id for entry in manifest.entries])
        candidate_row.addWidget(candidate_label)
        candidate_row.addWidget(self.candidate, 1)
        self.capture_details = QLabel()
        self.capture_details.setObjectName('SecondaryText')
        candidate_row.addWidget(self.capture_details)
        layout.addLayout(candidate_row)
        self.image_choice = QComboBox()
        self.image_choice.setAccessibleName('Captured IMGT section')
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setAccessibleName('IMGT result summary and missing sections')
        self.text.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.image = QLabel()
        self.image.setObjectName('EvidenceImage')
        self.image.setAccessibleName('Captured IMGT evidence image')
        self.image.setWordWrap(True)
        self.image.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        scroll = QScrollArea()
        scroll.setAccessibleName('Evidence image viewer')
        scroll.setWidget(self.image)
        scroll.setWidgetResizable(True)
        tabs = QTabWidget()
        tabs.addTab(self.text, 'Result summary')
        image_page = QWidget()
        image_layout = QVBoxLayout(image_page)
        image_layout.setContentsMargins(0, 12, 0, 0)
        image_layout.addWidget(self.image_choice)
        image_layout.addWidget(scroll, 1)
        tabs.addTab(image_page, 'Captured sections')
        layout.addWidget(tabs, 1)
        self.folder = QPushButton('Open evidence folder')
        footer = QHBoxLayout()
        footer.addWidget(self.folder)
        footer.addStretch()
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        footer.addWidget(buttons)
        layout.addLayout(footer)
        self.candidate.currentIndexChanged.connect(self._select_entry)
        self.image_choice.currentIndexChanged.connect(self._select_image)
        self.folder.clicked.connect(self._open_folder)
        self._select_entry()

    def _select_entry(self):
        index = self.candidate.currentIndex()
        if index < 0:
            self.text.setPlainText('No evidence has been captured. Return to IMGT & ARResT and capture evidence for selected sequences.')
            self.folder.setEnabled(False)
            self.image_choice.setEnabled(False)
            self.capture_details.clear()
            self._select_image()
            return
        entry = self.manifest.entries[index]
        self.text.setPlainText(entry.sections.get('00_summary', '') + '\n\n' +
                              '\n'.join(f'{key}: {reason}' for key, reason in entry.missing_sections.items()))
        self.capture_details.setText(f'{len(entry.images)} sections captured')
        self.folder.setEnabled(bool(entry.images))
        self.image_choice.setEnabled(bool(entry.images))
        self.image_choice.blockSignals(True)
        self.image_choice.clear()
        for path in entry.images:
            self.image_choice.addItem(Path(path).stem, path)
        self.image_choice.blockSignals(False)
        self._select_image()

    def _select_image(self):
        path = self.image_choice.currentData()
        if path:
            pixmap = QPixmap(path)
            self.image.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
            self.image.setMargin(0)
            self.image.setPixmap(pixmap)
            if pixmap.isNull():
                self.image.setAlignment(Qt.AlignmentFlag.AlignCenter)
                self.image.setMargin(24)
                self.image.setText('The captured image could not be opened. Check the evidence folder.')
        else:
            self.image.setPixmap(QPixmap())
            self.image.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.image.setMargin(24)
            self.image.setText('No captured image is available for this sequence.')

    def _open_folder(self):
        if self.candidate.currentIndex() < 0:
            return
        entry = self.manifest.entries[self.candidate.currentIndex()]
        if entry.images:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(entry.images[0]).parent)))
