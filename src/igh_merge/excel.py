from __future__ import annotations

import os
import tempfile
from pathlib import Path

from openpyxl import Workbook
from openpyxl.formatting.rule import CellIsRule, FormulaRule
from openpyxl.styles import Alignment, Border, Font, Side

from .models import MergedRow
from .privacy import ensure_outside_git

HEADERS = (
    "Rank",
    "Sequence",
    "Length",
    "Merge count",
    "V-gene",
    "J-gene",
    "% total reads",
    "Cumulative %",
    "Mutation rate to partial V-gene (%)",
    "In-frame (Y/N)",
    "No Stop codon (Y/N)",
    "V-coverage",
    "CDR3 Seq",
    "Identitet til VH",
    "Sample",
    "Reads",
    "Target",
    "Dato PCR-oppsett",
    "find sequence in other samples",
    "Subset",
    "Kommentar",
    "Fasta",
)


class ExcelReportWriter:
    def write(self, rows: tuple[MergedRow, ...] | list[MergedRow], output: Path, *, overwrite: bool = False) -> Path:
        output = output.expanduser().resolve()
        if output.suffix.lower() != ".xlsx":
            output = output.with_suffix(".xlsx")
        ensure_outside_git(output)
        if output.exists() and not overwrite:
            raise FileExistsError(f"Output finnes allerede: {output}")
        output.parent.mkdir(parents=True, exist_ok=True)

        workbook = Workbook()
        worksheet = workbook.active
        worksheet.title = "Sheet1"
        worksheet.append(HEADERS)
        for excel_row, item in enumerate(rows, start=2):
            source = item.source
            worksheet.append(
                [
                    source.rank,
                    source.sequence,
                    source.length,
                    source.merge_count,
                    source.v_gene,
                    source.j_gene,
                    source.percent_total_reads,
                    source.cumulative_percent,
                    source.mutation_rate,
                    source.in_frame,
                    source.no_stop_codon,
                    source.v_coverage,
                    source.cdr3_sequence,
                    f'=IF(I{excel_row}="","",100-I{excel_row})',
                    item.sample,
                    item.total_reads,
                    item.target,
                    item.run_date,
                    item.other_samples,
                    item.subset,
                    item.comment,
                    item.fasta,
                ]
            )

        self._format(worksheet, len(rows) + 1)
        workbook.calculation.fullCalcOnLoad = True
        workbook.calculation.forceFullCalc = True
        workbook.calculation.calcMode = "auto"

        fd, temporary_name = tempfile.mkstemp(
            prefix=f".{output.stem}-", suffix=".xlsx", dir=output.parent
        )
        os.close(fd)
        temporary = Path(temporary_name)
        try:
            workbook.save(temporary)
            os.replace(temporary, output)
        finally:
            workbook.close()
            temporary.unlink(missing_ok=True)
        return output

    def _format(self, worksheet, last_row: int) -> None:
        thin = Side(style="thin", color="D9D9D9")
        border = Border(left=thin, right=thin, top=thin, bottom=thin)
        for cell in worksheet[1]:
            cell.font = Font(name="Calibri", size=11, bold=True, color="000000")
            cell.alignment = Alignment(horizontal="center", vertical="bottom")
            cell.border = border
        worksheet.row_dimensions[1].height = 28

        for row in worksheet.iter_rows(min_row=2, max_row=last_row, min_col=1, max_col=22):
            for cell in row:
                cell.font = Font(name="Calibri", size=11, color="000000")
                cell.alignment = Alignment(vertical="center")
                cell.border = border
            row[14].font = Font(name="Calibri", size=11, bold=True, color="000000")
            # Behold kompakte rader som i referansefilen. FASTA-innholdet kan
            # leses i formellinjen uten at hele sekvensen blåser opp radhøyden.
            row[21].alignment = Alignment(vertical="center", wrap_text=False)

        for column in ("G", "H", "I", "L", "N"):
            for cell in worksheet[f"{column}2:{column}{last_row}"]:
                cell[0].number_format = "0.##"
        for cell in worksheet[f"P2:P{last_row}"]:
            cell[0].number_format = "#,##0"

        green_font = Font(color="008000", bold=False)
        black_font = Font(color="000000", bold=False)
        bold_font = Font(color="000000", bold=True)
        red_font = Font(color="FF0000")
        percent_range = f"G2:G{last_row}"
        worksheet.conditional_formatting.add(
            percent_range, CellIsRule(operator="greaterThanOrEqual", formula=["2.5"], font=bold_font)
        )
        worksheet.conditional_formatting.add(
            percent_range,
            CellIsRule(operator="between", formula=["2.4", "2.499999999"], font=black_font),
        )
        worksheet.conditional_formatting.add(
            percent_range, CellIsRule(operator="lessThan", formula=["2.4"], font=green_font)
        )
        worksheet.conditional_formatting.add(
            f"J2:J{last_row}",
            FormulaRule(formula=['OR(J2="N",J2="N/A")'], font=red_font),
        )
        worksheet.conditional_formatting.add(
            f"K2:K{last_row}",
            FormulaRule(formula=['OR(K2="N",K2="N/A")'], font=red_font),
        )

        widths = {
            "A": 8, "B": 55, "C": 10, "D": 14, "E": 20, "F": 16,
            "G": 14, "H": 14, "I": 30, "J": 16, "K": 20, "L": 13,
            "M": 22, "N": 17, "O": 18, "P": 14, "Q": 11, "R": 18,
            "S": 34, "T": 13, "U": 30, "V": 60,
        }
        for column, width in widths.items():
            worksheet.column_dimensions[column].width = width
        worksheet.freeze_panes = "A2"
        worksheet.auto_filter.ref = f"A1:V{last_row}"
        worksheet.sheet_view.showGridLines = True
