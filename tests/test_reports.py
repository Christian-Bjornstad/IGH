from __future__ import annotations

from igh_merge.external import parse_imgt_full_result
from igh_merge.reports import generate_clinical_report_package

from test_external import SEQUENCE, candidate_batch, merged_row


def test_generates_local_pdf_report_package(tmp_path):
    batch = candidate_batch()
    summary = (
        "Sequence ID\tV-DOMAIN Functionality\tV-GENE and allele\t"
        "V-REGION identity %\tV-REGION identity nt\tJ-GENE and allele\t"
        "D-GENE and allele\tCDR3-IMGT length\tAA JUNCTION\tJUNCTION frame\t"
        "Sequence\tCLL subset\n"
        f"SEQ-ABC123\tproductive\tHomsap IGHV3-21*01 F\t98.25\t"
        f"283/288 nt\tHomsap IGHJ6*02 F\tHomsap IGHD3-10*03 F\t9\t"
        f"CARDR\tin-frame\t{SEQUENCE}\tCLL subset #2\n"
    )
    imgt = parse_imgt_full_result(
        {
            "1_Summary.txt": summary,
            "5_AA-sequences.txt": "Sequence ID\tCDR3-IMGT\nSEQ-ABC123\tARD\n",
            "11_Parameters.txt": (
                "IMGT/V-QUEST program version\t3.8.2\n"
                "IMGT/V-QUEST reference directory release\t209901-1\n"
            ),
        },
        batch,
    )
    directory = generate_clinical_report_package(
        tmp_path, [merged_row()], batch, imgt
    )
    pdf = directory / "SYN_LOCAL_ONLY_IGHV_rapportutkast.pdf"
    assert pdf.exists() and pdf.stat().st_size > 1_000
    assert (directory / "rapportdata.audit.json").exists()
