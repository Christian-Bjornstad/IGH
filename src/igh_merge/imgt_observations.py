"""Descriptive observations; never a subset classifier."""
from dataclasses import dataclass
import re
from typing import Mapping


@dataclass(frozen=True)
class Observation:
    name: str
    status: str
    source: str
    detail: str


def observe_numbered_aa(aa: Mapping[int, str], *, source: str) -> tuple[Observation, ...]:
    def status(positions, condition):
        if any(aa.get(p, '').upper() not in 'ACDEFGHIKLMNPQRSTVWY' or not aa.get(p) for p in positions):
            return 'ikke vurdert'
        return 'påvist' if condition else 'ikke påvist'
    return (
        Observation('J-TRP', status([118], aa.get(118) == 'W'), source, 'AA position 118; manual assessment'),
        Observation('J-PHE', status([118], aa.get(118) == 'F'), source, 'AA position 118; manual assessment'),
        Observation('G-X-G', status([119, 120, 121], aa.get(119) == aa.get(121) == 'G'), source,
                    'AA positions 119–121; manual assessment'),
    )


def j_call_notes(raw: str) -> str:
    notes = []
    if '(a)' in raw:
        notes.append('Alternative J call (a): manual assessment')
    if re.search(r'(?<![A-Za-z0-9])IGHJ5\*03(?!\d)', raw):
        notes.append('IGHJ5*03: pseudogene (IMGT human IGHJ gene table); manual assessment')
    return '; '.join(notes)


def record_observation_text(record) -> str:
    observations = observe_numbered_aa(dict(record.numbered_aa), source=record.numbered_aa_source or 'IMGT numbering unavailable')
    return '; '.join(f'{o.name}: {o.status} ({o.detail}; {o.source})' for o in observations)
