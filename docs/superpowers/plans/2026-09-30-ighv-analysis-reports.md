# IGHV: IMGT, ARResT, rapporter og grå-lilla grensesnitt

> **Til neste agent:** Bruk `superpowers:executing-plans` og gjennomfør oppgavene nedenfor i rekkefølge. Bruk `ui-ux-pro-max` til grensesnittet. Dette dokumentet er både kravgrunnlag og implementeringsplan. Implementeringen er utsatt til en ny chat etter brukerens ønske.

**Mål:** Gjøre hele arbeidsflyten fra Leader/FR1 til IMGT, ARResT, Excel og rapporter sammenhengende, sporbar og enkel å bruke.

**Arkitektur:** Behold Python/PyQt6-appen og eksisterende adaptere. Skill ut arbeidskø og bilde-/tekstbevis i små moduler fremfor å utvide den allerede store GUI-filen med all logikk. Resultater, bilder og rapporter skal kobles til den samme sekvensen med ekstern ID og sekvenshash.

**Teknologi:** Windows, Python >=3.11, PyQt6, requests, Edge/CDP, openpyxl, python-docx, ReportLab, pytest.

## 1. Overlevering og faktisk status

- Arbeidsmappe: `C:\Users\molpa\Documents\IGH`.
- Repo: https://github.com/Christian-Bjornstad/IGH. MolStat ble nevnt som referanse for install/start, men dette prosjektet er IGH.
- Ny branch er opprettet: `codex/ighv-analysis-reports`.
- Startpunkt: `c29eb34` på `feature/ighv-modern-ui-english`.
- Ingen nye funksjonsendringer er gjennomført på denne branchen. Denne planen er første nye fil.
- Tidligere arbeid har allerede forbedret install/start, hindret endring av kandidat-/run-tilstand under eksterne jobber og flyttet CI til Windows.
- Sist rapporterte teststatus fra forrige arbeid: 98 tester passerte. Dette er historisk status; kjør testene på nytt ved oppstart.
- IMGT via HTTP, ARResT, Edge-skjermbilder og enkle Word/PDF-rapportutkast finnes allerede. De må utvides og gjennomgås, ikke bygges på nytt.
- Eksisterende `docs/clinical_rules.md` og `docs/imgt_arrest_plan.md` beskriver eldre Leader/Y-Y-utvalg. Nytt brukerkrav nedenfor overstyrer dette utvalget.
- `requirements.txt` har en bevisst femlinjers kontrakt for sykehusmiljøet. Øvrige kjøretidsavhengigheter installeres fra `pyproject.toml`; ikke endre kontrakten uten å undersøke testene og installflyten.

## 2. Bekreftede krav

1. **Alle Leader og FR1 med reads >=2,5 % skal foreslås til IMGT**, også når de ikke er produktive. Dette er brukerens eksplisitte avklaring. Eksisterende funksjonell gulmerking må ikke styre hvem som får analyseres.
2. Reads >=2,5 % skal være tydelig med fet skrift. Grensen gjelder også nøyaktig 2,5 %.
3. IMGT-locus er IGH. Molekyltype er normalt gDNA. Et cDNA-token i prøvenavnet, uavhengig av store/små bokstaver, gir cDNA.
4. Behold den raske HTTP-integrasjonen som eget valg. Bilde-/tekstinnhenting via IMGT skal også være tilgjengelig.
5. Hent bilde av hele den gule oppsummeringen og seksjonene 1–6 og 9. Manglende valgfrie seksjoner skal forklares, ikke gi misvisende tomme bilder.
6. Hent hele oppsummeringen som kopierbar tekst i tillegg til bilde.
7. Vis GxG og J-TRP som **observasjoner til manuell vurdering**; ingen automatisk subsetklassifisering.
8. Vis alternative J-kall merket `(a)` tydelig. IGHJ5*03 skal fremheves rødt med forklarende tekst om pseudogenet; verifiser allelets status mot IMGT før regelen implementeres.
9. Når IMGT viser to identitetsverdier, ønsker brukeren den høyre verdien for en produktiv rearrangering. Behold begge råverdier og forklar hvilken som vises; ikke velg bare det laveste tallet vilkårlig.
10. Kontrollrekkefølgen i Excel skal være `IGH_SHM_POS`, `IGH_POS`, `NGS_NEG`, `NK`. Dette er allerede modellert; behold og test det.
11. Samme eksterne søke-ID skal følge kandidaten gjennom IMGT, ARResT, Excel, lokale bevis og rapporter. Prøvenavn skal bare finnes i den lokale koblingen.
12. ARResT skal få robust feilhåndtering og verifiserte alternative endepunkter/stasjoner dersom tjenesten faktisk tilbyr det.
13. Rapporter skal kunne produseres som Word/PDF med tilhørende Excel og relevante IMGT-bilder/tekst. De skal være ferdig utfylt med tilgjengelige resultater, med plass til faglig vurdering.
14. Profesjonelt, ryddig grå-lilla grensesnitt. Fjern slogans, dekorative statusfraser og unødvendig tekst. Behold nyttig informasjon om handling, kilde og status.

