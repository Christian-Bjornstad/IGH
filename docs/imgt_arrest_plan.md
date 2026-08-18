# Plan for IMGT and ARResT Phase

Status: foundation and first integration implemented. External sending only
occurs after payload preview and explicit confirmation.

## Goals

- Analyze manually selected Leader rearrangements in IMGT/V-QUEST.
- Retrieve productivity indicators, V/D/J calls, identity, and tool version
  from IMGT without overwriting LymphoTrack results.
- Assign CLL subset with clear source. IMGT can identify subsets 2 and 8,
  while ARResT/AssignSubsets covers 19 major subsets.
- Maintain the compatible merged sheet with 22 columns.
- Do not introduce automatic clinical review or decision support.

## Locked Rule for External Sending

1. The app sends only selected nucleotide sequences in FASTA format with
   random external IDs. It never sends sample names, patient IDs, filenames,
   run dates, local paths, or raw FASTQ data.
2. The user sees the complete payload before sending and must explicitly
   initiate each send. There is no background sending.
3. IMGT should be contacted regarding automated use of the tool per their
   terms. The terms state that scientific input and output data are normally
   stored on IMGT servers for four to six months.
4. Retention, processing location, and terms for ARResT are documented in
   local procedure. The app shows the service as recipient before sending.
5. Automatic retry can only occur while the dialog is open and must use
   exactly the same pseudonymous payload.

## Data Model and Local Storage

For each selected rearrangement, the following is stored locally in the
run folder:

- Random external ID and linkage to Sample/Target/Rank;
- SHA-256 of the sequence for secure result linkage;
- Service, analysis time, parameters, tool version, and
  reference database release;
- Raw result file unchanged;
- Normalized IMGT fields: productive, stop_codon, vj_in_frame, V/D/J calls,
  V identity, junction/CDR3, and any indel findings;
- Normalized ARResT fields: subset, confidence, score, and SeqCure status.

The linkage file and raw results are clinical data, stored outside Git and
never included in application logs. LymphoTrack fields and `Identity to VH`
are not overwritten by IMGT.

## Phase 1 – Common Send and Result Foundation (implemented)

1. Add the **IMGT & ARResT** tab.
2. Let the user select Leader rows and create batches of up to 50
   complete nucleotide sequences.
3. Build a pseudonymized FASTA payload and a local linkage file. Raw FASTQ
   is not sent.
4. Show the locked IMGT settings:
   - Species: Homo sapiens
   - Receptor type or locus: IGH
   - AIRR-formatted result
   - Alignment for D-GENE: on
   - Search for insertions and deletions in V-REGION: on
   - Clinical application, CLL subsets 2 and 8: on
5. Show payload preview and recipient domains before active sending.
6. Send to IMGT and import `Parameters.txt` and `vquest_airr.tsv`.
7. Send the same pseudonymous FASTA to ARResT and import
   the plain-text result table.
8. Validate unique external IDs, missing/extra rows, sequence hash, and
   required columns before results can be linked back.

## Phase 2 – IMGT Adapter (implemented)

IMGT is built as an isolated adapter with the following contract:

- Input is only pseudonym ID and sequence;
- Batch size maximum 50;
- Fixed, versioned parameters from phase 1;
- Output is `Parameters.txt` and `vquest_airr.tsv`;
- Timeout, abort, and partial result give status, not automatic
  classification;
- Response's program version, reference release, and parameters must be present;
  - Changed schema or unknown version stops import in a controlled manner.

`ShawHahnLab/vquest` can be used as reference or isolated dependency after
license assessment. The package automates the web form, is AGPL-3.0, supports
only AIRR results, and has the latest published release from 2022. It should
therefore not be linked directly without a contract test against the current
IMGT/V-QUEST.

## Phase 3 – ARResT (implemented)

ARResT is built as a separate adapter:

- Maximum 50 complete IG nucleotide sequences and approximately 100 kB;
- Parser for label, SeqCure, subset, confidence, and score;
- `unassigned` and `skipped/unhealthy` are treated as result values;
- Borderline/low is stored unchanged without the app interpreting them;
- The adapter must account for ARResT itself using IMGT/V-QUEST.

IMGT result for subset 2/8 and ARResT result are stored separately. In case
of disagreement, both sources are shown; the app does not automatically pick
a winner.

## GUI and Merged Output

The **IMGT & ARResT** tab shall show:

- Selected rows and pseudonymous external IDs;
- Status: not exported, exported, imported, or import error;
- IMGT fields and ARResT fields side by side;
- Version, reference release, timestamp, and parameters;
- Buttons for local export and import;
- Send buttons with payload preview and clear recipient.

In the merged file, the columns are retained:

- `Subset`: confirmed subset value;
- `Comment`: short source attribution, for example
  `IMGT 3.8.2: productive; ARResT: subset 2, high`.

Complete external results are stored in a separate local sidecar file, so
the merged sheet remains compatible and traceability is not compressed away.

## Tests and Acceptance

- All automated tests use published example data or constructed
  sequences.
- Parsers are tested against stored, anonymized fixtures for valid result,
  missing row, duplicate, changed header, partial batch, and unknown version.
- No network is used in unit tests.
- Contract test is run manually with public IMGT/ARResT examples before each
  approved release.
- Test shall prove that external payload does not contain internal sample IDs.
- Test shall prove that results from wrong sequence or wrong run cannot
  be imported.
- Merged export shall retain 22 columns, formulas, and formatting.
- A clinical pilot is compared with manual workflow and signed by
  responsible specialist before the function enters routine use.

## Proposed Delivery Sequence

1. Data model, pseudonymous IDs, and sidecar format. Done.
2. Tab, payload preview, and IMGT AIRR parser. Done.
3. ARResT parser and source-aware subset display. Done.
4. Contract test with public sequence against IMGT 3.8.2 and ARResT. Done.
5. Local validation against historical, non-versioned clinical results.
6. Terms and professional documentation.
7. Clinical pilot and sign-off before routine use.
