# IGHV workspace design contract

Updated 2026-10-09 for the PyQt6 desktop application. The UI is a local laboratory workspace for prolonged review of dense molecular pathology results.

## Purpose and hierarchy

The Run page validates and lists source files; Controls supports manual QC review; IMGT & ARResT selects sequences, submits pseudonymized payloads, and reviews analysis evidence; Export creates the merged workbook; Settings stores local defaults. Preserve these English navigation labels and all existing confirmation flows.

Each page has a persistent title and workflow stage. A dark navigation rail shows the active page. Three compact summary metrics support the workflow while result tables receive the available vertical space. The minimum supported window is 1040 × 720; the default is 1380 × 900. Actions must stay visible at both sizes. Dense candidate tables may scroll horizontally rather than truncate their data.

## Palette

| Role | Value |
| --- | --- |
| Text | `#203247` |
| Secondary text | `#59697A` |
| Application | `#F3F5F7` |
| Surface | `#FFFFFF` |
| Subtle surface | `#EDF1F4` |
| Border | `#D4DDE5` |
| Control border | `#98A9B8` |
| Navigation | `#172C42` |
| Navigation hover | `#233E58` |
| Navigation text | `#F5F8FC` |
| Navigation secondary text | `#B4C5D5` |
| Primary action / active page | `#16756F` |
| Primary hover | `#105D59` |
| Selected surface | `#DDEEEB` |
| Success | `#326646` |
| Error | `#A33E42` |
| Warning | `#8A601B` |

`src/igh_merge/theme.py` is the implementation source for semantic tokens. Clinical preliminary-candidate yellow remains exactly `#FFFF00`; excluded gray remains exactly `#D9D9D9`. These states include row tooltips and text. They do not imply automatic clinical interpretation. The merged workbook's optional yellow highlighting stays off by default; report workbooks have their own formatting.

## Typography and density

Use the installed Segoe UI family without network font dependencies. Page title: 22 pt, summary values: 22 pt, body: 10 pt, controls/table headers: 9 pt, supporting captions: 8 pt. Spacing follows 4/8/12/16/24 px increments. Summary cards are 64 px tall. Table rows are 30 px with a 34 px header. Corners are 4 px for controls and 6 px for sections; no shadows, gradients, or decorative animations.

## Interaction and states

- Use native Qt controls, visible keyboard focus, meaningful accessible names, and stable geometry across hover, focus and pressed states.
- Keep dropdown and spinbox arrows visible and align their surfaces with other inputs.
- Provide explicit empty states before validation and when filters match no candidates. Filtering preserves selection, including hidden rows; the selected count describes the whole run.
- Failed validation clears the previous run's tables, metrics and action readiness, so stale results cannot appear to belong to an invalid run.
- In IMGT & ARResT, separate Analysis actions from Documentation actions. Prepare FASTA locally, then submit it with the existing payload confirmation. Evidence capture, evidence viewing and report drafts form a second group.
- Export separates workbook destination from optional formatting, then provides the export action and readiness text. Report drafts live in Documentation and produce Word, PDF and per-sample Excel workbooks.
- The optional LymphoTrack version comes from user-entered software/run metadata. An empty value remains unspecified.
- Evidence uses separate summary and captured-section tabs, with an explicit empty state and Close action.

## Finish gate

Verify all five pages at 1040 × 720 and 1380 × 900, using Windows Segoe fonts for offscreen renders. Inspect synthetic empty and populated runs. Confirm visible navigation state, readable controls, uncut actions, tabular row semantics, keyboard activation, selection preservation through filters, and cleared state after failed validation. Do not use real patient data for screenshots or tests.
