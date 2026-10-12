from __future__ import annotations

import csv
import hashlib
import io
import math
import json
import os
import re
import secrets
import tempfile
import zipfile
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urljoin, urlparse

from .tls import configure_system_trust_store

configure_system_trust_store()

import requests

from .models import MergedRow
from .privacy import ensure_outside_git

IMGT_URL = "https://www.imgt.org/IMGT_vquest/analysis"
# Verified 2026-09-30 from the AssignSubsets form action. Station3/Subsets
# is a Shiny application, not a compatible CGI reserve.
ARREST_URL = "https://bat.infspire.org/cgi-bin/arrest/assignsubsets_html.pl"
ARREST_ENDPOINTS = (ARREST_URL,)
MAX_BATCH_SIZE = 50
MAX_RESPONSE_BYTES = 25_000_000
IUPAC_NUCLEOTIDES = frozenset("ACGTRYSWKMBDHVN")


class ExternalAnalysisError(RuntimeError):
    """External analysis did not respond with a safe, expected result."""


def _tls_error(service: str, exc: requests.exceptions.SSLError) -> ExternalAnalysisError:
    return ExternalAnalysisError(
        f"Could not contact {service} because the HTTPS certificate could not "
        "be verified against Windows' certificate store. Run INSTALL PACKAGES "
        "command again after the latest update. If the error persists, "
        "IT must check that the organization's proxy-/Ivanti-root certificate is in "
        f"Windows Trusted Root Certification Authorities. Details: {exc}"
    )


def normalize_sequence(sequence: str) -> str:
    normalized = "".join(sequence.split()).upper()
    if not normalized:
        raise ValueError("Sequence is empty")
    invalid = sorted(set(normalized) - IUPAC_NUCLEOTIDES)
    if invalid:
        raise ValueError(f"Sequence contains invalid characters: {''.join(invalid)}")
    return normalized


def sequence_sha256(sequence: str) -> str:
    return hashlib.sha256(normalize_sequence(sequence).encode("ascii")).hexdigest()


@dataclass(frozen=True)
class ExternalCandidate:
    external_id: str
    row_index: int
    sample: str
    target: str
    molecule_type: str
    rank: int
    sequence: str
    sequence_sha256: str


@dataclass(frozen=True)
class ExternalBatch:
    session_id: str
    run_date: str
    created_at: str
    candidates: tuple[ExternalCandidate, ...]

    @property
    def fasta(self) -> str:
        return "".join(
            f">{candidate.external_id}\n{candidate.sequence}\n"
            for candidate in self.candidates
        )

    @property
    def candidate_ids(self) -> tuple[str, ...]:
        return tuple(candidate.external_id for candidate in self.candidates)

    def by_id(self) -> dict[str, ExternalCandidate]:
        return {candidate.external_id: candidate for candidate in self.candidates}


def create_external_batch(
    run_date: str,
    selected_rows: Iterable[tuple[int, MergedRow]],
) -> ExternalBatch:
    selected = list(selected_rows)
    if not selected:
        raise ValueError("Velg minst én sekvens")

    candidates: list[ExternalCandidate] = []
    used_ids: set[str] = set()
    seen_rows: set[int] = set()
    for row_index, row in selected:
        if row_index in seen_rows:
            raise ValueError("duplicate row index")
        seen_rows.add(row_index)
        sequence = normalize_sequence(row.source.sequence)
        digest = sequence_sha256(sequence)
        external_id = row.external_id
        if external_id and not re.fullmatch(r"SEQ-[A-F0-9]{6,24}", external_id):
            raise ValueError("Invalid external ID")
        if external_id and external_id in used_ids:
            raise ValueError("duplicate external ID")
        if row.external_sequence_sha256 and row.external_sequence_sha256 != digest:
            external_id = ""
        while not external_id or external_id in used_ids:
            external_id = f"SEQ-{secrets.token_hex(6).upper()}"
        used_ids.add(external_id)
        candidates.append(
            ExternalCandidate(
                external_id=external_id,
                row_index=row_index,
                sample=row.sample,
                target=row.target,
                molecule_type=row.molecule_type,
                rank=row.source.rank,
                sequence=sequence,
                sequence_sha256=sequence_sha256(sequence),
            )
        )
    # Validate the whole selection before updating local rows.
    for (_, row), candidate in zip(selected, candidates):
        if row.external_sequence_sha256 and row.external_sequence_sha256 != candidate.sequence_sha256:
            row.subset = ""
            row.comment = " | ".join(part for part in row.comment.split(" | ")
                                     if not part.startswith(("IMGT ", "ARResT:")))
        row.external_id = candidate.external_id
        row.external_sequence_sha256 = candidate.sequence_sha256
    return ExternalBatch(
        session_id=secrets.token_hex(8).upper(),
        run_date=run_date,
        created_at=datetime.now(timezone.utc).isoformat(),
        candidates=tuple(candidates),
    )


