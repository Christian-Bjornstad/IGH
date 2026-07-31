from __future__ import annotations

from collections.abc import Sequence

from .models import MergedRow


def is_functional_group_candidate(
    rows: Sequence[MergedRow], result_index: int
) -> bool:
    """Returner om Leader-raden følger appens foreløpige gule utvalg."""
    leader = rows[result_index]
    source = leader.source
    if (
        leader.target != "Leader"
        or source.in_frame.strip().upper() != "Y"
        or source.no_stop_codon.strip().upper() != "Y"
    ):
        return False
    if source.percent_total_reads >= 2.5:
        return True

    label = f"Leader-{source.rank}"
    return any(
        row.sample == leader.sample
        and row.target == "FR1"
        and row.source.percent_total_reads >= 2.5
        and row.source.in_frame.strip().upper() == "Y"
        and row.source.no_stop_codon.strip().upper() == "Y"
        and label in row.comment.replace("(", "").replace(")", "").split()
        for row in rows
    )


def functional_group_candidate_indices(rows: Sequence[MergedRow]) -> frozenset[int]:
    return frozenset(
        index
        for index in range(len(rows))
        if is_functional_group_candidate(rows, index)
    )
