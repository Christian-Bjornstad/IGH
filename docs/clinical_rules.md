# Control Rules in V1

Only the run controls are evaluated automatically. Patient samples are
assessed manually without review alerts from the app.

Source basis reviewed locally 2026-07-30:

- `HTS - IGHV-SHM (KLL)`, document ID 134367
- `KLL - IGHV mutation - Background and interpretation`, document ID 38899, version 5

## Controls

| Filename | Meaning | Rule |
|---|---|---|
| `IGH_POS` | IGH-PK | Top sequence at least 2.5 % |
| `IGH_SHM_POS` | IGH-SHM | Top sequence at least 2.5 % and mutation rate at least 2.0 % |
| `NGS_NEG` | Negative control | Top sequence below 1.0 % |
| `NK` | NTC | Total reads below 10,000 |

Leader and FR1 are evaluated separately. Missing or failed controls are
shown as control errors. Sample review, exceptions, biclonality, borderline
results, and final functionality are handled manually.

## Operational Clone Grouping

The app creates a preliminary, local grouping to limit which
Leader sequences are sent to IMGT and ARResT:

- Only rows with `In-frame=Y` and `No Stop codon=Y` may be included.
- Leader at least 2.5 % is included.
- Leader below 2.5 % is included when an FR1 of at least 2.5 % overlaps
  the Leader exactly. The FR1 comment is then set in parentheses.
- When the same FR1 overlaps both a Leader above and below 2.5 %, the
  Leader row above the threshold is prioritized.
- A selected Leader is marked `Variant of Leader-n` when it has the same
  V- and J-gene family, same length, at most 10 % nucleotide deviation
  in the whole sequence, and, when CDR3 is found, at most 15 % deviation
  in CDR3.

This is grouping and selection, not automatic clinical classification.
