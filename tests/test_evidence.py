from dataclasses import replace
import pytest

from igh_merge import evidence
from test_external import candidate_batch


def test_evidence_manifest_full_text_and_binding(tmp_path):
    batch = candidate_batch()
    candidate = batch.candidates[0]
    image = tmp_path / '00_summary.png'
    image.write_bytes(b'png')
    sections = {'00_summary': 'first line\nsecond line\nthird line'}
    manifest = evidence.save_evidence_manifest(tmp_path, batch, candidate, sections, [image],
                                             parameters={'moleculeType': 'gDNA'})
    evidence.validate_evidence_manifest(manifest, batch)
    assert manifest.entries[0].sections['00_summary'] == sections['00_summary']
    assert (tmp_path / 'summary.txt').read_text(encoding='utf-8') == sections['00_summary']
    assert '04_leader' in manifest.entries[0].missing_sections
    for altered in [replace(batch, session_id='OTHER'),
                    replace(batch, candidates=(replace(candidate, sequence_sha256='wrong'),))]:
        with pytest.raises(ValueError):
            evidence.validate_evidence_manifest(manifest, altered)


def test_capture_page_wrong_sequence_rejected():
    class Page:
        def evaluate(self, expression):
            return {'external_id': 'SEQ-ABC123', 'sequence': 'TGCA' * 40}
    with pytest.raises(ValueError):
        evidence.verify_imgt_page(Page(), candidate_batch().candidates[0])