@dataclass(frozen=True)
class ImgtRecord:
    external_id: str
    productive: bool | None
    stop_codon: bool | None
    vj_in_frame: bool | None
    v_call: str
    d_call: str
    j_call: str
    v_identity_percent: float | None
    junction: str
    junction_aa: str
    insertions: str
    deletions: str
    cll_subset: str
    functionality: str = ""
    functionality_comment: str = ""
    v_identity_numerator: int | None = None
    v_identity_denominator: int | None = None
    cdr3_aa: str = ""
    cdr3_aa_length: int | None = None
    junction_aa_length: int | None = None
    junction_frame: str = ""
    orientation: str = ""
    potential_indel: str = ""
    sequence_category: str = ""
    analyzed_length: int | None = None
    raw_identity_percent: str = ""
    raw_identity_with_indel_events: str = ""
    identity_with_indel_events: float | None = None
    identity_source: str = "IMGT AIRR v_identity"
    numbered_aa: tuple[tuple[int, str], ...] = ()
    numbered_aa_source: str = ""
    identity_with_indel_numerator: int | None = None
    identity_with_indel_denominator: int | None = None
    raw_cdr3_imgt_length: str = ""

    @property
    def selected_identity_percent(self) -> float | None:
        if self.productive is True and self.identity_with_indel_events is not None:
            return self.identity_with_indel_events
        return self.v_identity_percent

    @property
    def selected_identity_source(self) -> str:
        if self.productive is True and self.identity_with_indel_events is not None:
            return 'IMGT V-REGION identity % (with ins/del events); right/bracketed value'
        return self.identity_source

    @property
    def selected_identity_counts(self) -> tuple[int | None, int | None]:
        if self.productive is True and self.identity_with_indel_events is not None:
            return self.identity_with_indel_numerator, self.identity_with_indel_denominator
        return self.v_identity_numerator, self.v_identity_denominator


@dataclass(frozen=True)
class ImgtBatchResult:
    parameters: dict[str, str]
    records: tuple[ImgtRecord, ...]
    raw_parameters: str
    raw_airr: str
    raw_files: dict[str, str] = field(default_factory=dict)

    @property
    def program_version(self) -> str:
        return self.parameters.get("IMGT/V-QUEST program version", "")

    @property
    def reference_release(self) -> str:
        return self.parameters.get("IMGT/V-QUEST reference directory release", "")


@dataclass(frozen=True)
class ArrestRecord:
    external_id: str
    seqcure: str
    subset: str
    nearest_subset: str
    confidence: str
    score: str
    functionality: str
    v_call: str
    v_identity_percent: float | None
    j_call: str
    d_call: str
    junction_aa: str
    imgt_date: str
    imgt_version: str
    reference_release: str
    indel_search: str
    sequence_verified: bool
    seqcure_messages: tuple[str, ...] = ()
    seqcure_advice: tuple[str, ...] = ()
    seqcure_report_url: str = ""
    seqcure_details_status: str = ""


@dataclass(frozen=True)
class ArrestBatchResult:
    records: tuple[ArrestRecord, ...]
    raw_tsv: str
    results_url: str
    endpoint: str = ""
    attempts: int = 1
    raw_response_html: str = ""
    raw_seqcure_html: str = ""
    seqcure_report_url: str = ""
    seqcure_details_error: str = ""
    seqcure_retrieved_at: str = ""


def _bool_value(value: str | None) -> bool | None:
    if value is None or not value.strip():
        return None
    normalized = value.strip().lower()
    if normalized in {"t", "true", "yes", "y"}:
        return True
    if normalized in {"f", "false", "no", "n"}:
        return False
    return None


def _float_value(value: str | None) -> float | None:
    if value is None or not value.strip():
        return None
    try:
        return float(value.replace(",", "."))
    except ValueError:
        return None


def _identity_percent(value: str | None) -> float | None:
    parsed = _float_value(value)
    if parsed is None:
        return None
    return parsed * 100 if 0 <= parsed <= 1 else parsed


def _strict_identity(value: str | None, *, fraction: bool = False) -> float | None:
    if not value or not value.strip():
        return None
    parsed = _float_value(value)
    if parsed is None or not math.isfinite(parsed) or not 0 <= parsed <= (1 if fraction else 100):
        raise ValueError('Unreadable IMGT identity value')
    return parsed * 100 if fraction else parsed


def _validate_response_size(content: bytes) -> None:
    if len(content) > MAX_RESPONSE_BYTES:
        raise ExternalAnalysisError("The service returned an unexpectedly large response")


def _parse_parameters(text: str) -> dict[str, str]:
    parameters: dict[str, str] = {}
    for row in csv.reader(io.StringIO(text), delimiter="\t"):
        if len(row) >= 2 and row[0].strip():
            parameters[row[0].strip()] = row[1].strip()
    return parameters


def _validate_ids(
    observed_ids: Iterable[str],
    batch: ExternalBatch,
    service: str,
) -> None:
    observed = list(observed_ids)
    expected = list(batch.candidate_ids)
    if len(observed) != len(set(observed)):
        raise ExternalAnalysisError(f"{service} returned duplicate external IDs")
    if set(observed) != set(expected):
        missing = sorted(set(expected) - set(observed))
        extra = sorted(set(observed) - set(expected))
        raise ExternalAnalysisError(
            f"{service} result does not match the batch "
            f"(missing {len(missing)}, extra {len(extra)})"
        )