## 3. Uavklart IMGT-arbeidsflyt

Brukeren husker ikke feltnavnet som skal settes til «no» ved ny analyse av insertion/deletion, eller hva «B» betyr. Instruksjonen er å undersøke selv; hvis det ikke kan avklares, kan dette tas senere.

- Offisiell IMGT-dokumentasjon har en **B. Synthesis view**, men dette bekrefter ikke at brukerens «B» er det samme valget.
- Undersøk faktisk skjema, parameternavn og offisielle beskrivelser med offentlige eksempeldata.
- Ikke gjett hvilket felt som skal være «no». Ikke legg inn automatisk reanalyse eller automatisk funksjonalitetsavgjørelse på denne antakelsen.
- Ønsket arbeidsflyt er samlet analyse av varianter av samme gen/rearrangering, og bilder av summary table, nr. 1 og nr. 8. Genlikhet alene er ikke tilstrekkelig til å slå sammen rearrangeringer; brukeren må kunne kontrollere gruppen.
- Hvis valgene verifiseres: lag et separat manuelt startet reanalysevalg med synlige parametre, ny analysehistorikk og lenke til originalen. Hvis ikke: dokumenter konkret hva som mangler og lever de øvrige kravene.

### Faglige presiseringer som skal være synlige

- IMGT-posisjonene 119–121 for G-X-G er **aminosyreposisjoner**, ikke baseparposisjoner. J-TRP/J-PHE er ved posisjon 118. Ikke søk på rå nukleotidoffset 119–121.
- Dokumentasjonen beskriver en identitet med indel-hendelser der hver insertion/deletion teller som én hendelse. Verifiser at dette er den høyre verdien i den aktuelle resultatvisningen før den normaliseres.
- Hvis nummerert IMGT-translasjon mangler, vis «ikke vurdert» for motivet. En tilfeldig GxG et annet sted skal ikke gi en positiv observasjon.

**Referanser til kontroll ved implementering:**

