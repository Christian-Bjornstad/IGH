# Verifikasjon med ekte data – 9. oktober 2026

Testdata og alle kliniske rapporter ligger utenfor Git. Ingen kliniske
testfiksturer er lagt til i repoet.

## Rådata og brukergrensesnitt

To komplette kjøringer med 24 prøver og 48 råfiler per kjøring ble validert
gjennom MergeService og Qt-knappen for validering. Kjøringene inneholder
381 og 424 rader. Samtlige rådataverdier ble sammenlignet med TSV-kildene;
Excel-eksportene beholder 24 kolonner, sekvenser, prøvebinding og antall reads.
Kontrollreglene ga null feil i begge kjøringer. Utvalg på minst 2,5 % omfatter
henholdsvis 97 og 87 sekvenser. Filtrering bevarer utvalg. FASTA inneholder
tilfeldige eksterne ID-er. Eksisterende filer overskrives ikke uten tillatelse,
og mislykket validering tømmer tidligere tabell og sperrer eksport.

SHA256-kontroll av 234 opprinnelige kildefiler bekreftet uendret innhold.

## Lagrede analyser og ARResT

Septembermaterialet inneholder 88 IMGT-svar og opprinnelig 50 ARResT-svar.
Alle 88 identiteter og rå CDR3-lengder ble sammenlignet direkte med IMGTs
Summary-filer. De manglende 38 sekvensene ble sendt med de eksisterende
tilfeldige ID-ene og hentet fra ARResT. Samtlige 38 ID-er ble returnert.
Fire nye svar var `skipped/unhealthy` uten returnert DNA; de merkes slik,
og får ikke et oppdiktet sekvensverifikasjonsflagg. Returnert DNA ble
hashkontrollert når tilgjengelig. Hele materialet har 13 slike ARResT-svar.

Reavspilling av de ekte TSV-svarene gjennom arbeidskøen og Qt-mottakeren
bekreftet forespørsler på 50 + 38, lagring av hver del og samlet visning av
88 svar. Eksisterende oppdeling ble beholdt. Klienten sperrer nå direkte
forespørsler over 50; nye forsøk sender bare manglende sekvenser og bevarer
tidligere svar også ved ny feil. Fremdrift vises per gruppe.

## Rapportpakke

23 prøvearbeidsbøker, 23 PDF-er og 23 Word-dokumenter ble generert.
58 rearrangeringer rapporteres, og 30 FR1-sekvenser er redegjort for som
støtte til Leader. Alle prøve/ID/sekvens-bindinger og medfølgende bildehashes
ble kontrollert. IMGT- og ARResT-dekning er begge komplette. Bilder følger
bare der de var tilgjengelige: ti bevisoppføringer, med 35 relevante bilder
innebygd i rapportarbeidsbøkene. Manglende bilder er markert.

Alle 23 PDF-er (105 sider) ble åpnet og tekstkontrollert; utvalgte PDF-er og
Excel-faner ble i tillegg rendret og visuelt kontrollert. Word ble struktur-
og innholdskontrollert, men Word-sideinndeling krever Word/LibreOffice som
ikke er tilgjengelig i denne runtime. Rapportene forblir faglige utkast;
vurdering og konklusjon er manuelle.

202 automatiserte tester passerer etter endringene. Regresjoner dekker
gruppegrense, delvis feil, nytt forsøk uten dobbeltinnsending og bevaring
og sammenslåing av tidligere ARResT-svar.
