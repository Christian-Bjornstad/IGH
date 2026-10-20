from dataclasses import replace

import pytest

from igh_merge import candidates
from igh_merge.external import create_external_batch
from igh_merge.io import detect_molecule_type
from test_external import merged_row


@pytest.mark.parametrize('target', ['Leader', 'FR1'])
@pytest.mark.parametrize('percent,selected', [(2.49, False), (2.499, False), (2.5, True), (2.51, True)])
@pytest.mark.parametrize('frame,stop', [('Y', 'Y'), ('Y', 'N'), ('N', 'N')])
def test_analysis_threshold_ignores_functionality(target, percent, selected, frame, stop):
    row = merged_row()
    row.target = target
    row.source = replace(row.source, percent_total_reads=percent, in_frame=frame, no_stop_codon=stop)
    assert candidates.analysis_candidate_indices([row]) == (frozenset({0}) if selected else frozenset())


@pytest.mark.parametrize('name', ['SYN-cDNA-1', 'SYN.CdNa', 'cdna SYN', 'SYN_cdna'])
def test_molecule_token(name):
    assert detect_molecule_type(name) == 'cDNA'


def test_embedded_molecule_word():
    assert detect_molecule_type('acdnab') == 'gDNA'


def test_stable_id_and_sequence_change():
    row = merged_row()
    first = create_external_batch('2099_01_02', [(0, row)])
    assert row.external_id == first.candidate_ids[0]
    assert create_external_batch('2099_01_02', [(0, row)]).candidate_ids == first.candidate_ids
    row.source = replace(row.source, sequence='TGCA' * 40)
    assert create_external_batch('2099_01_02', [(0, row)]).candidate_ids != first.candidate_ids


def test_excel_fasta_uses_assigned_external_id():
    row = merged_row()
    batch = create_external_batch('2099_01_02', [(0, row)])
    assert row.fasta == batch.fasta.rstrip('\n')
    assert row.sample not in row.fasta


def test_duplicate_existing_ids_rejected():
    rows = [merged_row(), merged_row()]
    for row in rows:
        row.external_id = 'SEQ-ABC123'
    with pytest.raises(ValueError, match='duplicate'):
        create_external_batch('2099_01_02', list(enumerate(rows)))


def test_invalid_existing_id_rejected():
    row = merged_row()
    row.external_id = 'SYN_LOCAL_ONLY'
    with pytest.raises(ValueError, match='external ID'):
        create_external_batch('2099_01_02', [(0, row)])

