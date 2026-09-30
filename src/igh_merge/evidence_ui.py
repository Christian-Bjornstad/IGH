from pathlib import Path

from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot, Qt, QUrl
from PyQt6.QtGui import QPixmap, QDesktopServices
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QComboBox, QPlainTextEdit, QLabel, QPushButton, QScrollArea

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
        self.manifest = manifest
        layout = QVBoxLayout(self)
        self.candidate = QComboBox()
        self.candidate.addItems([entry.external_id for entry in manifest.entries])
        self.image_choice = QComboBox()
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.image = QLabel()
        self.image.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll = QScrollArea()
        scroll.setWidget(self.image)
        scroll.setWidgetResizable(True)
        self.folder = QPushButton('Open evidence folder')
        for widget in (self.candidate, self.text, self.image_choice, scroll, self.folder):
            layout.addWidget(widget)
        self.candidate.currentIndexChanged.connect(self._select_entry)
        self.image_choice.currentIndexChanged.connect(self._select_image)
        self.folder.clicked.connect(self._open_folder)
        self._select_entry()

    def _select_entry(self):
        entry = self.manifest.entries[self.candidate.currentIndex()]
        self.text.setPlainText(entry.sections.get('00_summary', '') + '\n\n' +
                              '\n'.join(f'{key}: {reason}' for key, reason in entry.missing_sections.items()))
        self.image_choice.clear()
        for path in entry.images:
            self.image_choice.addItem(Path(path).stem, path)

    def _select_image(self):
        path = self.image_choice.currentData()
        self.image.setPixmap(QPixmap(path) if path else QPixmap())

    def _open_folder(self):
        entry = self.manifest.entries[self.candidate.currentIndex()]
        if entry.images:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(entry.images[0]).parent)))
