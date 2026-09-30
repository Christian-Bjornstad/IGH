"""Validated local evidence, bound to analysis session and sequence."""
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

from .external import ExternalBatch, ExternalCandidate, sequence_sha256, _atomic_write_text
from .privacy import ensure_outside_git
from .edge_cdp import IMGT_SCREENSHOT_SPECS


@dataclass(frozen=True)
class EvidenceEntry:
    external_id: str
    sequence_sha256: str
    session_id: str
    captured_at: str
    parameters: dict[str, str]
    sections: dict[str, str]
    images: tuple[str, ...]
    image_hashes: dict[str, str]
    missing_sections: dict[str, str]


@dataclass(frozen=True)
class EvidenceManifest:
    entries: tuple[EvidenceEntry, ...]


def verify_imgt_page(page, candidate: ExternalCandidate) -> None:
    shown = page.evaluate(r"""(() => {
        const title = document.querySelector('h3.sequence_title');
        let node = title?.nextElementSibling;
        while (node && node.tagName !== 'PRE') node = node.nextElementSibling;
        const lines = (node?.innerText || '').trim().split(/\n/);
        return {external_id: (title?.innerText || '').trim().split(/\s+/).pop(),
                sequence: lines.filter(line => !line.trim().startsWith('>')).join('')};
    })()""")
    if not shown or shown.get('external_id') != candidate.external_id or sequence_sha256(shown.get('sequence', '')) != candidate.sequence_sha256:
        raise ValueError('IMGT evidence page does not match external ID and sequence hash')


def validate_evidence_manifest(manifest: EvidenceManifest, batch: ExternalBatch) -> None:
    candidates = batch.by_id()
    seen = set()
    for entry in manifest.entries:
        candidate = candidates.get(entry.external_id)
        if entry.external_id in seen or not candidate or entry.session_id != batch.session_id or entry.sequence_sha256 != candidate.sequence_sha256:
            raise ValueError('Evidence does not match ID, hash or analysis session')
        seen.add(entry.external_id)
        for filename in entry.images:
            path = Path(filename)
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != entry.image_hashes.get(filename):
                raise ValueError('Evidence image is missing or has changed')


def save_evidence_manifest(directory: Path, batch: ExternalBatch, candidate: ExternalCandidate,
                           sections: dict[str, str], images, *, parameters: dict[str, str]) -> EvidenceManifest:
    ensure_outside_git(directory)
    directory.mkdir(parents=True, exist_ok=True)
    images = tuple(str(Path(path).resolve()) for path in images)
    available_images = {Path(path).stem for path in images}
    missing = {spec.key: ('Optional section not available for this sequence/molecule type' if spec.optional else 'Section not captured')
               for spec in IMGT_SCREENSHOT_SPECS if spec.key not in available_images or not sections.get(spec.key)}
    entry = EvidenceEntry(candidate.external_id, candidate.sequence_sha256, batch.session_id,
                          datetime.now(timezone.utc).isoformat(), parameters, dict(sections), images,
                          {path: hashlib.sha256(Path(path).read_bytes()).hexdigest() for path in images}, missing)
    manifest = EvidenceManifest((entry,))
    validate_evidence_manifest(manifest, batch)
    _atomic_write_text(directory / 'summary.txt', sections.get('00_summary', ''))
    _atomic_write_text(directory / 'evidence.audit.json', json.dumps(asdict(manifest), ensure_ascii=False, indent=2))
    return manifest
