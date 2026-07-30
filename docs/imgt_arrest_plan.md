# Plan for IMGT- og ARResT-fasen

Status: grunnmur og første integrasjon implementert. Ekstern sending skjer kun
etter payload-forhåndsvisning og eksplisitt bekreftelse.

## Mål

- Analysere manuelt valgte Leader-rearrangeringer i IMGT/V-QUEST.
- Hente produktivitetsindikatorer, V/D/J-kall, identitet og verktøyversjon fra
  IMGT uten å overskrive LymphoTrack-resultater.
- Tilordne CLL-subset med tydelig kilde. IMGT kan identifisere subset 2 og 8,
  mens ARResT/AssignSubsets dekker 19 hovedsubsets.
- Beholde dagens kompatible merged-ark med 22 kolonner.
- Ikke innføre automatisk klinisk review eller beslutningsstøtte.

## Låst regel for ekstern sending

1. Appen sender bare valgte nukleotidsekvenser i FASTA-format med tilfeldige
   eksterne ID-er. Den sender aldri Sample-navn, pasient-ID, filnavn,
   kjøringsdato, lokale stier eller rå FASTQ-data.
2. Brukeren får se den komplette payloaden før sending og må starte hver
   sending eksplisitt. Det finnes ingen bakgrunnssending.
3. IMGT bør kontaktes om automatisert bruk av verktøyet i tråd med vilkårene.
   Vilkårene
   opplyser at vitenskapelige input- og outputdata normalt lagres på
   IMGT-servere i fire til seks måneder.
4. Retensjon, behandlingssted og vilkår for ARResT dokumenteres i lokal
   prosedyre. Appen viser tjenesten som mottaker før sending.
5. Automatisk retry kan bare skje mens dialogen er åpen og må bruke nøyaktig
   samme pseudonyme payload.

## Datamodell og lokal lagring

For hver valgt rearrangering lagres følgende lokalt i kjøringsmappen:

- tilfeldig ekstern ID og kobling til Sample/Target/Rank;
- SHA-256 av sekvensen for sikker resultatkobling;
- tjeneste, analysetidspunkt, parametere, verktøyversjon og
  referansedatabase-release;
- rå resultatfil uendret;
- normaliserte IMGT-felt: productive, stop_codon, vj_in_frame, V/D/J-kall,
  V-identitet, junction/CDR3 og eventuelle indelfunn;
- normaliserte ARResT-felt: subset, confidence, score og SeqCure-status.

Koblingsfilen og råresultatene er kliniske data, lagres utenfor Git og tas
aldri med i applikasjonslogger. LymphoTrack-feltene og `Identitet til VH`
overskrives ikke av IMGT.

## Fase 1 – felles sende- og resultatgrunnlag (implementert)

1. Legg til fanen **IMGT og ARResT**.
2. La brukeren velge Leader-rader og opprette batcher på maksimalt 50
   fullstendige nukleotidsekvenser.
3. Bygg en pseudonymisert FASTA-payload og en lokal koblingsfil. Rå FASTQ
   sendes ikke.
4. Vis de låste IMGT-innstillingene:
   - Species: Homo sapiens
   - Receptor type or locus: IGH
   - AIRR-formatert resultat
   - Alignment for D-GENE: på
   - Search for insertions and deletions in V-REGION: på
   - Clinical application, CLL subsets 2 and 8: på
5. Vis en payload-forhåndsvisning og mottakerdomene før aktiv sending.
6. Send til IMGT og importer `Parameters.txt` og `vquest_airr.tsv`.
7. Send samme pseudonyme FASTA til ARResT og importer
   plain-text-resultattabellen.
8. Valider unike eksterne ID-er, manglende/ekstra rader, sekvenshash og
   nødvendige kolonner før resultatene kan knyttes tilbake.

## Fase 2 – IMGT-adapter (implementert)

IMGT bygges som en isolert adapter med følgende kontrakt:

- input er kun pseudonym ID og sekvens;
- batchstørrelse maksimalt 50;
- faste, versjonerte parametere fra fase 1;
- output er `Parameters.txt` og `vquest_airr.tsv`;
- timeout, avbrudd og delvis resultat gir status, ikke automatisk
  klassifikasjon;
- responsens programversjon, referanserelease og parametere må være til stede;
- endret skjema eller ukjent versjon stopper importen kontrollert.

`ShawHahnLab/vquest` kan brukes som referanse eller isolert avhengighet etter
lisensvurdering. Pakken automatiserer webskjemaet, er AGPL-3.0, støtter bare
AIRR-resultater og har siste publiserte release fra 2022. Den skal derfor ikke
kobles direkte inn uten en kontrakttest mot gjeldende IMGT/V-QUEST.

## Fase 3 – ARResT (implementert)

ARResT bygges som en separat adapter:

- maksimalt 50 fullstendige IG-nukleotidsekvenser og omtrent 100 kB;
- parser for label, SeqCure, subset, confidence og score;
- `unassigned` og `skipped/unhealthy` behandles som resultatverdier;
- borderline/low lagres uendret uten at appen tolker dem;
- adapteren må ta høyde for at ARResT selv bruker IMGT/V-QUEST.

IMGT-resultat for subset 2/8 og ARResT-resultat lagres hver for seg. Ved
uenighet vises begge kildene; appen velger ikke automatisk en vinner.

## GUI og merged-output

Fanen **IMGT og ARResT** skal vise:

- valgte rader og pseudonyme eksterne ID-er;
- status: ikke eksportert, eksportert, importert eller importfeil;
- IMGT-felter og ARResT-felter side om side;
- versjon, referanserelease, tidspunkt og parametere;
- knapper for lokal eksport og import;
- sendeknapper med payload-forhåndsvisning og tydelig mottaker.

I merged-filen beholdes kolonnene:

- `Subset`: bekreftet subset-verdi;
- `Kommentar`: kort kildeangivelse, for eksempel
  `IMGT 3.8.2: productive; ARResT: subset 2, high`.

Fullstendige eksterne resultater lagres i en separat lokal sidecarfil, slik at
merged-arket forblir kompatibelt og sporbarheten ikke komprimeres bort.

## Tester og akseptanse

- Alle automatiske tester bruker publiserte eksempeldata eller konstruerte
  sekvenser.
- Parsere testes mot lagrede, anonymiserte fixtures for gyldig resultat,
  manglende rad, duplikat, endret header, delvis batch og ukjent versjon.
- Ingen nettverk brukes i enhetstester.
- Kontrakttest kjøres manuelt med offentlige IMGT/ARResT-eksempler før hver
  godkjent release.
- Test skal bevise at eksternt payload ikke inneholder interne prøve-ID-er.
- Test skal bevise at resultat fra feil sekvens eller feil kjøring ikke kan
  importeres.
- Merged-eksport skal beholde 22 kolonner, formler og formatering.
- En klinisk pilot sammenlignes med manuell arbeidsflyt og signeres av
  fagansvarlig før funksjonen tas i rutinebruk.

## Foreslått leveranserekkefølge

1. Datamodell, pseudonyme ID-er og sidecarformat. Ferdig.
2. Fane, payload-forhåndsvisning og IMGT AIRR-parser. Ferdig.
3. ARResT-parser og kildebevisst subsetvisning. Ferdig.
4. Kontrakttest med offentlig sekvens mot IMGT 3.8.2 og ARResT. Ferdig.
5. Lokal validering mot historiske, ikke-versjonerte kliniske resultater.
6. Vilkårs- og faglig dokumentasjon.
7. Klinisk pilot og signering før rutinebruk.
