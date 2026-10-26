# Rapportarbeidsbøker og lokal vurdering

Oppdatert 12. oktober 2026 etter gjennomgang av laboratoriets rapport,
Excel-eksempel og kommenterte rapportkopi. Eksemplene brukes som
oppsettreferanser. Huskelapper er ikke analyseresultater.
Kildematerialet lagres utenfor repoet.

## Rapportutvalg og filer

Det eksterne analyseutvalget omfatter fortsatt valgte Leader- og FR1-rader,
uavhengig av funksjonalitet. Rapporten samler FR1 med eksakt subsekvensstøtte
til en valgt Leader med reads ≥2,5 % under denne Leader-rearrangeringen,
også for ufunksjonelle sekvenser. Selvstendige FR1-rader beholdes. Manuelt
valgte lave Leader-rader fjernes ikke i skjul. Dette er presentasjonsgruppering,
ikke klinisk klassifikasjon. Gul funksjonell GUI-gruppering følger Y/Y-reglene.

`analysis.xlsx` beholder merged-formatet med 24 kolonner. Hver prøve får
Word og `*_IGHV_analysis.xlsx` med Oversikt, rearrangeringsfaner og Mal for
Sanger. Oversikt slutter ved rad 8, og ingen celler er fryst. LVMS og de
dupliserte vurderings-/summary-feltene er fjernet. Excel inneholder FASTA,
analyseresultater og én IMGT-tabell med detaljsidens farger. Target fraction
og FR1 support vises igjen i rapporten. Støtteandelen beregnes fra alle
eksakte FR1-støtter i samme prøve, også under analysegrensen; dette endrer
ikke hvilke sekvenser som sendes til analyse.

Ufunksjonelle IMGT-resultater har «(Ufunksjonell)» i fanenavnet, med
opprinnelig FASTA-header uendret. Uavhengige FR1-resultater over grensen
beholder egne faner. Positive påvist-fraser er fete, mens ikke påvist er
vanlig tekst. Nummereringskoordinater bevares, med kortere kildetekst og
linjeskift etter semikolon. Vanlige rader er 15 pt (20 px) og vertikalt
midtjustert. Sanger følger referansens radplasseringer, bredde og skrifter.

IMGTs rå CDR3-lengde (inkludert `X`) skilles fra lengden av returnert
AA-sekvens. AA JUNCTION merkes som junction når CDR3 mangler.
LymphoTrack-versjon redigeres manuelt i Settings; startverdien er 2.4.6.
ARResT/SeqCure-meldinger og full advice hentes fra den separate rapporten,
bindes til eksakt ekstern ID og vises som tekst. Det kreves ikke skjermbilde.
Ved utilgjengelig detaljrapport beholdes hovedresultatet og mangelen merkes.
Lange råd fordeles over flere Excel-rader for å unngå makshøyde på 409 pt.
Rå HTML, URL, hentetid og hash lagres. Originale IMGT-PNG-er bevares;
Excel bruker native beskjæring og større visningsflate.

Revidert 22. oktober: IMGT-sammendraget viser lokalt DIT/prøvenummer i
stedet for ekstern SEQ-ID. Observasjoner og ARResT-notater får linjeskift
etter semikolon. Det dupliserte Comment-feltet utelates uten å flytte
de øvrige feltene. J-genets identitetstekst vises i vanlig svart Calibri.
Junction-bilder har 1463 px visningsbredde, proporsjonal høyde og låst
størrelsesforhold. Reservert plass følger bildehøyden for å unngå overlapp.

Merged-eksportens Comment-kolonne viser bare støtte- og variantforhold,
for eksempel «Støtter Leader-1» og «(Variant av Leader-1)». Usikre
støtteforhold beholder parentesene. De interne analysekommentarene endres
ikke av denne presentasjonsfiltreringen; detaljer finnes i analyse/audit.

Audit bevarer alle analyserte ID-er og oppgir rapporterte/støttende ID-er.
`complete` beholdes for kompatibilitet og betyr IMGT-dekning. Eksplisitte
felter for IMGT, ARResT og bevis synliggjør manglende data. Pakkede
bildehenvisninger bruker lokale filnavn med bevarte hashes.

## Verifikasjon og begrensninger

Regresjoner dekker ufunksjonell sekvensstøtte, kandidatregler, rå CDR3-lengde,
rapportutvalg, separate dekninger, portable bildehenvisninger, bokstavelig
Excel-tekst og filintegritet. UI rendres med syntetiske data ved 1040×720
og 1380×900.

Full ny kjøring 9. oktober hentet 88 nye IMGT- og ARResT-svar og 528 nye
IMGT-bildesnitt. Revideringen 12. oktober bruker disse validerte resultatene
og bildene, med read-only henting av SeqCure-detaljer for begge delanalyser.
ID/sekvenshash, bildehash, kildefil og nye felt kontrolleres ved regenerering.
PDF opprettes ikke ved rapporteksport. Native Excel og Word brukes til
visuell kontroll når Office er tilgjengelig; eventuelle begrensninger
oppgis i testresultatet sammen med filene.
