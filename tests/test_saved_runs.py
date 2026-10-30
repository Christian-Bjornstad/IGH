from dataclasses import replace
import json
import zipfile

import pytest

from conftest import write_summary
from igh_merge.service import MergeService
from igh_merge.external import create_external_batch, save_imgt_result, save_arrest_result
from igh_merge.evidence import save_evidence_manifest
from test_report_package import results
from test_external import arrest_text
from igh_merge.external import parse_arrest_result
from igh_merge.saved_runs import RunSession, save_session, load_session, restore_analysis
from igh_merge.qc import ControlLimits


def session(run_factory, make_row):
    root, leader, fr1 = run_factory()
    write_summary(leader, 'SYN', 1, [make_row(1, 'ACGT' * 40)])
    write_summary(fr1, 'SYN', 1, [make_row(1, 'ACGT' * 30)])
    result = MergeService().process(root, None)
    batch = create_external_batch(result.manifest.run_date, [(0, result.rows[0])])
    imgt = results(batch)
    arrest = parse_arrest_result(arrest_text().replace('SEQ-ABC123', batch.candidate_ids[0]), batch)
    return RunSession(result, batch, imgt, arrest, None, (0,), '2.4.6', ControlLimits())


def test_portable_session_reopens_without_input_and_keeps_images(run_factory, make_row, tmp_path):
    import base64
    state = session(run_factory, make_row)
    image = tmp_path / '01_v_gene.png'
    image.write_bytes(base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jXioAAAAASUVORK5CYII='))
    evidence = save_evidence_manifest(tmp_path/'evidence', state.batch, state.batch.candidates[0], {'00_summary':'summary'}, [image], parameters={})
    state = replace(state, evidence=evidence, limits=ControlLimits(positive_min=4.0))
    archive = save_session(tmp_path/'saved.ighv', state)
    image.unlink()
    loaded = load_session(archive, tmp_path/'restored')
    assert loaded.imgt == state.imgt
    assert loaded.arrest == state.arrest
    assert loaded.batch == state.batch
    assert loaded.selected == (0,)
    assert loaded.limits.positive_min == 4.0
    assert loaded.lymphotrack_version == '2.4.6'
    assert loaded.result.rows[0].source == state.result.rows[0].source
    assert loaded.result.manifest.run_directory == archive.parent
    assert loaded.evidence.entries[0].sequence_sha256 == state.batch.candidates[0].sequence_sha256
    assert loaded.evidence.entries[0].images[0].endswith('01_v_gene.png')
    assert __import__('pathlib').Path(loaded.evidence.entries[0].images[0]).is_file()


def test_legacy_audits_restore_without_resubmitting(run_factory, make_row):
    state = session(run_factory, make_row)
    root = state.result.manifest.run_directory
    saved = save_imgt_result(root, state.batch, state.imgt)
    save_arrest_result(root, state.batch, state.arrest)
    loaded = restore_analysis(saved.parent.parent/'mapping.audit.json')
    assert loaded.imgt.records == state.imgt.records
    assert loaded.arrest.records == state.arrest.records
    assert loaded.batch.candidate_ids == state.batch.candidate_ids
    assert loaded.selected == (0,)


def test_legacy_restore_from_merged_when_raw_inputs_are_missing(run_factory, make_row):
    from igh_merge.excel import ExcelReportWriter
    state = session(run_factory, make_row)
    root = state.result.manifest.run_directory
    saved = save_imgt_result(root, state.batch, state.imgt)
    ExcelReportWriter().write(state.result.rows, root/f'{state.batch.run_date}_merged.xlsx')
    # Keep the old saved results and merged workbook, without any TSV input.
    for source in state.result.manifest.sample_files:
        source.path.unlink()
    loaded = restore_analysis(saved.parent.parent/'mapping.audit.json')
    assert loaded.imgt.records == state.imgt.records
    assert loaded.result.rows[0].source.sequence == state.result.rows[0].source.sequence
    assert loaded.batch.candidate_ids == state.batch.candidate_ids


def test_session_rejects_wrong_candidate_binding_and_unsafe_image_member(run_factory, make_row, tmp_path):
    state = session(run_factory, make_row)
    archive = save_session(tmp_path/'saved.ighv', state)
    with zipfile.ZipFile(archive) as z:
        data = json.loads(z.read('session.json'))
    data['batch']['candidates'][0]['sequence_sha256'] = 'wrong'
    with zipfile.ZipFile(archive, 'w') as z:
        z.writestr('session.json', json.dumps(data))
        z.writestr('../escape.png', b'not an image')
    with pytest.raises(ValueError):
        load_session(archive, tmp_path/'restored')
    assert not (tmp_path/'escape.png').exists()


def test_session_rejects_modified_sequence_hash_without_path_attack(run_factory, make_row, tmp_path):
    state = session(run_factory, make_row)
    archive = save_session(tmp_path/'saved.ighv', state)
    with zipfile.ZipFile(archive) as z:
        data = json.loads(z.read('session.json'))
    data['batch']['candidates'][0]['sequence_sha256'] = 'wrong'
    with zipfile.ZipFile(archive, 'w') as z:
        z.writestr('session.json', json.dumps(data))
    with pytest.raises(ValueError, match='does not match'):
        load_session(archive, tmp_path/'restored')


def test_legacy_import_keeps_packaged_images_and_partial_service_coverage(run_factory, make_row, tmp_path):
    import base64
    from igh_merge.reports import generate_clinical_report_package
    state = session(run_factory, make_row)
    image = tmp_path/'01_v_gene.png'
    image.write_bytes(base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jXioAAAAASUVORK5CYII='))
    evidence = save_evidence_manifest(tmp_path/'evidence', state.batch, state.batch.candidates[0], {'00_summary':'summary'}, [image], parameters={})
    root = state.result.manifest.run_directory
    audit = save_imgt_result(root, state.batch, state.imgt)
    package = generate_clinical_report_package(root, state.result.rows, state.batch, state.imgt,
                                               evidence=evidence, lymphotrack_version='saved-version',
                                               control_limits={'positive_min': 4.0})
    image.unlink()
    loaded = restore_analysis(audit.parent.parent/'mapping.audit.json')
    assert loaded.imgt.records == state.imgt.records
    assert loaded.arrest is None
    assert loaded.lymphotrack_version == 'saved-version'
    assert loaded.limits.positive_min == 4.0
    assert len(loaded.evidence.entries[0].images) == 1
    assert 'evidence' in loaded.evidence.entries[0].images[0]


def test_session_rejects_path_in_saved_date(run_factory, make_row, tmp_path):
    state = session(run_factory, make_row)
    archive = save_session(tmp_path/'saved.ighv', state)
    with zipfile.ZipFile(archive) as z:
        data = json.loads(z.read('session.json'))
    data['result']['manifest']['run_date'] = '../../elsewhere'
    data['batch']['run_date'] = '../../elsewhere'
    with zipfile.ZipFile(archive, 'w') as z:
        z.writestr('session.json', json.dumps(data))
    with pytest.raises(ValueError, match='date'):
        load_session(archive, tmp_path/'restored')
