from __future__ import annotations

import pytest

from igh_merge.io import RunDiscovery, ValidationError, parse_number
from igh_merge.service import MergeService

from conftest import write_summary


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2,50", 2.5),
        ("2.50", 2.5),
        ("1 234", 1234.0),
        ("1\u00a0234,5", 1234.5),
        ("1.234,5", 1234.5),
        ("1,234.5", 1234.5),
    ],
)
def test_parse_localized_numbers(raw, expected):
    assert parse_number(raw) == expected


def test_merge_orders_samples_and_targets_and_adds_annotations(run_factory, make_row):
    root, leader, fr1 = run_factory()
    shared = "ACGT" * 30
    write_summary(
        leader,
        "SYN_B",
        10,
        [make_row(1, "TTTT" + shared + "GGGG"), make_row(2, "AAAA" + shared + "CCCC")],
    )
    write_summary(fr1, "SYN_B", 10, [make_row(1, shared)])
    write_summary(leader, "SYN_A", 2, [make_row(1, shared)])
    write_summary(fr1, "SYN_A", 2, [make_row(1, "ACGT" * 20)])

    result = MergeService().process(root, expected_samples=2)

    assert [(item.sample, item.target) for item in result.manifest.sample_files] == [
        ("SYN_A", "Leader"),
        ("SYN_A", "FR1"),
        ("SYN_B", "Leader"),
        ("SYN_B", "FR1"),
    ]
    syn_b_fr1 = next(row for row in result.rows if row.sample == "SYN_B" and row.target == "FR1")
    assert syn_b_fr1.comment == "Støtter Leader-1 og Leader-2"
    syn_a_leader = next(row for row in result.rows if row.sample == "SYN_A" and row.target == "Leader")
    assert "SYN_B_1_FR1" in syn_a_leader.other_samples
    assert syn_a_leader.fasta.startswith(">SYN_A-Leader-1\n")


def test_possible_near_match_is_not_annotated(run_factory, make_row):
    root, leader, fr1 = run_factory()
    write_summary(
        leader,
        "SYN_A",
        1,
        [make_row(1, "A" * 120, cdr3="MATCH", j_gene="IGHJ4_02")],
    )
    write_summary(
        fr1,
        "SYN_A",
        1,
        [make_row(1, "C" * 90, cdr3="MATCH", j_gene="IGHJ4_02")],
    )
    result = MergeService().process(root, expected_samples=1)
    fr1_row = next(row for row in result.rows if row.target == "FR1")
    assert fr1_row.comment == ""


def test_support_requires_one_functional_target_above_threshold(
    run_factory, make_row
):
    root, leader, fr1 = run_factory()
    shared = "ACGT" * 30
    write_summary(
        leader,
        "SYN_A",
        1,
        [
            make_row(1, "TTTT" + shared, percent=1.71),
            make_row(2, "GGGG" + shared, percent=1.44),
            make_row(
                3,
                "CCCC" + shared,
                percent=3.5,
                in_frame="N/A",
                no_stop="N",
            ),
        ],
    )
    write_summary(
        fr1,
        "SYN_A",
        1,
        [
            make_row(1, shared, percent=3.98),
            make_row(2, shared[:-4], percent=2.12),
        ],
    )

    result = MergeService().process(root, expected_samples=1)
    fr1_rows = [row for row in result.rows if row.target == "FR1"]

    assert fr1_rows[0].comment == "(Støtter Leader-1); (Støtter Leader-2)"
    assert fr1_rows[1].comment == ""


def test_detects_selected_leader_variants_without_grouping_low_noise(
    run_factory, make_row
):
    root, leader, fr1 = run_factory()
    base = "A" * 100 + "C" * 20
    variant_high = "A" * 99 + "G" + "C" * 20
    variant_supported = "A" * 98 + "GG" + "C" * 20
    low_noise = "A" * 97 + "GGG" + "C" * 20
    write_summary(
        leader,
        "SYN_A",
        1,
        [
            make_row(1, base, percent=60.0, cdr3="CARDR"),
            make_row(2, variant_high, percent=3.0, cdr3="CARDR"),
            make_row(3, variant_supported, percent=1.7, cdr3="CARDR"),
            make_row(4, low_noise, percent=1.4, cdr3="CARDR"),
        ],
    )
    write_summary(
        fr1,
        "SYN_A",
        1,
        [
            make_row(
                1,
                variant_supported[-80:],
                percent=4.0,
                cdr3="CARDR",
            ),
            make_row(2, low_noise[-80:], percent=2.1, cdr3="CARDR"),
        ],
    )

    result = MergeService().process(root, expected_samples=1)
    leader_rows = [row for row in result.rows if row.target == "Leader"]

    assert leader_rows[0].comment == ""
    assert leader_rows[1].comment == "Variant av Leader-1"
    assert leader_rows[2].comment == "Variant av Leader-1"
    assert leader_rows[3].comment == ""


def test_support_uses_strongest_duplicate_leader_sequence(run_factory, make_row):
    root, leader, fr1 = run_factory()
    shared = "ACGT" * 30
    write_summary(
        leader,
        "SYN_A",
        1,
        [
            make_row(1, "TTTT" + shared, percent=8.0),
            make_row(2, "GGGG" + shared, percent=0.1),
        ],
    )
    write_summary(fr1, "SYN_A", 1, [make_row(1, shared, percent=6.0)])

    result = MergeService().process(root, expected_samples=1)
    leader_rows = [row for row in result.rows if row.target == "Leader"]
    fr1_row = next(row for row in result.rows if row.target == "FR1")

    assert fr1_row.comment == "Støtter Leader-1"
    assert leader_rows[1].comment == ""


def test_missing_pair_blocks_processing(run_factory, make_row):
    root, leader, _ = run_factory()
    write_summary(leader, "SYN_A", 1, [make_row(1, "A" * 100)])
    with pytest.raises(ValidationError, match="mangler FR1"):
        RunDiscovery().discover(root, expected_samples=1)


def test_duplicate_sample_target_blocks_processing(run_factory, make_row):
    root, leader, fr1 = run_factory()
    rows = [make_row(1, "A" * 100)]
    write_summary(leader, "SYN_A", 1, rows, lane=1)
    write_summary(leader, "SYN_A", 1, rows, lane=2)
    write_summary(fr1, "SYN_A", 1, rows)
    with pytest.raises(ValidationError, match="Duplikat"):
        RunDiscovery().discover(root, expected_samples=1)


def test_malformed_header_blocks_processing(run_factory, make_row):
    root, leader, fr1 = run_factory()
    path = write_summary(leader, "SYN_A", 1, [make_row(1, "A" * 100)])
    text = path.read_text(encoding="utf-8").replace("V-gene", "Changed header", 1)
    path.write_text(text, encoding="utf-8")
    write_summary(fr1, "SYN_A", 1, [make_row(1, "A" * 90)])
    with pytest.raises(ValidationError, match="header"):
        RunDiscovery().discover(root, expected_samples=1)


def test_count_difference_is_warning_when_pairs_are_complete(run_factory, make_row):
    root, leader, fr1 = run_factory()
    write_summary(leader, "SYN_A", 1, [make_row(1, "A" * 100)])
    write_summary(fr1, "SYN_A", 1, [make_row(1, "A" * 90)])
    manifest = RunDiscovery().discover(root, expected_samples=24)
    assert manifest.warnings == ("Forventet 24 prøver per target, fant 1",)
