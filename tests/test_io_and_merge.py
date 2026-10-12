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
    assert syn_b_fr1.comment == "Supports Leader-1 and Leader-2"
    syn_a_leader = next(row for row in result.rows if row.sample == "SYN_A" and row.target == "Leader")
    assert "SYN_B_1_FR1" in syn_a_leader.other_samples
    assert syn_a_leader.fasta.startswith(">SYN_A-Leader-1\n")


def test_merge_places_controls_first_in_required_order(run_factory, make_row):
    root, leader, fr1 = run_factory()
    samples = [
        ("SYN_PATIENT", 1),
        ("NK", 2),
        ("IGH_POS", 3),
        ("NGS_NEG", 4),
        ("IGH_SHM_POS", 5),
    ]
    for sample, number in samples:
        write_summary(leader, sample, number, [make_row(1, "ACGT" * 30)])
        write_summary(fr1, sample, number, [make_row(1, "TGCA" * 30)])

    result = MergeService().process(root, expected_samples=5)

    assert [
        item.sample
        for item in result.manifest.sample_files
        if item.target == "Leader"
    ] == ["IGH_SHM_POS", "IGH_POS", "NGS_NEG", "NK", "SYN_PATIENT"]
    assert [
        row.sample
        for row in result.rows
        if row.target == "Leader"
    ] == ["IGH_SHM_POS", "IGH_POS", "NGS_NEG", "NK", "SYN_PATIENT"]


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


def test_support_includes_nonfunctional_high_leader(
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

    assert fr1_rows[0].comment == "Supports Leader-3"
    assert fr1_rows[1].comment == "(Supports Leader-3)"


@pytest.mark.parametrize(
    ("leader_frame", "leader_stop", "fr1_frame", "fr1_stop"),
    [("N", "Y", "Y", "Y"), ("Y", "N", "Y", "Y"),
     ("Y", "Y", "N", "Y"), ("N", "N", "N", "N")],
)
def test_exact_support_does_not_require_functionality(
    run_factory, make_row, leader_frame, leader_stop, fr1_frame, fr1_stop
):
    root, leader, fr1 = run_factory()
    sequence = "ACGT" * 30
    write_summary(leader, "SYN_A", 1, [make_row(
        1, "TTTT" + sequence, percent=2.5,
        in_frame=leader_frame, no_stop=leader_stop,
    )])
    write_summary(fr1, "SYN_A", 1, [make_row(
        1, sequence, percent=2.5, in_frame=fr1_frame, no_stop=fr1_stop,
    )])

    result = MergeService().process(root, expected_samples=1)
    support = next(row for row in result.rows if row.target == "FR1")

    assert support.comment == "Supports Leader-1"


def test_nonfunctional_support_preserves_functional_low_leader_grouping(
    run_factory, make_row
):
    from igh_merge.candidates import functional_group_candidate_indices

    root, leader, fr1 = run_factory()
    sequence = "ACGT" * 30
    write_summary(leader, "SYN_A", 1, [
        make_row(1, "TTTT" + sequence, percent=1.0),
        make_row(2, "CCCC" + sequence, percent=3.0, no_stop="N"),
    ])
    write_summary(fr1, "SYN_A", 1, [make_row(1, sequence, percent=3.0)])

    result = MergeService().process(root, expected_samples=1)

    assert functional_group_candidate_indices(result.rows) == frozenset({0})
    assert result.rows[2].comment == "Supports Leader-2"


def test_exact_support_helper_uses_same_sample_and_strongest_exact_leader(
    run_factory, make_row
):
    from igh_merge.matching import exact_supporting_leaders

    root, leader, fr1 = run_factory()
    sequence = "ACGT" * 30
    write_summary(leader, "SYN_A", 1, [
        make_row(1, "TTTT" + sequence, percent=3.0, no_stop="N"),
        make_row(2, "TTTT" + sequence, percent=4.0, no_stop="N"),
        make_row(3, "CCCC" + sequence, percent=1.0),
        make_row(4, "TTTT" + sequence[:-1] + "A", percent=5.0),
    ])
    write_summary(fr1, "SYN_A", 1, [make_row(1, sequence, percent=3.0)])
    write_summary(leader, "SYN_B", 2, [make_row(1, sequence, percent=6.0)])
    write_summary(fr1, "SYN_B", 2, [make_row(1, "C" * 30, percent=6.0)])
    result = MergeService().process(root, expected_samples=2)
    support = next(row for row in result.rows if row.sample == "SYN_A" and row.target == "FR1")

    assert [row.source.rank for row in exact_supporting_leaders(support, result.rows)] == [2]
    assert [row.source.rank for row in exact_supporting_leaders(
        support, result.rows, functional_only=True
    )] == [3]


def test_exact_support_helper_requires_one_target_at_unrounded_threshold(
    run_factory, make_row
):
    from igh_merge.matching import exact_supporting_leaders

    root, leader, fr1 = run_factory()
    sequence = "ACGT" * 30
    write_summary(leader, "SYN_A", 1, [make_row(1, "TTTT" + sequence, percent=2.499)])
    write_summary(fr1, "SYN_A", 1, [
        make_row(1, sequence, percent=2.499),
        make_row(2, sequence, percent=2.5),
    ])
    result = MergeService().process(root, expected_samples=1)

    assert exact_supporting_leaders(result.rows[1], result.rows) == []
    assert [row.source.rank for row in exact_supporting_leaders(
        result.rows[2], result.rows
    )] == [1]


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
    assert leader_rows[1].comment == "Variant of Leader-1"
    assert leader_rows[2].comment == "Variant of Leader-1"
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

    assert fr1_row.comment == "Supports Leader-1"
    assert leader_rows[1].comment == ""


def test_missing_pair_blocks_processing(run_factory, make_row):
    root, leader, _ = run_factory()
    write_summary(leader, "SYN_A", 1, [make_row(1, "A" * 100)])
    with pytest.raises(ValidationError, match="missing FR1"):
        RunDiscovery().discover(root, expected_samples=1)


def test_duplicate_sample_target_blocks_processing(run_factory, make_row):
    root, leader, fr1 = run_factory()
    rows = [make_row(1, "A" * 100)]
    write_summary(leader, "SYN_A", 1, rows, lane=1)
    write_summary(leader, "SYN_A", 1, rows, lane=2)
    write_summary(fr1, "SYN_A", 1, rows)
    with pytest.raises(ValidationError, match="Duplicate"):
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
    assert manifest.warnings == ("Expected 24 samples per target, found 1",)
