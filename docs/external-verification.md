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
selectors. Live Edge capture on this workstation exits code 0 before publishing
DevToolsActivePort, even with a fresh headless profile. Crop visual QA cannot
currently be confirmed; this is reported rather than treated as a passing check.
