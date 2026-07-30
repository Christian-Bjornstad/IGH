# IGH Merge

Norsk desktopapplikasjon for lokal sammenslåing og kontroll av
LymphoTrack IGHV-SHM-resultater.

## Personvern

Merge og filbehandling skjer lokalt. Ekstern analyse skjer bare når brukeren
velger Leader-sekvenser, kontrollerer den komplette FASTA-payloaden og trykker
**Send**. Appen erstatter lokale prøvenumre med tilfeldige eksterne ID-er før
sending til IMGT eller ARResT. Den sender ikke filnavn, kjøringsdato, lokale
stier eller rå FASTQ-data.

Kliniske data skal ligge utenfor Git-repoet, som standard i:

```text
C:\Users\<bruker>\Documents\IGH-data
```

Git-regler, en pre-commit-hook og CI-kontroll blokkerer vanlige kliniske
filtyper og gjenkjennelige prøveidentifikatorer. Dette erstatter ikke
virksomhetens ordinære tilgangskontroll og databehandlerprosedyrer.

## Installer og start

```powershell
python -m pip install -e .[dev]
igh-prosess
```

På Windows kan GUI-et også startes med:

```powershell
.\Start-IGH-Merge.ps1
```

Kommandolinje:

```powershell
igh-merge C:\sti\til\2026_03_09_IGHV --output C:\sti\til\2026_03_09_merged.xlsx
```

Ved et annet antall enn forventet må `--allow-count-warning` oppgis. En
eksisterende output overskrives bare med `--overwrite`.

## Arbeidsflyt

1. Velg en kjøringsmappe.
2. Valider at Leader og FR1 er komplette og parvise.
3. Se status for kjøringens kontroller.
4. Kontroller de forhåndsvalgte gule Leader-kandidatene i **IMGT og ARResT**.
5. Kontroller den pseudonymiserte FASTA-payloaden og trykk **Send** til én
   tjeneste om gangen. Selve Send-klikket er bekreftelsen.
6. Eksporter én kompatibel merged-fane med 22 kolonner.

## IMGT og ARResT

- Maksimalt 50 sekvenser sendes per batch.
- Gult er et foreløpig lokalt gruppeutvalg: `In-frame=Y`,
  `No Stop codon=Y` og enten minst 2,5 % reads eller eksakt FR1-støtte på
  minst 2,5 %. Utvalget kan endres manuelt før sending.
- Appen viser `Variant av Leader-n` for valgte Leader-sekvenser som passer
  samme konservative V/J-, lengde-, helsekvens- og CDR3-gruppe.
- FR1-støtte settes i parentes når bare én av Leader/FR1 er over 2,5 %.
- IMGT bruker Homo sapiens, IGH, AIRR-output, D-gene alignment,
  V-region-indelsøk og CLL-subset 2/8.
- ARResT-resultatet inkluderer subset, confidence, score og SeqCure-status.
- Returnerte ID-er og sekvenser verifiseres mot den lokale batchen.
- IMGT hentes som den komplette 11-filers resultatpakken, ikke bare AIRR-utdraget.
- Råresultat, parametere og lokal ID-kobling lagres i kjøringsmappen under
  `YYYY_MM_DD_external_results`.
- `Subset` og en kort kildeangivelse i `Kommentar` tas med ved neste
  merged-eksport.
- **Lag rapportutkast** oppretter én lokal PDF per prøve samt
  `rapportdata.audit.json` under `YYYY_MM_DD_rapporter\<sesjon>`. Rapportene
  inneholder dybde, Leader/FR1-andel, fulle V/D/J-alleler, identiske/total VH-nt,
  identitet, funksjonalitet, CDR3, indels og subset.

## Klinisk avgrensning

Appen utfører ikke automatisk review eller klinisk klassifikasjon av
pasientprøver. Leader er hovedresultat og FR1 er støtte. IMGT- og
ARResT-resultatene vises med kilde og skal vurderes etter lokal prosedyre.

## Tester

```powershell
pytest
python tools/check_no_clinical_data.py --all
```

Alle versjonerte tester bruker syntetiske identifikatorer og sekvenser.