def parse_imgt_result(
    raw_parameters: str,
    raw_airr: str,
    batch: ExternalBatch,
) -> ImgtBatchResult:
    reader = csv.DictReader(io.StringIO(raw_airr), delimiter="\t")
    required = {
        "sequence_id",
        "sequence",
        "productive",
        "stop_codon",
        "vj_in_frame",
        "v_call",
        "d_call",
        "j_call",
        "v_identity",
        "junction",
        "junction_aa",
        "insertions",
        "deletions",
        "cll_subset",
    }
    if reader.fieldnames is None or not required.issubset(reader.fieldnames):
        missing = sorted(required - set(reader.fieldnames or ()))
        raise ExternalAnalysisError(f"IMGT AIRR is missing columns: {', '.join(missing)}")

    candidates = batch.by_id()
    records: list[ImgtRecord] = []
    observed_ids: list[str] = []
    for row in reader:
        external_id = (row.get("sequence_id") or "").strip()
        if not external_id:
            raise ExternalAnalysisError("IMGT AIRR inneholder en rad uten sequence_id")
        observed_ids.append(external_id)
        candidate = candidates.get(external_id)
        returned_sequence = row.get("sequence") or ""
        if candidate is None or sequence_sha256(returned_sequence) != candidate.sequence_sha256:
            raise ExternalAnalysisError(
                f"IMGT-resultatet for {external_id} har en annen sekvens enn den sendte"
            )
        records.append(
            ImgtRecord(
                external_id=external_id,
                productive=_bool_value(row.get("productive")),
                stop_codon=_bool_value(row.get("stop_codon")),
                vj_in_frame=_bool_value(row.get("vj_in_frame")),
                v_call=(row.get("v_call") or "").strip(),
                d_call=(row.get("d_call") or "").strip(),
                j_call=(row.get("j_call") or "").strip(),
                v_identity_percent=_strict_identity(row.get("v_identity"), fraction=True),
                raw_identity_percent=row.get("v_identity") or "",
                junction=(row.get("junction") or "").strip(),
                junction_aa=(row.get("junction_aa") or "").strip(),
                insertions=(row.get("insertions") or "").strip(),
                deletions=(row.get("deletions") or "").strip(),
                cll_subset=(row.get("cll_subset") or "").strip(),
            )
        )
    _validate_ids(observed_ids, batch, "IMGT")
    parameters = _parse_parameters(raw_parameters)
    if not parameters.get("IMGT/V-QUEST program version"):
        raise ExternalAnalysisError("IMGT Parameters.txt is missing the program version")
    if not parameters.get("IMGT/V-QUEST reference directory release"):
        raise ExternalAnalysisError("IMGT Parameters.txt is missing the reference release")
    return ImgtBatchResult(parameters, tuple(records), raw_parameters, raw_airr)


def _int_value(value: str | None) -> int | None:
    try:
        return int((value or "").strip())
    except ValueError:
        return None


def _identity_counts(value: str) -> tuple[int | None, int | None]:
    match = re.search(r"(\d+)\s*/\s*(\d+)", value)
    return (
        (int(match.group(1)), int(match.group(2)))
        if match
        else (None, None)
    )


def parse_imgt_full_result(
    raw_files: dict[str, str], batch: ExternalBatch
) -> ImgtBatchResult:
    required = {"1_Summary.txt", "5_AA-sequences.txt", "11_Parameters.txt"}
    if not required.issubset(raw_files):
        raise ExternalAnalysisError(
            "IMGT full result is missing: " + ", ".join(sorted(required - raw_files.keys()))
        )
    summaries = list(
        csv.DictReader(io.StringIO(raw_files["1_Summary.txt"]), delimiter="\t")
    )
    aa_by_id = {
        (row.get("Sequence ID") or "").strip(): row
        for row in csv.DictReader(
            io.StringIO(raw_files["5_AA-sequences.txt"]), delimiter="\t"
        )
    }
    numbered_rows = list(csv.DictReader(io.StringIO(raw_files.get('4_IMGT-gapped-AA-sequences.txt', '')), delimiter='\t'))
    numbered_ids = [row.get('Sequence ID', '') for row in numbered_rows]
    if len(numbered_ids) != len(set(numbered_ids)) or not set(numbered_ids).issubset(batch.candidate_ids):
        raise ExternalAnalysisError('IMGT numbered amino acid IDs do not match the batch')
    numbered_by_id = {row['Sequence ID']: row for row in numbered_rows}
    candidates = batch.by_id()
    records: list[ImgtRecord] = []
    observed: list[str] = []
    for row in summaries:
        external_id = (row.get("Sequence ID") or "").strip()
        observed.append(external_id)
        candidate = candidates.get(external_id)
        returned_sequence = row.get("Sequence") or ""
        if candidate is None or sequence_sha256(returned_sequence) != candidate.sequence_sha256:
            raise ExternalAnalysisError(
                f"IMGT-resultatet for {external_id} har en annen sekvens enn den sendte"
            )
        functionality = (row.get("V-DOMAIN Functionality") or "").strip()
        lower = functionality.lower()
        productive = (
            True
            if lower.startswith("productive")
            else False
            if lower.startswith("unproductive")
            else None
        )
        junction_frame = (row.get("JUNCTION frame") or "").strip()
        numerator, denominator = _identity_counts(
            row.get("V-REGION identity nt") or ""
        )
        event_numerator, event_denominator = _identity_counts(row.get('V-REGION identity nt (with ins/del events)') or '')
        aa_row = aa_by_id.get(external_id, {})
        cdr3_aa = (aa_row.get("CDR3-IMGT") or "").strip()
        fr4 = (numbered_by_id.get(external_id, {}).get('FR4-IMGT') or '').strip().upper()
        # IMGT labels FR4 as AA 118–128. Only its first four explicit
        # positions are required; unknown/gap characters remain unknown.
        numbered = tuple(enumerate(fr4[:4], start=118)) if fr4 else ()
        records.append(
            ImgtRecord(
                external_id=external_id,
                productive=productive,
                stop_codon=None,
                vj_in_frame=True if junction_frame.lower() == 'in-frame' else False if junction_frame.lower() == 'out-of-frame' else None,
                v_call=(row.get("V-GENE and allele") or "").strip(),
                d_call=(row.get("D-GENE and allele") or "").strip(),
                j_call=(row.get("J-GENE and allele") or "").strip(),
                v_identity_percent=_strict_identity(row.get("V-REGION identity %")),
                raw_identity_percent=row.get("V-REGION identity %") or "",
                raw_identity_with_indel_events=row.get("V-REGION identity % (with ins/del events)") or "",
                identity_with_indel_events=_strict_identity(row.get("V-REGION identity % (with ins/del events)")),
                identity_source="IMGT 1_Summary.txt V-REGION identity %",
                numbered_aa=numbered,
                numbered_aa_source='IMGT 4_IMGT-gapped-AA-sequences.txt FR4-IMGT (AA 118–121)' if numbered else '',
                junction="",
                junction_aa=(row.get("AA JUNCTION") or "").strip(),
                insertions=(row.get("V-REGION insertions") or "").strip(),
                deletions=(row.get("V-REGION deletions") or "").strip(),
                cll_subset=(row.get("CLL subset") or "").strip(),
                functionality=functionality,
                functionality_comment=(
                    row.get("V-DOMAIN Functionality comment") or ""
                ).strip(),
                v_identity_numerator=numerator,
                v_identity_denominator=denominator,
                identity_with_indel_numerator=event_numerator,
                identity_with_indel_denominator=event_denominator,
                cdr3_aa=cdr3_aa,
                cdr3_aa_length=len(cdr3_aa) if cdr3_aa else None,
                junction_aa_length=_int_value(row.get("CDR3-IMGT length")),
                raw_cdr3_imgt_length=row.get("CDR3-IMGT length") or "",
                junction_frame=junction_frame,
                orientation=(row.get("Orientation") or "").strip(),
                potential_indel=(row.get("V-REGION potential ins/del") or "").strip(),
                sequence_category=(
                    row.get("Sequence analysis category") or ""
                ).strip(),
                analyzed_length=_int_value(row.get("Analysed sequence length")),
            )
        )
    _validate_ids(observed, batch, "IMGT")
    parameters = _parse_parameters(raw_files["11_Parameters.txt"])
    return ImgtBatchResult(
        parameters,
        tuple(records),
        raw_files["11_Parameters.txt"],
        "",
        dict(raw_files),
    )


