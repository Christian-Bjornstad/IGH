from __future__ import annotations

from collections import defaultdict

from .models import MergedRow, QcItem, QcReport

def _item(category: str, sample: str, target: str, ok: bool, message: str) -> QcItem:
    return QcItem(category, sample, target, "OK" if ok else "FEIL", message)


def evaluate_qc(rows: list[MergedRow]) -> QcReport:
    groups: dict[tuple[str, str], list[MergedRow]] = defaultdict(list)
    for row in rows:
        groups[(row.sample, row.target)].append(row)
    for values in groups.values():
        values.sort(key=lambda row: row.source.rank)

    controls: list[QcItem] = []
    for control in ("IGH_POS", "IGH_SHM_POS", "NGS_NEG", "NK"):
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
                    _item("Kontroll", control, target, pct >= 2.5, f"Toppsekvens {pct:.2f} % (krav ≥2,5 %)")
                )
            elif control == "IGH_SHM_POS":
                ok = pct >= 2.5 and mutation is not None and mutation >= 2.0
                mutation_text = "mangler" if mutation is None else f"{mutation:.2f} %"
                controls.append(
                    _item(
                        "Kontroll",
                        control,
                        target,
                        ok,
                        f"Toppsekvens {pct:.2f} %, mutasjonsrate {mutation_text} "
                        "(krav ≥2,5 % og ≥2,0 %)",
                    )
                )
            elif control == "NGS_NEG":
                controls.append(
                    _item("Kontroll", control, target, pct < 1.0, f"Toppsekvens {pct:.2f} % (krav <1,0 %)")
                )
            else:
                controls.append(
                    _item("Kontroll", control, target, reads < 10_000, f"{reads:,} reads (krav <10 000)")
                )

    return QcReport(tuple(controls))
