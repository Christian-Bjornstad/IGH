from dataclasses import replace
import pytest
from igh_merge.qc import ControlLimits, evaluate_qc
from test_external import merged_row


def test_changed_limits_change_status_and_requirement_text():
    row = merged_row()
    row.sample = 'IGH_POS'
    row.source = replace(row.source, percent_total_reads=3.0)
    assert evaluate_qc([row]).controls[2].status == 'OK'
    strict = evaluate_qc([row], ControlLimits(positive_min=4.0))
    assert strict.controls[2].status == 'FEIL'
    assert '4' in strict.controls[2].message


@pytest.mark.parametrize('kwargs', [{'positive_min':-1}, {'negative_max':float('nan')}, {'ntc_reads_max':0}])
def test_control_limits_reject_invalid_values(kwargs):
    with pytest.raises(ValueError):
        ControlLimits(**kwargs)