class ImgtClient:
    def __init__(self, *, timeout: tuple[int, int] = (15, 180)):
        self.timeout = timeout

    def submit(self, batch: ExternalBatch) -> ImgtBatchResult:
        molecule_types = {candidate.molecule_type for candidate in batch.candidates}
        if not molecule_types:
            raise ExternalAnalysisError("Batch has no candidates")
        if len(molecule_types) > 1:
            names = ", ".join(sorted(molecule_types))
            raise ExternalAnalysisError(
                f"IMGT submit must use a single molecule type per batch (got: {names})"
            )
        molecule_type = next(iter(molecule_types))
        data: dict[str, str] = {
            "species": "human",
            "receptorOrLocusType": "IGH",
            "moleculeType": "cDNA" if molecule_type == "cDNA" else "gDNA",
            "inputType": "inline",
            "sequences": batch.fasta,
            "resultType": "excel",
            "xv_outputtype": "1",
            "outputType": "html",
            "nbNtPerLine": "60",
            "dv_D_GENEalignment": "true",
            "V_REGIONsearchIndel": "true",
            "cllSubsetSearch": "true",
            "IMGTrefdirSet": "1",
            "IMGTrefdirAlleles": "true",
            "nbD_GENE": "-1",
            "nbVmut": "-1",
            "nbDmut": "-1",
            "nbJmut": "-1",
            "nb5V_REGIONignoredNt": "0",
            "nb3V_REGIONaddedNt": "0",
            "scfv": "false",
            "xv_summary": "true",
            "xv_JUNCTION": "true",
            "xv_parameters": "true",
        }
        try:
            response = requests.post(IMGT_URL, data=data, timeout=self.timeout)
            response.raise_for_status()
        except requests.exceptions.SSLError as exc:
            raise _tls_error("IMGT", exc) from exc
        except requests.RequestException as exc:
            raise ExternalAnalysisError(f"Kunne ikke kontakte IMGT: {exc}") from exc
        _validate_response_size(response.content)
        try:
            with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
                names = set(archive.namelist())
                if {"Parameters.txt", "vquest_airr.tsv"}.issubset(names):
                    raw_parameters = archive.read("Parameters.txt").decode("utf-8-sig")
                    raw_airr = archive.read("vquest_airr.tsv").decode("utf-8-sig")
                    return parse_imgt_result(raw_parameters, raw_airr, batch)
                raw_files = {
                    name: archive.read(name).decode("utf-8-sig")
                    for name in archive.namelist()
                    if name.endswith(".txt")
                }
        except zipfile.BadZipFile as exc:
            message = re.sub(r"<[^>]+>", " ", response.text)
            message = " ".join(message.split())[:500]
            raise ExternalAnalysisError(
                f"IMGT did not return a valid AIRR archive: {message}"
            ) from exc
        return parse_imgt_full_result(raw_files, batch)


