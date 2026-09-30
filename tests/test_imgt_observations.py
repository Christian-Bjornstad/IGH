import pytest

from igh_merge.external import parse_imgt_full_result
from igh_merge import imgt_observations
from test_external import candidate_batch, SEQUENCE


def full_files(productive='productive', identity='98.0', events='99.2'):
    headers = ['Sequence ID', 'Sequence', 'V-DOMAIN Functionality', 'V-REGION identity %',
               'V-REGION identity % (with ins/del events)', 'J-GENE and allele']
    values = ['SEQ-ABC123', SEQUENCE, productive, identity, events, 'IGHJ4*02 F, (a) IGHJ5*03 P']
    return {'1_Summary.txt': '\t'.join(headers) + '\n' + '\t'.join(values),
            '5_AA-sequences.txt': 'Sequence ID\tCDR3-IMGT\nSEQ-ABC123\tCARDR',
            '11_Parameters.txt': 'IMGT/V-QUEST program version\t3.8.3'}


@pytest.mark.parametrize('productive,expected', [('productive', 99.2), ('unproductive', 98.0)])
def test_identity_selection_retains_raw_values(productive, expected):
    record = parse_imgt_full_result(full_files(productive), candidate_batch()).records[0]
    assert record.raw_identity_percent == '98.0'
    assert record.raw_identity_with_indel_events == '99.2'
    assert record.selected_identity_percent == expected
    assert '(a)' in record.j_call
    assert 'pseudogene' in imgt_observations.j_call_notes(record.j_call)


def test_invalid_identity_rejected():
    with pytest.raises(ValueError):
        parse_imgt_full_result(full_files(identity='unreadable'), candidate_batch())


@pytest.mark.parametrize('aa,trp,phe,gxg', [
    ({118: 'W', 119: 'G', 120: 'A', 121: 'G'}, 'påvist', 'ikke påvist', 'påvist'),
    ({118: 'F', 119: 'A', 120: 'G', 121: 'G'}, 'ikke påvist', 'påvist', 'ikke påvist'),
    ({118: '-', 119: 'G', 120: '.', 121: 'G'}, 'ikke vurdert', 'ikke vurdert', 'ikke vurdert'),
    ({1: 'G', 2: 'A', 3: 'G'}, 'ikke vurdert', 'ikke vurdert', 'ikke vurdert'),
])
def test_numbered_motifs(aa, trp, phe, gxg):
    observations = imgt_observations.observe_numbered_aa(aa, source='IMGT numbered AA')
    assert [o.status for o in observations] == [trp, phe, gxg]
    assert all(o.source == 'IMGT numbered AA' for o in observations)