- [IMGT/V-QUEST brukerveiledning](https://www.imgt.org/IMGT_vquest/user_guide)
- [IMGT Education: junction og nummerering](https://www.imgt.org/IMGTeducation/QuestionsAnswers/index.php?article=lesson4&lang=UK)
- [ARResT sentral inngang](https://arrest.tools/)
- [AssignSubsets på bat.infspire.org](https://bat.infspire.org/arrest/assignsubsets/)

En sentral side eller omdirigering beviser ikke at den er et selvstendig reserveendepunkt for POST. Verifiser skjemaets action og mottaker før bruk.

## 4. Globale føringer

- Bruk brukerens nye utvalgskrav i stedet for eldre Leader/Y-Y-utvalg.
- Behold opprinnelige LymphoTrack-felt. IMGT-identitet skal ikke overskrive rå identitet fra kildedata.
- Behold separat IMGT- og ARResT-kilde ved subsetfunn og uenighet.
- Eksternt innhold er kun pseudonym ID og sekvens. Lokal kobling, råresultater og rapporter lagres utenfor Git.
- Behold nyttig payload-preview og aktiv brukerstart; ikke legg til gjentatte godkjenningsspørsmål under utvikling.
- Ingen TLS-nedgradering. Retry skal være begrenset og bruke samme payload; formatfeil, feil ID eller feil hash er ikke retrygrunn.
- Nye bakgrunnsjobber skal håndtere tilstand og Qt-tråder trygt. UI skal ikke fryse under bildeinnhenting.
- Ikke bruk ekte pasientdata i tester, Git, skjermbilder for utvikling eller tjenestetester.
- Bruk eksisterende branch. Ikke opprett ny chat eller nye agenter uten passende autorisasjon.

## 5. Implementeringsoppgaver

### Oppgave 1: Korrekt utvalg, molekyltype og stabil kobling

**Filer:** `src/igh_merge/candidates.py`, `io.py`, `models.py`, `external.py`, `gui.py`, `excel.py`; `tests/test_external.py`, `test_gui.py`, `test_redesign_features.py` og relevante Excel-tester.

**Grensesnitt:** Legg til `analysis_candidate_indices(rows: Sequence[MergedRow]) -> frozenset[int]`. Behold funksjonell gruppeberegning separat. `create_external_batch` skal gjenbruke en gyldig eksisterende ekstern ID for samme rad/sekvens og sette ID på lokal rad før Excel-eksport.

- [ ] Skriv tester for Leader og FR1 ved 2,49 / 2,50 / 2,51 %, inklusive Y/N og N/N. Test at GUI tilbyr begge targets og velger alle over grensen.
- [ ] Test cDNA-token med store/små bokstaver og vanlige skilletegn. Et innebygd ord som `acdnab` skal fortsatt gi gDNA.
- [ ] Test at ID er stabil når utvalget endres, mens endret sekvens ikke får arve gamle resultater. Avvis duplikate/ugyldige ID-er.
- [ ] Implementer ny utvalgslogikk og fet skrift. Kontroller avrunding før grensesammenligning; 2,499 skal ikke bli valgt bare fordi UI viser 2,50.
- [ ] La FASTA, Excel, lokal koblingsfil og rapportmodell bruke samme ID. Ta med molekyltype i koblingsfilen.
- [ ] Kjør målrettede tester, oppdater eldre dokumentasjon og commit denne delen.

### Oppgave 2: Arbeidskø, blandede molekyltyper og tabellstatus

**Filer:** Ny `src/igh_merge/analysis_jobs.py`; `external.py`, `gui.py`; ny `tests/test_analysis_jobs.py` og `tests/test_gui.py`.

**Grensesnitt:** `partition_imgt_batch(batch: ExternalBatch, max_sequences: int = 50) -> tuple[ExternalBatch, ...]`. Hver underbatch har én molekyltype. Den samlede jobben beholder én lokal kobling og status per ID.

- [ ] Test 51 ulike sekvenser og blandet gDNA/cDNA. Sikre ingen tap, duplikater eller ny ID ved oppdeling.
- [ ] Test delvis feil: ferdige resultater bevares, mislykkede kandidater får tydelig status, rapporter presenteres ikke som komplette.
- [ ] Implementer sekvensiell, begrenset oppdeling etter faktisk tjenestekapasitet. Behold separate råresultater og metadata per delanalyse.
- [ ] Rett feil kolonneindekser i `_refresh_external_table`; reads, IMGT, ARResT og subset skal forbli i riktig kolonne.
- [ ] Nullstill rapport-/bildeknapper og resultattilstand ved nytt run. Gjenbruk eksisterende låsing under aktive jobber.
- [ ] Kjør tester og commit.

### Oppgave 3: IMGT-tolkning og manuelle observasjoner

**Filer:** `external.py`; ny `src/igh_merge/imgt_observations.py`; `gui.py`, `reports.py`; parser- og observasjonstester.

**Grensesnitt:** Utvid `ImgtRecord` med separate rå identitetsverdier, identitet med indel-hendelser og kildeinformasjon. Legg til en entydig `selected_identity_percent`-egenskap. Observasjoner har status «påvist», «ikke påvist» eller «ikke vurdert» med kilde.

- [ ] Lag offentlig/syntetisk fixture med to identitetsverdier og produktiv/ikke-produktiv rearrangering. Test at begge råverdier bevares og valgt verdi følger det bekreftede kravet.
- [ ] Verifiser kolonnenavn og tekstvisning mot IMGT. Avvis uleselige verdier fremfor å tolke dem som null.
- [ ] Test alternativt J-kall `(a)` og IGHJ5*03 blant flere kall; behold full råtekst.
- [ ] Test nummerert W/F ved 118 og G-X-G ved 119–121, gap og manglende nummerering. Ingen automatisk subsetavgjørelse.
- [ ] Vis valgt identitet, kilde, alternative kall og observasjoner i UI og rapportmodell. Pseudogen skal ha tekst i tillegg til rødt.
- [ ] Kjør tester og commit.

### Oppgave 4: Verifisert ARResT-reserve og feilhåndtering

**Filer:** `external.py`, `analysis_jobs.py`, `gui.py`; `tests/test_external.py`.

**Grensesnitt:** `ArrestClient` får eksplisitt, verifisert endepunktliste. Resultat/audit lagrer brukt endepunkt og forsøk, uten klinisk payload i logger.

- [ ] Undersøk sentral AssignSubsets-side og gjeldende form-action med GET. Dokumenter hvilke alternative mottakere som faktisk støttes.
- [ ] Test timeout/5xx og reserve med samme payload; test at schema-/ID-/hashfeil og TLS-feil ikke utløser blind gjentakelse.
- [ ] Implementer begrenset retry/failover for verifiserte endepunkter, HTTPS og tillatte resultatdomener. Dersom ingen uavhengig reserve finnes, gi tydelig feil og mulighet for ny brukerstart.
- [ ] Behold IMGT- og ARResT-subset separat og vis «unassigned» som et reelt resultat.
- [ ] Kjør tester og commit.

### Oppgave 5: IMGT-bilder, full tekst og visning

**Filer:** `edge_cdp.py`; nye `src/igh_merge/evidence.py`, `evidence_ui.py`; `analysis_jobs.py`, `gui.py`; relevante Edge-tester og nye evidenstester.

**Grensesnitt:** `capture_imgt_evidence` beholder eksisterende seksjonskontrakt. Ny manifestmodell kobler filer til session-ID, ekstern ID, sekvenshash, parametre og tidspunkt. GUI-leseren viser bilde og kopierbar tekst.

- [ ] Test manifestkobling og avvisning av bilder fra feil sekvens eller session. Test hele summary-teksten, ikke bare første linje.
- [ ] Koble eksisterende `extract_imgt_text` til lagring av tekst/JSON sammen med summary og seksjoner 1–6 og 9.
- [ ] Kjør capture i QThread-jobb med fremdrift og tydelig feil per kandidat. Ikke blokker GUI under nettleserarbeid.
- [ ] Legg til en resultatsvisning med kopierbar full tekst, bildevalg og lenke til lagringsmappe. Behold rask HTTP-analyse som eget valg.
- [ ] Test valgfrie manglende seksjoner og feil underveis uten å slette allerede hentet bevis.
- [ ] Verifiser faktisk bildeavgrensning med offentlig IMGT-eksempel. Kjør tester og commit.

### Oppgave 6: Samlet reanalyse av varianter, hvis verifisert

**Filer:** `edge_cdp.py`, `imgt_observations.py`, `evidence.py`, `gui.py`; nye kontrakt-/arbeidsflyttester.

- [ ] Finn og dokumenter faktisk «no»-parameter og om «B» betyr Synthesis view. Bruk offentlige eksempler.
- [ ] Hvis bekreftet: test manuelt valgt variantgruppe, felles pseudonymisert payload, eksplisitt parameter og bilder summary/1/8. Behold kobling fra hver variant til hver resultatrad.
- [ ] Implementer egen brukerstartet reanalyse uten å overskrive den første analysen.
- [ ] Hvis ikke bekreftet: dokumenter begrensningen og utsett denne oppgaven. De andre leveransene skal fortsatt ferdigstilles.

### Oppgave 7: Rapportpakke med Excel og IMGT-bevis

**Filer:** `reports.py`, `excel.py`, `evidence.py`, `gui.py`; `tests/test_reports.py` og relevante Excel-tester.

**Grensesnitt:** Utvid rapportgenereringen med et valgfritt validert evidensmanifest og tilhørende Excel-eksport. Pakken inneholder Word, PDF, Excel og lokal oversikt over inkluderte analyser/bevis.

- [ ] Test flere rearrangeringer og begge targets for samme prøve; riktig target/rank må følge hver sekvens. `Leader-1` må ikke feilaktig treffe `Leader-10`.
- [ ] Test identisk ekstern ID i Word/PDF/Excel og at feil hash/session avviser bevis.
- [ ] Rett PDF-bygging inne i løkke, escape tekst for ReportLab, bruk cellebryting og sikre unike filnavn/utdatamapper ved navnekollisjoner.
- [ ] Inkluder resultatsammendrag, full kopierbar IMGT-summary, relevante bilder, begge subsetkilder, metadata og plass til faglig vurdering. Marker manglende analyse/bevis tydelig.
- [ ] Vis at rapporten er et utkast til faglig godkjenning uten dekorativ eller overdreven advarselstekst.
- [ ] Generer en syntetisk rapportpakke og inspiser Word/PDF visuelt med dokument-/PDF-ferdighetene. Test kontrollrekkefølge og 24 Excel-kolonner.
- [ ] Kjør tester og commit.

### Oppgave 8: Profesjonell grå-lilla UI

**Filer:** `gui.py`, `evidence_ui.py`, eventuelt ny `src/igh_merge/theme.py`; `tests/test_gui.py` og designdokumentasjon.

**Grensesnitt:** Ett sett temaverdier for nøytrale grå flater, lilla aksent, mørk tekst, fokus og semantiske statusfarger. Ingen endring av klinisk mening for eksisterende Excel-farger.

- [ ] Les `C:\Users\molpa\.codex\skills\ui-ux-pro-max\SKILL.md` og bruk relevante desktop-prinsipper. Brukerens grå-lilla retning overstyrer automatisk foreslåtte paletter.
- [ ] Samle harde fargeverdier, begrens pynt, rydd hierarki/luft og fjern slogans som «LOCAL AND TRACEABLE» der de ikke tilfører informasjon.
- [ ] Gi kandidatlisten søk/filtrering etter prøve og target, tydelig utvalgsteller, lesbare kolonner og separate tjenestestatusfelt.
- [ ] Sikre tastaturfokus, kontrast, respons ved vindusendring og at viktig tekst ikke bare formidles med farge. Ikke vis implementeringsdetaljer i ordinære produkttekster.
- [ ] Verifiser syntetisk run og resultatsvisning i Qt, inklusive liten vindusstørrelse og lange prøvenavn. Lag lokale QA-skjermbilder utenfor Git og inspiser dem.
- [ ] Kjør GUI-tester og commit.

### Oppgave 9: Review, install/start og push

**Filer:** hele endringsdiffen, `README.md`, `docs/clinical_rules.md`, `docs/imgt_arrest_plan.md`, install-/startfilene ved behov.

- [ ] Gjennomgå kode for tilstandsfeil, feil kobling, parserantakelser, trådlivsløp, rapportformat og lekkasje av lokale prøveopplysninger.
- [ ] Kjør `.\.venv\Scripts\python.exe -m pytest -q` fra repoet. Kontroller exitkode og faktisk output.
- [ ] Gjør en realistisk install/start-smoketest uten å endre sykehusets dependency-kontrakt. Skil mellom den lokale repo-kopien og en eventuell eldre K:-kopi.
- [ ] Verifiser med offentlig eksempel at HTTP-resultat og Edge-bevis peker til samme ID/sekvens; ingen pasientdata sendes under utvikling.
- [ ] Oppdater docs med det som faktisk er levert og eventuelle uavklarte «no»/«B»-valg.
- [ ] Sjekk `git diff --check`, status og staged filer for kliniske data eller lokale miljøfiler.
- [ ] Commit resterende endringer og push `codex/ighv-analysis-reports` med upstream. Brukerens tidligere ønske er push etter ferdig arbeid; ikke merge til hovedbranch automatisk.
- [ ] Oppsummer hva som er klart for brukerens testing, testresultater og konkrete begrensninger.

## 6. Review-fokus på tvers av oppgavene

| Risiko | Forventet håndtering | Oppgave |
|---|---|---|
| Nytt run/utvalg mens jobb er aktiv | Stabil kobling, låste endringskontroller, ingen stale rapporter | 1–2 |
| Flere molekyltyper og >50 kandidater | Korrekt oppdeling uten sekvenstap, synlig delvis feil | 2 |
| IMGT endrer format eller seksjoner mangler | Kontrollert importfeil/ikke vurdert, ingen gjetting | 3, 5 |
| Reserve gir feil ID eller annet resultatdomene | Avvis resultat, ingen blind retry eller TLS-nedgradering | 4 |
| Lange navn, flere rearrangeringer og gamle bilder | Lesbare rapporter og UI, entydig ID/hash/session | 5, 7–8 |

## 7. Startmelding som kan limes inn i ny chat

> Fortsett IGH-prosjektet i `C:\Users\molpa\Documents\IGH` på eksisterende branch `codex/ighv-analysis-reports`. Les og gjennomfør `docs/superpowers/plans/2026-09-30-ighv-analysis-reports.md`. Alle Leader og FR1 >=2,5 % skal tilbys IMGT, også ikke-produktive. Behold rask HTTP-analyse, lag IMGT-bilder og kopierbar summary, stabil ID-kobling til Excel og rapporter, robust ARResT og profesjonell grå-lilla UI med ui-ux-pro-max. GxG/J-TRP er kun manuelle observasjoner. Undersøk «no»/«B»; utsett akkurat den delen hvis den ikke kan verifiseres. Gjør kode-review, nødvendige tester og push branchen når arbeidet er klart. Planen er laget, funksjonene er ennå ikke implementert.