class _ResultLinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tsv_links: list[str] = []
        self.seqcure_links: list[str] = []
        self._anchor_href = ""
        self._anchor_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        href = dict(attrs).get("href") or ""
        self._anchor_href = href
        self._anchor_text = []
        if href.lower().endswith(".tsv"):
            self.tsv_links.append(href)

    def handle_data(self, data: str) -> None:
        if self._anchor_href:
            self._anchor_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a":
            text = " ".join("".join(self._anchor_text).split()).lower()
            if "seqcure" in text and "report" in text and self._anchor_href:
                self.seqcure_links.append(self._anchor_href)
            self._anchor_href = ""
            self._anchor_text = []


def _trusted_arrest_url(url: str) -> None:
    try:
        parsed = urlparse(url)
        valid = (
            parsed.scheme == "https"
            and parsed.hostname in {"bat.infspire.org", "station3.arrest.tools"}
            and parsed.port in {None, 443}
            and parsed.username is None and parsed.password is None
            and not any(ord(char) < 32 for char in url) and "\\" not in url
        )
    except ValueError:
        valid = False
    if not valid:
        raise ExternalAnalysisError("ARResT returned an unknown or insecure report link")


def seqcure_report_url_from_results_url(results_url: str) -> str:
    """Recover the report path for saved TSVs using the verified ARResT format."""
    _trusted_arrest_url(results_url)
    parsed = urlparse(results_url)
    match = re.fullmatch(
        r"/arrest/assignsubsets_results/(fasta\d+)\.sc\.merged\.table\.as\.res\.subtable\.tsv",
        parsed.path,
    )
    if not match or parsed.query or parsed.fragment:
        raise ExternalAnalysisError("Saved ARResT result URL has an unknown report filename format")
    return parsed._replace(path=f"/arrest/assignsubsets_results/{match.group(1)}.sc.report.html").geturl()


class _SeqCureTableParser(HTMLParser):
    """Extract report cells, including the rowspans used for sequence labels."""

    def __init__(self):
        super().__init__()
        self.tables: list[list[list[str]]] = []
        self._table: list[list[str]] | None = None
        self._row: list[str] | None = None
        self._cell: list[str] | None = None
        self._rowspan = 1
        self._spans: dict[int, tuple[int, str]] = {}
        self._ignored = 0
        self.advice_blocks: dict[str, str] = {}
        self.advice_references: dict[str, list[str]] = {}
        self._cell_references: list[str] = []
        self._advice_id = ""
        self._advice_text: list[str] = []

    @staticmethod
    def _plain_text(parts: list[str]) -> str:
        return "\n".join(" ".join(line.split()) for line in "".join(parts).splitlines()).strip()

    def _finish_cell(self) -> None:
        if self._cell is None or self._row is None:
            return
        self._carry_spans()
        value = self._plain_text(self._cell)
        column = len(self._row)
        self._row.append(value)
        if self._rowspan > 1:
            self._spans[column] = (self._rowspan, value)
        if self._cell_references:
            self.advice_references[value] = list(self._cell_references)
        self._cell = None
        self._cell_references = []

    def _carry_spans(self) -> None:
        if self._row is not None:
            while len(self._row) in self._spans:
                self._row.append(self._spans[len(self._row)][1])

    def _finish_row(self) -> None:
        self._finish_cell()
        if self._row is not None:
            if self._table is not None:
                self._carry_spans()
                self._table.append(self._row)
            self._spans = {column: (remaining - 1, value)
                           for column, (remaining, value) in self._spans.items() if remaining > 1}
        self._row = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in {"script", "style"}:
            self._ignored += 1
        elif not self._ignored:
            if tag == "adv":
                advice_id = dict(attrs).get("id") or ""
                if re.fullmatch(r"adv\d+", advice_id):
                    self._advice_id = advice_id
                    self._advice_text = []
            elif tag == "table":
                self._table = []
                self.tables.append(self._table)
                self._spans = {}
            elif tag == "tr" and self._table is not None:
                self._finish_row()
                self._row = []
            elif tag in {"td", "th"} and self._row is not None:
                self._finish_cell()
                self._cell = []
                self._cell_references = []
                try:
                    self._rowspan = max(1, min(1000, int(dict(attrs).get("rowspan") or "1")))
                except ValueError:
                    self._rowspan = 1
            elif tag in {"br", "p"} and self._cell is not None:
                self._cell.append("\n")
            elif tag == "a" and self._cell is not None:
                href = dict(attrs).get("href") or ""
                if re.fullmatch(r"#adv\d+", href):
                    self._cell_references.append(href[1:])
            if tag in {"br", "p"} and self._advice_id:
                self._advice_text.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"script", "style"} and self._ignored:
            self._ignored -= 1
        elif not self._ignored:
            if tag == "adv" and self._advice_id:
                self.advice_blocks[self._advice_id] = self._plain_text(self._advice_text)
                self._advice_id = ""
                self._advice_text = []
            elif tag == "br":
                if self._cell is not None:
                    self._cell.append("\n")
                if self._advice_id:
                    self._advice_text.append("\n")
            elif tag in {"td", "th"}:
                self._finish_cell()
            elif tag == "tr":
                self._finish_row()
            elif tag == "table":
                self._finish_row()
                self._table = None
                self._spans = {}

    def handle_data(self, data: str) -> None:
        if not self._ignored and self._cell is not None:
            self._cell.append(data)
        if not self._ignored and self._advice_id:
            self._advice_text.append(data)


