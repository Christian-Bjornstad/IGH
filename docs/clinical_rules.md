# Kontrollregler i V1

Bare kjøringens kontroller evalueres automatisk. Pasientprøver vurderes
manuelt uten review-varsler fra appen.

Kildegrunnlag gjennomgått lokalt 2026-07-30:

- `HTS - IGHV-SHM (KLL)`, dokument-ID 134367
- `KLL - IGHV mutasjon - Bakgrunn og tolkning`, dokument-ID 38899, versjon 5

## Kontroller

| Filnavn | Betydning | Regel |
|---|---|---|
| `IGH_POS` | IGH-PK | Toppsekvens minst 2,5 % |
| `IGH_SHM_POS` | IGH-SHM | Toppsekvens minst 2,5 % og mutasjonsrate minst 2,0 % |
| `NGS_NEG` | Negativ kontroll | Toppsekvens under 1,0 % |
| `NK` | NTC | Totalt antall reads under 10 000 |

Leader og FR1 evalueres separat. Manglende eller ikke bestått kontroll vises
som kontrollfeil. Prøve-review, unntak, biklonalitet, borderline-resultater
og endelig funksjonalitet håndteres manuelt.

## Operasjonell klongruppering

Appen lager en foreløpig, lokal gruppering for å begrense hvilke
Leader-sekvenser som sendes til IMGT og ARResT:

- Bare rader med `In-frame=Y` og `No Stop codon=Y` kan inngå.
- Leader minst 2,5 % tas med.
- Leader under 2,5 % tas med når en FR1 minst 2,5 % overlapper Leader
  eksakt. FR1-kommentaren settes da i parentes.
- Når samme FR1 overlapper både en Leader over og under 2,5 %, prioriteres
  Leader-raden over terskelen.
- En valgt Leader merkes `Variant av Leader-n` når den har samme V- og
  J-genfamilie, samme lengde, høyst 10 % nukleotidavvik i hele sekvensen og,
  når CDR3 finnes, høyst 15 % avvik i CDR3.

Dette er gruppering og utvalg, ikke automatisk klinisk klassifikasjon.
