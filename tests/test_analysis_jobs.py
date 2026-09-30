from dataclasses import replace

import pytest

from igh_merge import analysis_jobs
from igh_merge.external import ExternalAnalysisError, create_external_batch, ImgtBatchResult
from test_external import merged_row
from igh_merge.external import save_batch_mapping, save_imgt_result
import json


def test_partition_keeps_ids_and_molecule_types():
    rows = [merged_row('ACGT' * (i + 1)) for i in range(51)]
    for i, row in enumerate(rows):
        row.molecule_type = 'cDNA' if i % 2 else 'gDNA'
    batch = create_external_batch('2099_01_02', list(enumerate(rows)))
    parts = analysis_jobs.partition_imgt_batch(batch, max_sequences=10)
    assert all(len(part.candidates) <= 10 for part in parts)
    assert all(len({c.molecule_type for c in part.candidates}) == 1 for part in parts)
    assert sorted(c.external_id for p in parts for c in p.candidates) == sorted(batch.candidate_ids)
    assert all(p.session_id == batch.session_id for p in parts)


def test_partial_job_retains_success_and_errors():
    rows = [merged_row(), merged_row('TGCA' * 40)]
    rows[1].molecule_type = 'cDNA'
    batch = create_external_batch('2099_01_02', list(enumerate(rows)))
    class Client:
        def submit(self, part):
            if part.candidates[0].molecule_type == 'cDNA':
                raise ExternalAnalysisError('service unavailable')
            return ImgtBatchResult({}, (), '', '')
    result = analysis_jobs.run_analysis_job('IMGT', batch, Client())
    assert len(result.parts) == 1
    assert result.errors == {batch.candidate_ids[1]: 'service unavailable'}
    assert not result.complete


def test_partition_invalid_capacity():
    batch = create_external_batch('2099_01_02', [(0, merged_row())])
    with pytest.raises(ValueError):
        analysis_jobs.partition_imgt_batch(batch, max_sequences=0)


def test_partition_saves_do_not_replace_master_mapping(tmp_path):
    rows = [merged_row(), merged_row()]
    rows[1].molecule_type = 'cDNA'
    batch = create_external_batch('2099_01_02', list(enumerate(rows)))
    mapping = save_batch_mapping(tmp_path, batch)
    for part in analysis_jobs.partition_imgt_batch(batch):
        save_imgt_result(tmp_path, part, ImgtBatchResult({}, (), '', ''))
    assert {c['external_id'] for c in json.loads(mapping.read_text())['candidates']} == set(batch.candidate_ids)
