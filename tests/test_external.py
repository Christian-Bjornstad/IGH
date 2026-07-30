from __future__ import annotations

import io
import zipfile

import pytest

from igh_merge.external import (
    ArrestClient,
    ExternalAnalysisError,
    ExternalBatch,
    ExternalCandidate,
    ImgtClient,
    apply_arrest_result,
    apply_imgt_result,
    create_external_batch,
    parse_arrest_result,
    parse_imgt_full_result,
    parse_imgt_result,
    save_arrest_result,
    save_imgt_result,
    sequence_sha256,
)
from igh_merge.models import MergedRow, SourceRow


SEQUENCE = "ACGT" * 40


def candidate_batch(sequence: str = SEQUENCE) -> ExternalBatch:
    candidate = ExternalCandidate(
        external_id="SEQ-ABC123",
        row_index=0,
        sample="SYN_LOCAL_ONLY",
        target="Leader",
        rank=1,
        sequence=sequence,
        sequence_sha256=sequence_sha256(sequence),
    )
    return ExternalBatch(
        session_id="SESSION123",
        run_date="2099_01_02",
        created_at="2099-01-02T00:00:00+00:00",
        candidates=(candidate,),
    )


def merged_row(sequence: str = SEQUENCE) -> MergedRow:
    source = SourceRow(
        rank=1,
        sequence=sequence,
        length=len(sequence),
        merge_count=500,
        v_gene="IGHV1-2_01",
        j_gene="IGHJ4_02",
        percent_total_reads=3.0,
        cumulative_percent=3.0,
        mutation_rate=2.0,
        in_frame="Y",
        no_stop_codon="Y",
        v_coverage=100.0,
        cdr3_sequence="CARDR",
    )
    return MergedRow(source, "SYN_LOCAL_ONLY", 1, 100_000, "Leader", "2099_01_02")


def imgt_text(sequence: str = SEQUENCE) -> tuple[str, str]:
    parameters = (
        "Date\t2099-01-02\n"
        "IMGT/V-QUEST program version\t3.8.2\n"
        "IMGT/V-QUEST reference directory release\t209901-1\n"
    )
    header = [
        "sequence_id",
        "sequence",
        "productive",
        "stop_codon",
        "vj_in_frame",
        "v_call",
        "d_call",
        "j_call",
        "v_identity",
        "junction",
        "junction_aa",
        "insertions",
        "deletions",
        "cll_subset",
    ]
    values = [
        "SEQ-ABC123",
        sequence.lower(),
        "T",
        "F",
        "T",
        "Homsap IGHV3-21*01 F",
        "Homsap IGHD3-10*03",
        "Homsap IGHJ6*02 F",
        "0.9825",
        "ACGT",
        "CARDR",
        "",
        "",
        "CLL subset #2",
    ]
    airr = "\t".join(header) + "\n" + "\t".join(values) + "\n"
    return parameters, airr


def arrest_text(sequence: str = SEQUENCE) -> str:
    header = [
        "# label of your sequence",
        "'worst' message level from ARResT/SeqCure",
        "assigned subset, or 'unassigned'",
        "nearest subset if unassigned",
        "confidence",
        "score",
        "IMGT/V-QUEST | functionality",
        "IMGT/V-QUEST | V-gene and allele",
        "IMGT/V-QUEST | V-gene and allele % identity to germline",
        "IMGT/V-QUEST | mutational status at 98% threshold",
        "IMGT/V-QUEST | J gene and allele",
        "IMGT/V-QUEST | D gene and allele",
        "IMGT/V-QUEST | D region reading frame",
        "IMGT/V-QUEST | CDR3 length",
        "IMGT/V-QUEST | junction amino acid sequence",
        "IMGT/V-QUEST | junction frame",
        "full nucleotide sequence",
        "IMGT/V-QUEST | date and time",
        "IMGT/V-QUEST | program version",
        "IMGT/V-QUEST | reference directory release",
        "IMGT/V-QUEST | search for insertions and deletions",
    ]
    values = [
        "SEQ-ABC123",
        "OK",
        "CLL#2",
        "-",
        "high",
        "74.38",
        "productive",
        "IGHV3-21*01 F",
        "98.25",
        "unmutated",
        "IGHJ6*02 F",
        "IGHD3-10*03 F",
        "3",
        "9",
        "CARDR",
        "in-frame",
        sequence.lower(),
        "2099-01-02",
        "3.8.2",
        "209901-1",
        "yes",
    ]
    return "\t".join(header) + "\n" + "\t".join(values) + "\n"


def test_batch_payload_contains_only_external_id_and_sequence():
    batch = create_external_batch("2099_01_02", [(0, merged_row())])
    assert "SYN_LOCAL_ONLY" not in batch.fasta
    assert ">SEQ-" in batch.fasta
    assert SEQUENCE in batch.fasta


def test_batch_rejects_more_than_50_sequences():
    row = merged_row()
    with pytest.raises(ValueError, match="Maksimalt 50"):
        create_external_batch("2099_01_02", [(index, row) for index in range(51)])


def test_parse_imgt_result_and_verify_sequence():
    parameters, airr = imgt_text()
    result = parse_imgt_result(parameters, airr, candidate_batch())
    record = result.records[0]
    assert record.productive is True
    assert record.stop_codon is False
    assert record.v_identity_percent == pytest.approx(98.25)
    assert record.cll_subset == "CLL subset #2"
    assert result.program_version == "3.8.2"