def parse_seqcure_report(
    raw_html: str, batch: ExternalBatch,
) -> dict[str, tuple[tuple[str, ...], tuple[str, ...]]]:
    """Bind final-report messages and full advice to exact local external IDs."""
    parser = _SeqCureTableParser()
    parser.feed(raw_html)
    expected = set(batch.candidate_ids)
    messages: dict[str, list[str]] = {key: [] for key in expected}
    advice: dict[str, list[str]] = {key: [] for key in expected}
    observed: set[str] = set()
    observed_advice: set[str] = set()
    for table in parser.tables:
        section = ""
        current_id = ""
        text_column = 0
        for cells in table:
            if not cells:
                continue
            first = " ".join(cells[0].split())
            if "seqcure id" in first.lower():
                headers = [cell.lower() for cell in cells]
                if "advice" in headers:
                    section, text_column = "advice", headers.index("advice")
                elif any("message" in cell for cell in headers):
                    section = "messages"
                else:
                    section = ""
                current_id = ""
                continue
            if not section:
                continue
            if first:
                match = re.fullmatch(r"(SEQ-[A-F0-9]{6,24})\s*(?:\[#\d+\])?", first)
                if not match or match.group(1) not in expected:
                    raise ExternalAnalysisError("SeqCure report contains an unknown sequence ID")
                current_id = match.group(1)
            if not current_id:
                raise ExternalAnalysisError("SeqCure report message has no sequence ID")
            if section == "messages":
                observed.add(current_id)
                text = "; ".join(cell for cell in cells[1:] if cell)
                destination = messages[current_id]
            else:
                observed_advice.add(current_id)
                text = cells[text_column] if len(cells) > text_column else ""
                destination = advice[current_id]
            if text and text not in destination:
                destination.append(text)
            if section == "advice":
                for advice_id in parser.advice_references.get(text, []):
                    full_text = parser.advice_blocks.get(advice_id)
                    if not full_text:
                        raise ExternalAnalysisError("SeqCure report is missing referenced full advice")
                    if full_text not in destination:
                        destination.append(full_text)
    if observed != expected or observed_advice != expected:
        raise ExternalAnalysisError("SeqCure report does not cover the submitted sequence IDs")
    return {key: (tuple(messages[key]), tuple(advice[key])) for key in expected}


def parse_arrest_result(
    raw_tsv: str,
    batch: ExternalBatch,
    *,
    results_url: str = "",
) -> ArrestBatchResult:
    rows = list(csv.reader(io.StringIO(raw_tsv), delimiter="\t"))
    if not rows:
        raise ExternalAnalysisError("ARResT result is empty")
    header = [cell.lstrip("# ").strip() for cell in rows[0]]
    if len(header) < 17 or "label of your sequence" not in header[0].lower():
        raise ExternalAnalysisError("ARResT result has an unknown header")

    candidates = batch.by_id()
    records: list[ArrestRecord] = []
    observed_ids: list[str] = []
    for values in rows[1:]:
        if not values or not values[0].strip():
            continue
        padded = [*values, *([""] * max(0, 21 - len(values)))]
        external_id = padded[0].strip()
        observed_ids.append(external_id)
        candidate = candidates.get(external_id)
        returned_sequence = padded[16].strip()
        verified = bool(
            candidate
            and returned_sequence
            and sequence_sha256(returned_sequence) == candidate.sequence_sha256
        )
        if returned_sequence and not verified:
            raise ExternalAnalysisError(
                f"ARResT-resultatet for {external_id} har en annen sekvens enn den sendte"
            )
        records.append(
            ArrestRecord(
                external_id=external_id,
                seqcure=padded[1].strip(),
                subset=padded[2].strip(),
                nearest_subset=padded[3].strip(),
                confidence=padded[4].strip(),
                score=padded[5].strip(),
                functionality=padded[6].strip(),
                v_call=padded[7].strip(),
                v_identity_percent=_identity_percent(padded[8]),
                j_call=padded[10].strip(),
                d_call=padded[11].strip(),
                junction_aa=padded[14].strip(),
                imgt_date=padded[17].strip(),
                imgt_version=padded[18].strip(),
                reference_release=padded[19].strip(),
                indel_search=padded[20].strip(),
                sequence_verified=verified,
            )
        )
    _validate_ids(observed_ids, batch, "ARResT")
    return ArrestBatchResult(tuple(records), raw_tsv, results_url)


