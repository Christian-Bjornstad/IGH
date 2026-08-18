from __future__ import annotations

from collections import defaultdict
from math import ceil

from .models import MergedRow

CLONE_THRESHOLD = 2.5


def annotate_exact_matches(rows: list[MergedRow]) -> None:
    """Annotate cross-sample hits, relevant FR1 support, and Leader variants."""
    by_sequence: dict[str, list[MergedRow]] = defaultdict(list)
    by_sample: dict[str, list[MergedRow]] = defaultdict(list)
    for row in rows:
        by_sequence[row.source.sequence].append(row)
        by_sample[row.sample].append(row)

    for row in rows:
        tokens: list[str] = []
        for other in by_sequence[row.source.sequence]:
            if other.sample == row.sample:
                continue
            token = f"{other.sample}_{other.source.rank}_{other.target}"
            if token not in tokens:
                tokens.append(token)
        row.other_samples = ", ".join(tokens)

    for sample_rows in by_sample.values():
        leaders = [row for row in sample_rows if row.target == "Leader"]
        fr1_rows = [row for row in sample_rows if row.target == "FR1"]
        for fr1 in fr1_rows:
            exact = _relevant_exact_leaders(fr1, leaders)
            if exact:
                confident: list[str] = []
                tentative: list[str] = []
                for leader in exact:
                    label = f"Leader-{leader.source.rank}"
                    if (
                        fr1.source.percent_total_reads >= CLONE_THRESHOLD
                        and leader.source.percent_total_reads >= CLONE_THRESHOLD
                    ):
                        confident.append(label)
                    else:
                        tentative.append(label)
                comments: list[str] = []
                if confident:
                    comments.append("Supports " + " and ".join(confident))
                comments.extend(f"(Supports {label})" for label in tentative)
                fr1.comment = "; ".join(comments)

        _annotate_leader_variants(leaders, fr1_rows)


def _is_functional(row: MergedRow) -> bool:
    return (
        row.source.in_frame.strip().upper() == "Y"
        and row.source.no_stop_codon.strip().upper() == "Y"
    )


def _annotate_leader_variants(
    leaders: list[MergedRow], fr1_rows: list[MergedRow]
) -> None:
    supported_ranks = {
        leader.source.rank
        for fr1 in fr1_rows
        if fr1.source.percent_total_reads >= CLONE_THRESHOLD
        for leader in _relevant_exact_leaders(fr1, leaders)
    }
    candidates = [
        leader
        for leader in leaders
        if _is_functional(leader)
        and (
            leader.source.percent_total_reads >= CLONE_THRESHOLD
            or leader.source.rank in supported_ranks
        )
    ]
    candidates.sort(key=lambda row: row.source.rank)

    group_leaders: list[MergedRow] = []
    for candidate in candidates:
        parent = next(
            (
                group_leader
                for group_leader in group_leaders
                if _looks_like_variant(candidate, group_leader)
            ),
            None,
        )
        if parent is None:
            group_leaders.append(candidate)
            continue
        candidate.comment = f"Variant of Leader-{parent.source.rank}"


def _relevant_exact_leaders(
    fr1: MergedRow, leaders: list[MergedRow]
) -> list[MergedRow]:
    if not _is_functional(fr1):
        return []
    exact = [
        leader
        for leader in leaders
        if _is_functional(leader)
        and (
            fr1.source.percent_total_reads >= CLONE_THRESHOLD
            or leader.source.percent_total_reads >= CLONE_THRESHOLD
        )
        and fr1.source.sequence in leader.source.sequence
    ]
    high_leaders = [
        leader
        for leader in exact
        if leader.source.percent_total_reads >= CLONE_THRESHOLD
    ]
    if high_leaders:
        exact = high_leaders

    strongest_by_sequence: dict[str, MergedRow] = {}
    for leader in exact:
        sequence = leader.source.sequence
        current = strongest_by_sequence.get(sequence)
        if current is None or (
            leader.source.percent_total_reads,
            -leader.source.rank,
        ) > (
            current.source.percent_total_reads,
            -current.source.rank,
        ):
            strongest_by_sequence[sequence] = leader
    return sorted(strongest_by_sequence.values(), key=lambda row: row.source.rank)


def _looks_like_variant(candidate: MergedRow, parent: MergedRow) -> bool:
    left = candidate.source
    right = parent.source
    if len(left.sequence) != len(right.sequence):
        return False
    if _gene_family(left.v_gene) != _gene_family(right.v_gene):
        return False
    if _gene_family(left.j_gene) != _gene_family(right.j_gene):
        return False

    sequence_distance = _hamming_distance(left.sequence, right.sequence)
    if sequence_distance > ceil(len(left.sequence) * 0.10):
        return False

    left_cdr3 = left.cdr3_sequence.strip()
    right_cdr3 = right.cdr3_sequence.strip()
    cdr3_available = (
        left_cdr3
        and right_cdr3
        and left_cdr3.lower() != "not found"
        and right_cdr3.lower() != "not found"
    )
    if not cdr3_available:
        return True
    if len(left_cdr3) != len(right_cdr3):
        return False
    return _hamming_distance(left_cdr3, right_cdr3) <= max(
        1, ceil(len(left_cdr3) * 0.15)
    )


def _gene_family(value: str) -> str:
    return value.strip().upper().split("_", 1)[0]


def _hamming_distance(left: str, right: str) -> int:
    return sum(a != b for a, b in zip(left.upper(), right.upper(), strict=True))