def test_parse_complete_imgt_package():
    summary_header = [
        "Sequence ID", "V-DOMAIN Functionality", "V-GENE and allele",
        "V-REGION identity %", "V-REGION identity nt", "J-GENE and allele",
        "D-GENE and allele", "CDR3-IMGT length", "AA JUNCTION",
        "JUNCTION frame", "Orientation", "V-DOMAIN Functionality comment",
        "V-REGION potential ins/del", "V-REGION insertions",
        "V-REGION deletions", "Sequence", "Analysed sequence length",
        "Sequence analysis category", "CLL subset",
    ]
    summary_values = [
        "SEQ-ABC123", "productive", "Homsap IGHV3-21*01 F", "98.25",
        "283/288 nt", "Homsap IGHJ6*02 F", "Homsap IGHD3-10*03 F",
        "9", "CARDR", "in-frame", "+", "", "", "", "", SEQUENCE,
        str(len(SEQUENCE)), "V-D-J", "CLL subset #2",
    ]
    files = {
        "1_Summary.txt": "\t".join(summary_header) + "\n" + "\t".join(summary_values) + "\n",
        "5_AA-sequences.txt": "Sequence ID\tCDR3-IMGT\nSEQ-ABC123\tARD\n",
        "11_Parameters.txt": (
            "IMGT/V-QUEST program version\t3.8.2\n"
            "IMGT/V-QUEST reference directory release\t209901-1\n"
        ),
    }
    result = parse_imgt_full_result(files, candidate_batch())
    record = result.records[0]
    assert record.productive is True
    assert record.v_identity_numerator == 283
    assert record.v_identity_denominator == 288
    assert record.cdr3_aa == "ARD"
    assert record.junction_aa_length == 9


def test_parse_imgt_rejects_result_from_other_sequence():
    parameters, airr = imgt_text("A" * len(SEQUENCE))
    with pytest.raises(ExternalAnalysisError, match="annen sekvens"):
        parse_imgt_result(parameters, airr, candidate_batch())


def test_parse_arrest_result_and_verify_sequence():
    result = parse_arrest_result(arrest_text(), candidate_batch())
    record = result.records[0]
    assert record.subset == "CLL#2"
    assert record.confidence == "high"
    assert record.score == "74.38"
    assert record.sequence_verified is True


class FakeResponse:
    def __init__(
        self,
        content: bytes,
        *,
        content_type: str = "application/octet-stream",
        url: str = "https://example.invalid/result",
    ):
        self.content = content
        self.headers = {"content-type": content_type}
        self.url = url

    @property
    def text(self) -> str:
        return self.content.decode("utf-8")

    def raise_for_status(self) -> None:
        return None


def test_imgt_client_posts_no_local_sample(monkeypatch):
    parameters, airr = imgt_text()
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("Parameters.txt", parameters)
        archive.writestr("vquest_airr.tsv", airr)
    captured = {}

    def fake_post(url, *, data, timeout):
        captured.update({"url": url, "data": data, "timeout": timeout})
        return FakeResponse(buffer.getvalue())

    monkeypatch.setattr("igh_merge.external.requests.post", fake_post)
    result = ImgtClient().submit(candidate_batch())
    assert result.records[0].external_id == "SEQ-ABC123"
    assert "SYN_LOCAL_ONLY" not in captured["data"]["sequences"]
    assert captured["data"]["V_REGIONsearchIndel"] == "true"
    assert captured["data"]["cllSubsetSearch"] == "true"


def test_arrest_client_posts_no_local_sample(monkeypatch):
    captured = {}
    html = b'<a href="/results/public.tsv">plain-text-formatted results table</a>'

    def fake_post(url, *, files, timeout):
        captured.update({"url": url, "files": files, "timeout": timeout})
        return FakeResponse(
            html,
            content_type="text/html",
            url="https://bat.infspire.org/cgi-bin/arrest/assignsubsets_html.pl",
        )

    def fake_get(url, *, timeout):
        captured["result_url"] = url
        return FakeResponse(arrest_text().encode("utf-8"), url=url)

    monkeypatch.setattr("igh_merge.external.requests.post", fake_post)
    monkeypatch.setattr("igh_merge.external.requests.get", fake_get)
    result = ArrestClient().submit(candidate_batch())
    sent = captured["files"]["fastatext"][1]
    assert "SYN_LOCAL_ONLY" not in sent
    assert result.records[0].subset == "CLL#2"
    assert captured["result_url"] == "https://bat.infspire.org/results/public.tsv"


def test_results_are_saved_locally_with_mapping(tmp_path):
    batch = candidate_batch()
    parameters, airr = imgt_text()
    imgt = parse_imgt_result(parameters, airr, batch)
    arrest = parse_arrest_result(arrest_text(), batch)
    imgt_path = save_imgt_result(tmp_path, batch, imgt)
    arrest_path = save_arrest_result(tmp_path, batch, arrest)
    assert imgt_path.exists()
    assert arrest_path.exists()
    mapping = imgt_path.parent.parent / "mapping.audit.json"
    assert mapping.exists()
    assert "SYN_LOCAL_ONLY" in mapping.read_text(encoding="utf-8")
    assert SEQUENCE not in mapping.read_text(encoding="utf-8")


def test_external_results_are_applied_to_merged_columns():
    row = merged_row()
    rows = [row]
    batch = candidate_batch()
    parameters, airr = imgt_text()
    apply_imgt_result(rows, batch, parse_imgt_result(parameters, airr, batch))
    apply_arrest_result(rows, batch, parse_arrest_result(arrest_text(), batch))
    assert row.subset == "2"
    assert "IMGT 3.8.2: productive" in row.comment
    assert "ARResT: CLL#2, high, score 74.38" in row.comment