class ArrestClient:
    def __init__(self, *, timeout: tuple[int, int] = (15, 300)):
        self.timeout = timeout
        self.endpoints = ARREST_ENDPOINTS

    def fetch_seqcure_details(
        self, result: ArrestBatchResult, batch: ExternalBatch, *, report_url: str,
    ) -> ArrestBatchResult:
        """Fetch supplemental text; a failed fetch never discards subset results."""
        raw_html = ""
        current_url = report_url
        try:
            _validate_ids((record.external_id for record in result.records), batch, "ARResT")
            for _ in range(4):
                _trusted_arrest_url(current_url)
                response = requests.get(current_url, timeout=self.timeout, allow_redirects=False)
                response.raise_for_status()
                _validate_response_size(response.content)
                _trusted_arrest_url(response.url)
                if getattr(response, "status_code", 200) in {301, 302, 303, 307, 308}:
                    location = response.headers.get("Location") or response.headers.get("location")
                    if not location:
                        raise ExternalAnalysisError("SeqCure report redirect has no destination")
                    current_url = urljoin(current_url, location)
                    continue
                raw_html = response.content.decode("utf-8-sig")
                details = parse_seqcure_report(raw_html, batch)
                records = tuple(replace(
                    record, seqcure_messages=details[record.external_id][0],
                    seqcure_advice=details[record.external_id][1],
                    seqcure_report_url=current_url, seqcure_details_status="available",
                ) for record in result.records)
                return replace(
                    result, records=records, raw_seqcure_html=raw_html,
                    seqcure_report_url=current_url, seqcure_details_error="",
                    seqcure_retrieved_at=datetime.now(timezone.utc).isoformat(),
                )
            raise ExternalAnalysisError("SeqCure report redirected too many times")
        except (requests.RequestException, ExternalAnalysisError, UnicodeError) as exc:
            return self._seqcure_unavailable(result, str(exc), report_url, raw_html)

    @staticmethod
    def _seqcure_unavailable(
        result: ArrestBatchResult, reason: str, report_url: str = "", raw_html: str = "",
    ) -> ArrestBatchResult:
        if report_url:
            try:
                _trusted_arrest_url(report_url)
            except ExternalAnalysisError:
                report_url = ""
        return replace(
            result, records=tuple(replace(
                record, seqcure_messages=(), seqcure_advice=(),
                seqcure_report_url=report_url, seqcure_details_status=f"unavailable: {reason}",
            ) for record in result.records), raw_seqcure_html=raw_html,
            seqcure_report_url=report_url, seqcure_details_error=reason,
            seqcure_retrieved_at="",
        )

    def submit(self, batch: ExternalBatch) -> ArrestBatchResult:
        if not 1 <= len(batch.candidates) <= MAX_BATCH_SIZE:
            raise ValueError('ARResT accepts between 1 and 50 sequences per request; use the analysis queue')
        payload = {"fastatext": (None, batch.fasta)}
        endpoint = self.endpoints[0]
        for attempts in range(1, 3):
            try:
                response = requests.post(endpoint, files=payload, timeout=self.timeout)
                response.raise_for_status()
                break
            except requests.exceptions.SSLError as exc:
                raise _tls_error("ARResT", exc) from exc
            except requests.RequestException as exc:
                retryable = isinstance(exc, requests.Timeout) or (
                    isinstance(exc, requests.HTTPError) and exc.response is not None
                    and 500 <= exc.response.status_code < 600)
                if not retryable or attempts == 2:
                    raise ExternalAnalysisError(
                        'ARResT unavailable. No independent compatible reserve is verified. Start a new analysis to retry.') from exc
        _validate_response_size(response.content)

        parser = _ResultLinkParser()
        parser.feed(response.text)
        if len(parser.tsv_links) != 1:
            plain = " ".join(re.sub(r"<[^>]+>", " ", response.text).split())[:500]
            raise ExternalAnalysisError(
                f"ARResT did not return a unique result file: {plain}"
            )
        results_url = urljoin(response.url, parser.tsv_links[0])
        if urlparse(results_url).scheme != 'https' or urlparse(results_url).hostname not in {
            "bat.infspire.org",
            "station3.arrest.tools",
        }:
            raise ExternalAnalysisError(
                "ARResT returned a result link to an unknown domain"
            )
        try:
            result_response = requests.get(results_url, timeout=self.timeout)
            result_response.raise_for_status()
        except requests.exceptions.SSLError as exc:
            raise _tls_error("ARResT-resultatet", exc) from exc
        except requests.RequestException as exc:
            raise ExternalAnalysisError(f"Kunne ikke hente ARResT-resultatet: {exc}") from exc
        _validate_response_size(result_response.content)
        if urlparse(result_response.url).scheme != 'https' or urlparse(result_response.url).hostname not in {'bat.infspire.org', 'station3.arrest.tools'}:
            raise ExternalAnalysisError('ARResT result redirected to an unknown or insecure domain')
        result = replace(parse_arrest_result(
            result_response.content.decode("utf-8-sig"),
            batch,
            results_url=results_url,
        ), endpoint=endpoint, attempts=attempts, raw_response_html=response.text)
        if len(parser.seqcure_links) != 1:
            return self._seqcure_unavailable(result, "A unique SeqCure report link was not returned")
        return self.fetch_seqcure_details(
            result, batch, report_url=urljoin(response.url, parser.seqcure_links[0]),
        )


def analysis_directory(run_directory: Path, batch: ExternalBatch) -> Path:
    directory = (
        run_directory.expanduser().resolve()
        / f"{batch.run_date}_external_results"
        / batch.session_id
    )
    ensure_outside_git(directory)
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _atomic_write_text(path: Path, content: str) -> None:
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}-", suffix=".tmp", dir=path.parent
    )
    os.close(fd)
    temporary = Path(temporary_name)
    try:
        temporary.write_text(content, encoding="utf-8", newline="\n")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def save_batch_mapping(run_directory: Path, batch: ExternalBatch) -> Path:
    directory = analysis_directory(run_directory, batch)
    payload: dict[str, Any] = {
        "schema_version": 1,
        "session_id": batch.session_id,
        "run_date": batch.run_date,
        "created_at": batch.created_at,
        "candidates": [
            {
                "external_id": item.external_id,
                "row_index": item.row_index,
                "sample": item.sample,
                "target": item.target,
                "molecule_type": item.molecule_type,
                "rank": item.rank,
                "sequence_sha256": item.sequence_sha256,
            }
            for item in batch.candidates
        ],
    }
    path = directory / "mapping.audit.json"
    if path.exists():
        existing = json.loads(path.read_text(encoding='utf-8'))
        if existing.get('session_id') != batch.session_id:
            raise ValueError('Local mapping session mismatch')
        merged = {item['external_id']: item for item in existing['candidates']}
        for item in payload['candidates']:
            if item['external_id'] in merged and merged[item['external_id']] != item:
                raise ValueError('Local mapping ID binding changed')
            merged[item['external_id']] = item
        payload['candidates'] = list(merged.values())
    _atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2))
    return path


