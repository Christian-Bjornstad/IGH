from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import math

from .models import CONTROL_SAMPLE_ORDER, MergedRow, QcItem, QcReport

def _item(category: str, sample: str, target: str, ok: bool, message: str) -> QcItem:
    return QcItem(category, sample, target, "OK" if ok else "FEIL", message)


@dataclass(frozen=True)
class ControlLimits:
    positive_min: float = 2.5
    shm_min: float = 2.5
    mutation_min: float = 2.0
    negative_max: float = 1.0
    ntc_reads_max: int = 10_000

    def __post_init__(self):
        for value in (self.positive_min, self.shm_min, self.mutation_min, self.negative_max):
            if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 100:
                raise ValueError('Control percentages must be between 0 and 100')
        if type(self.ntc_reads_max) is not int or not 1 <= self.ntc_reads_max <= 2_000_000_000:
            raise ValueError('NTC read limit must be a positive integer')


def evaluate_qc(rows: list[MergedRow], limits: ControlLimits | None = None) -> QcReport:
    limits = limits or ControlLimits()
    groups: dict[tuple[str, str], list[MergedRow]] = defaultdict(list)
    for row in rows:
        groups[(row.sample, row.target)].append(row)
    for values in groups.values():
        values.sort(key=lambda row: row.source.rank)

    controls: list[QcItem] = []
    for control in CONTROL_SAMPLE_ORDER:
        for target in ("Leader", "FR1"):
            group = groups.get((control, target))
            if not group:
                controls.append(
                    QcItem("Kontroll", control, target, "FEIL", "Kontrollen mangler")
                )
                continue
            top = group[0]
            pct = top.source.percent_total_reads
            mutation = top.source.mutation_rate
            reads = top.total_reads
            if control == "IGH_POS":
                controls.append(
                    _item("Kontroll", control, target, pct >= limits.positive_min, f"Toppsekvens {pct:.2f} % (krav ≥{limits.positive_min:g} %)")
                )
            elif control == "IGH_SHM_POS":
                ok = pct >= limits.shm_min and mutation is not None and mutation >= limits.mutation_min
                mutation_text = "mangler" if mutation is None else f"{mutation:.2f} %"
                controls.append(
                    _item(
                        "Kontroll",
                        control,
                        target,
                        ok,
                        f"Toppsekvens {pct:.2f} %, mutasjonsrate {mutation_text} "
                        f"(krav ≥{limits.shm_min:g} % og ≥{limits.mutation_min:g} %)",
                    )
                )
            elif control == "NGS_NEG":
                controls.append(
                    _item("Kontroll", control, target, pct < limits.negative_max, f"Toppsekvens {pct:.2f} % (krav <{limits.negative_max:g} %)")
                )
            else:
                controls.append(
                    _item("Kontroll", control, target, reads < limits.ntc_reads_max, f"{reads:,} reads (krav <{limits.ntc_reads_max:,})")
                )

    return QcReport(tuple(controls))
