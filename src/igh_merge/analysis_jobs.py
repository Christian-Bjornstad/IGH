"""Sequential service jobs with per-sequence failure accounting."""
from dataclasses import dataclass, replace
from typing import Callable

from .external import ExternalAnalysisError, ExternalBatch, MAX_BATCH_SIZE


def partition_imgt_batch(batch: ExternalBatch, max_sequences: int = 50) -> tuple[ExternalBatch, ...]:
    if not 1 <= max_sequences <= MAX_BATCH_SIZE:
        raise ValueError('IMGT capacity must be between 1 and 50')
    groups = {}
    for candidate in batch.candidates:
        if candidate.molecule_type not in {'gDNA', 'cDNA'}:
            raise ValueError('Unknown molecule type')
        groups.setdefault(candidate.molecule_type, []).append(candidate)
    return tuple(replace(batch, candidates=tuple(items[start:start + max_sequences]))
                 for items in groups.values() for start in range(0, len(items), max_sequences))


@dataclass(frozen=True)
class AnalysisJobResult:
    parts: tuple[tuple[ExternalBatch, object], ...]
    errors: dict[str, str]

    @property
    def complete(self) -> bool:
        return not self.errors


def run_analysis_job(service: str, batch: ExternalBatch, client,
                     progress: Callable[[int, int], None] | None = None) -> AnalysisJobResult:
    partitions = partition_imgt_batch(batch) if service == 'IMGT' else (
        tuple(replace(batch, candidates=batch.candidates[start:start + MAX_BATCH_SIZE])
              for start in range(0, len(batch.candidates), MAX_BATCH_SIZE)))
    parts, errors = [], {}
    for index, part in enumerate(partitions):
        try:
            result = client.submit(part)
            parts.append((part, result))
        except (ExternalAnalysisError, OSError, ValueError) as exc:
            errors.update({c.external_id: str(exc) for c in part.candidates})
        if progress:
            progress(index + 1, len(partitions))
    return AnalysisJobResult(tuple(parts), errors)