def save_imgt_result(
    run_directory: Path,
    batch: ExternalBatch,
    result: ImgtBatchResult,
) -> Path:
    directory = analysis_directory(run_directory, batch)
    save_batch_mapping(run_directory, batch)
    result_directory = directory / (
        "imgt_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    )
    result_directory.mkdir()
    if result.raw_files:
        for name, content in result.raw_files.items():
            _atomic_write_text(result_directory / Path(name).name, content)
    else:
        _atomic_write_text(result_directory / "Parameters.txt", result.raw_parameters)
        _atomic_write_text(result_directory / "vquest_airr.tsv", result.raw_airr)
    path = result_directory / "results.audit.json"
    _atomic_write_text(
        path,
        json.dumps(
            {
                "schema_version": 1,
                "service": "IMGT/V-QUEST",
                "endpoint": IMGT_URL,
                "saved_at": datetime.now(timezone.utc).isoformat(),
                "parameters": result.parameters,
                "records": [asdict(record) for record in result.records],
            },
            ensure_ascii=False,
            indent=2,
        ),
    )
    return path


def save_arrest_result(
    run_directory: Path,
    batch: ExternalBatch,
    result: ArrestBatchResult,
) -> Path:
    directory = analysis_directory(run_directory, batch)
    save_batch_mapping(run_directory, batch)
    result_directory = directory / (
        "arrest_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    )
    result_directory.mkdir()
    _atomic_write_text(result_directory / "results.tsv", result.raw_tsv)
    if result.raw_response_html:
        _atomic_write_text(result_directory / "assignsubsets_response.html", result.raw_response_html)
    if result.raw_seqcure_html:
        _atomic_write_text(result_directory / "seqcure_report.html", result.raw_seqcure_html)
    path = result_directory / "results.audit.json"
    _atomic_write_text(
        path,
        json.dumps(
            {
                "schema_version": 1,
                "service": "ARResT/AssignSubsets",
                "endpoint": result.endpoint or ARREST_URL,
                "attempts": result.attempts,
                "results_url": result.results_url,
                "seqcure_report_url": result.seqcure_report_url,
                "seqcure_details_error": result.seqcure_details_error,
                "seqcure_retrieved_at": result.seqcure_retrieved_at,
                "seqcure_report_sha256": hashlib.sha256(result.raw_seqcure_html.encode("utf-8")).hexdigest() if result.raw_seqcure_html else "",
                "saved_at": datetime.now(timezone.utc).isoformat(),
                "records": [asdict(record) for record in result.records],
            },
            ensure_ascii=False,
            indent=2,
        ),
    )
    return path


def _subset_number(value: str) -> str:
    if not value or value.lower() in {"unassigned", "skipped/unhealthy", "-"}:
        return ""
    match = re.search(r"#\s*([0-9]+[A-Za-z]?)", value)
    return match.group(1) if match else value.strip()


def _append_comment(existing: str, addition: str) -> str:
    parts = [part.strip() for part in existing.split(" | ") if part.strip()]
    if addition and addition not in parts:
        parts.append(addition)
    return " | ".join(parts)


def apply_imgt_result(
    rows: list[MergedRow] | tuple[MergedRow, ...],
    batch: ExternalBatch,
    result: ImgtBatchResult,
) -> None:
    candidates = batch.by_id()
    for record in result.records:
        candidate = candidates[record.external_id]
        row = rows[candidate.row_index]
        row.external_id = record.external_id
        subset = _subset_number(record.cll_subset)
        if subset:
            row.subset = subset
        functionality = (
            "productive"
            if record.productive is True
            else "not productive"
            if record.productive is False
            else "unknown functionality"
        )
        version = result.program_version or "unknown version"
        details = f"IMGT {version}: {functionality}"
        if record.d_call:
            details += f"; D={record.d_call}"
        from .imgt_observations import j_call_notes, record_observation_text
        if record.selected_identity_percent is not None:
            details += f"; identity={record.selected_identity_percent:g}% ({record.selected_identity_source})"
        details += f"; J={record.j_call}"
        notes = j_call_notes(record.j_call)
        if notes:
            details += f"; {notes}"
        details += '; ' + record_observation_text(record)
        row.comment = _append_comment(row.comment, details)


def apply_arrest_result(
    rows: list[MergedRow] | tuple[MergedRow, ...],
    batch: ExternalBatch,
    result: ArrestBatchResult,
) -> None:
    candidates = batch.by_id()
    for record in result.records:
        candidate = candidates[record.external_id]
        row = rows[candidate.row_index]
        row.external_id = record.external_id
        subset = _subset_number(record.subset)
        if subset:
            if row.subset and subset not in {
                part.strip() for part in row.subset.split("/")
            }:
                row.subset = f"{row.subset} / {subset}"
            elif not row.subset:
                row.subset = subset
        label = record.subset or "unknown"
        details = f"ARResT: {label}"
        if record.confidence:
            details += f", {record.confidence}"
        if record.score:
            details += f", score {record.score}"
        row.comment = _append_comment(row.comment, details)
