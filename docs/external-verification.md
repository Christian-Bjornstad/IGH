# IMGT and ARResT verification 2026-09-30

Official sources: https://www.imgt.org/IMGT_vquest/user_guide and
https://www.imgt.org/IMGTrepertoire/LocusGenes/genetable/autotable.php?group=IGHJ&species=Homo+sapiens

- Detailed view shows the event-based identity in brackets to the right.
  Excel exposes it explicitly as `V-REGION identity % (with ins/del events)`.
  Both raw values are retained; productive results select this named field.
- IGHJ5*03 is P (pseudogene); retain every alternative J call, including (a).
- J-TRP/J-PHE position 118 and G-X-G 119–121 are amino acid positions.
  Unnumbered junction text never supplies numbering. Missing numbering means not assessed.

## Reanalysis deliberately deferred

GET of the current IMGT form confirms `resultType=synthesis` is labelled B.
However, two different controls are labelled No:
`V_REGIONsearchIndel=false` (search for insertions/deletions) and
`ref_dir_adjustment=true` (customize reference directory).
This identifies B in the current form, but does not establish which No the
user intended for the proposed reanalysis. Do not change either automatically.
Grouped reanalysis remains deferred under task 6; initial evidence capture
continues to use Detailed view and explicit indel search true. Synthesis also
uses different section numbering, so Detailed 1/8 is not a substitute for B 1/8.

## Service receivers

GET of https://arrest.tools/ redirects to https://bat.infspire.org/.
https://bat.infspire.org/arrest/assignsubsets/ uses form action
https://bat.infspire.org/cgi-bin/arrest/assignsubsets_html.pl.
https://station3.arrest.tools/subsets/ is a Shiny application, not a verified
compatible alternative receiver. No independent failover is configured.

## Public test

IMGT public test-set AB021511 was submitted as SEQ-ABC123, without local sample
names. HTTP Excel and Detailed HTML returned this ID and the same 367-nt sequence.
The HTTP identity was 100%. Detailed HTML confirms summary and sections 1–6/9
selectors. Live Edge capture now succeeds on this workstation in both visible
and background mode. The initial launcher exits code 0 while the managed broker
starts Edge; allowing a three-second handoff grace and disabling Startup Boost
fixes the premature failure. This follows the launch approach inspected in
https://github.com/Christian-Bjornstad/Archer-prosess (services/edge_cdp.py).
Six PNG crops were captured and their ID/sequence binding verified. The summary
crop was visually inspected. A report package generated from the public result
contains six embedded images in Word and six in PDF, plus the original evidence
files; Excel contains analysis data, without embedded screenshots.

## Completed implementation and validation

The branch implements eligibility for both targets, stable sequence-bound IDs,
homogeneous IMGT partitioning, partial failure handling, right/event identity
selection with matching nucleotide counts, alternative J-call notes, secure
ARResT retry, asynchronous evidence capture, a text/image viewer, linked
Word/PDF/Excel/evidence packages, and a shared gray-purple theme with filtering.
FR4-IMGT from `4_IMGT-gapped-AA-sequences.txt` supplies AA 118–121, following
IMGT unique numbering (FR4 starts at 118); no raw nucleotide offsets or motif
search on an unnumbered junction are used.

A fresh whole-branch reviewer found mapping overwrite, false success after
local persistence failure, and disabled reporting after ARResT. All three
were repaired with regression checks. Additional checks cover cached sequence
changes and FASTA IDs in Excel. No clinical source data were used.

160 automated tests passed; control order and 24 Excel columns are covered.
A synthetic two-rearrangement PDF was rendered and visually inspected. Qt was
inspected at 1040x720 and 1380x900 with long synthetic names. A wheel was built,
installed into a separate QA target, imported from that target, and its GUI
started. Local Python FELLES start and Qt event loop returned exit 0. This
validates the local repo copy; no K: installation or Ivanti production session
was exercised. The five-line requirements contract was retained.

The broker fix passes 161 automated tests. Live capture used only public
AB021511 data; no workstation policies or TLS verification were changed.

Outstanding validation: Word pagination (render_docx.py cannot find LibreOffice and Word is absent),
and the deliberately deferred grouped reanalysis parameter described above.
These are not reported as passing checks.
