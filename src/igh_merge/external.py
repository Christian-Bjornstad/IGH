from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import secrets
import tempfile
import zipfile
from dataclasses import asdict, dataclass, field
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
ARREST_URL = "https://bat.infspire.org/cgi-bin/arrest/assignsubsets_html.pl"
MAX_BATCH_SIZE = 50
MAX_RESPONSE_BYTES = 25_000_000
IUPAC_NUCLEOTIDES = frozenset("ACGTRYSWKMBDHVN")


class ExternalAnalysisError(RuntimeError):
    """Ekstern analyse svarte ikke med et trygt, forventet resultat."""


def _tls_error(service: str, exc: requests.exceptions.SSLError) -> ExternalAnalysisError:
    return ExternalAnalysisError(
        f"Kunne ikke kontakte {service} fordi HTTPS-sertifikatet ikke kunne "
        "verifiseres mot Windows sitt sertifikatlager. Kjør INSTALLER PAKKER-"
        "kommandoen på nytt etter siste oppdatering. Hvis feilen fortsetter, må "
        "IT kontrollere at virksomhetens proxy-/Ivanti-rotsertifikat ligger i "
        f"Windows Trusted Root Certification Authorities. Detaljer: {exc}"
    )


def normalize_sequence(sequence: str) -> str:
    normalized = "".join(sequence.split()).upper()
    if not normalized:
        raise ValueError("Sekvensen er tom")
    invalid = sorted(set(normalized) - IUPAC_NUCLEOTIDES)
    if invalid:
        raise ValueError(f"Sekvensen inneholder ugyldige tegn: {''.join(invalid)}")
    return normalized


def sequence_sha256(sequence: str) -> str:
    return hashlib.sha256(normalize_sequence(sequence).encode("ascii")).hexdigest()


@dataclass(frozen=True)
class ExternalCandidate:
    external_id: str
    row_index: int
    sample: str
    target: str
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
    if len(selected) > MAX_BATCH_SIZE:
        raise ValueError(f"Maksimalt {MAX_BATCH_SIZE} sekvenser kan sendes i én batch")

    candidates: list[ExternalCandidate] = []
    used_ids: set[str] = set()
    for row_index, row in selected:
        external_id = ""
        while not external_id or external_id in used_ids:
            external_id = f"SEQ-{secrets.token_hex(6).upper()}"
        used_ids.add(external_id)
        sequence = normalize_sequence(row.source.sequence)
        candidates.append(
            ExternalCandidate(
                external_id=external_id,
                row_index=row_index,
                sample=row.sample,
                target=row.target,
                rank=row.source.rank,
                sequence=sequence,
                sequence_sha256=sequence_sha256(sequence),
            )
        )
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


@dataclass(frozen=True)
class ArrestBatchResult:
    records: tuple[ArrestRecord, ...]
    raw_tsv: str
    results_url: str


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


def _validate_response_size(content: bytes) -> None:
    if len(content) > MAX_RESPONSE_BYTES:
        raise ExternalAnalysisError("Tjenesten returnerte en uventet stor respons")


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
        raise ExternalAnalysisError(f"{service} returnerte duplikate eksterne ID-er")
    if set(observed) != set(expected):
        missing = sorted(set(expected) - set(observed))
        extra = sorted(set(observed) - set(expected))
        raise ExternalAnalysisError(
            f"{service}-resultatet matcher ikke batchen "
            f"(mangler {len(missing)}, ekstra {len(extra)})"
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
        raise ExternalAnalysisError(f"IMGT AIRR mangler kolonner: {', '.join(missing)}")

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
                v_identity_percent=_identity_percent(row.get("v_identity")),
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
        raise ExternalAnalysisError("IMGT Parameters.txt mangler programversjon")
    if not parameters.get("IMGT/V-QUEST reference directory release"):
        raise ExternalAnalysisError("IMGT Parameters.txt mangler referanserelease")
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
            "IMGT-fullresultat mangler: " + ", ".join(sorted(required - raw_files.keys()))
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
        aa_row = aa_by_id.get(external_id, {})
        cdr3_aa = (aa_row.get("CDR3-IMGT") or "").strip()
        records.append(
            ImgtRecord(
                external_id=external_id,
                productive=productive,
                stop_codon=None,
                vj_in_frame="in-frame" in junction_frame.lower(),
                v_call=(row.get("V-GENE and allele") or "").strip(),
                d_call=(row.get("D-GENE and allele") or "").strip(),
                j_call=(row.get("J-GENE and allele") or "").strip(),
                v_identity_percent=_float_value(row.get("V-REGION identity %")),
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
                cdr3_aa=cdr3_aa,
                cdr3_aa_length=len(cdr3_aa) if cdr3_aa else None,
                junction_aa_length=_int_value(row.get("CDR3-IMGT length")),
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
        data: dict[str, str] = {
            "species": "human",
            "receptorOrLocusType": "IGH",
            "moleculeType": "Unknown",
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
                f"IMGT svarte ikke med et gyldig AIRR-arkiv: {message}"
            ) from exc
        return parse_imgt_full_result(raw_files, batch)


class _ResultLinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tsv_links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        href = dict(attrs).get("href") or ""
        if href.lower().endswith(".tsv"):
            self.tsv_links.append(href)


def parse_arrest_result(
    raw_tsv: str,
    batch: ExternalBatch,
    *,
    results_url: str = "",
) -> ArrestBatchResult:
    rows = list(csv.reader(io.StringIO(raw_tsv), delimiter="\t"))
    if not rows:
        raise ExternalAnalysisError("ARResT-resultatet er tomt")
    header = [cell.lstrip("# ").strip() for cell in rows[0]]
    if len(header) < 17 or "label of your sequence" not in header[0].lower():
        raise ExternalAnalysisError("ARResT-resultatet har ukjent header")

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

    def submit(self, batch: ExternalBatch) -> ArrestBatchResult:
        try:
            response = requests.post(
                ARREST_URL,
                files={"fastatext": (None, batch.fasta)},
                timeout=self.timeout,
            )
            response.raise_for_status()
        except requests.exceptions.SSLError as exc:
            raise _tls_error("ARResT", exc) from exc
        except requests.RequestException as exc:
            raise ExternalAnalysisError(f"Kunne ikke kontakte ARResT: {exc}") from exc
        _validate_response_size(response.content)

        parser = _ResultLinkParser()
        parser.feed(response.text)
        if len(parser.tsv_links) != 1:
            plain = " ".join(re.sub(r"<[^>]+>", " ", response.text).split())[:500]
            raise ExternalAnalysisError(
                f"ARResT svarte uten en entydig resultatfil: {plain}"
            )
        results_url = urljoin(response.url, parser.tsv_links[0])
        if urlparse(results_url).hostname != "bat.infspire.org":
            raise ExternalAnalysisError("ARResT returnerte en resultatlenke til ukjent domene")
        try:
            result_response = requests.get(results_url, timeout=self.timeout)
            result_response.raise_for_status()
        except requests.exceptions.SSLError as exc:
            raise _tls_error("ARResT-resultatet", exc) from exc
        except requests.RequestException as exc:
            raise ExternalAnalysisError(f"Kunne ikke hente ARResT-resultatet: {exc}") from exc
        _validate_response_size(result_response.content)
        return parse_arrest_result(
            result_response.content.decode("utf-8-sig"),
            batch,
            results_url=results_url,
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
                "rank": item.rank,
                "sequence_sha256": item.sequence_sha256,
            }
            for item in batch.candidates
        ],
    }
    path = directory / "mapping.audit.json"
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
    path = result_directory / "results.audit.json"
    _atomic_write_text(
        path,
        json.dumps(
            {
                "schema_version": 1,
                "service": "ARResT/AssignSubsets",
                "endpoint": ARREST_URL,
                "results_url": result.results_url,
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
        subset = _subset_number(record.cll_subset)
        if subset:
            row.subset = subset
        functionality = (
            "productive"
            if record.productive is True
            else "not productive"
            if record.productive is False
            else "ukjent funksjonalitet"
        )
        version = result.program_version or "ukjent versjon"
        details = f"IMGT {version}: {functionality}"
        if record.d_call:
            details += f"; D={record.d_call}"
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
        subset = _subset_number(record.subset)
        if subset:
            if row.subset and subset not in {
                part.strip() for part in row.subset.split("/")
            }:
                row.subset = f"{row.subset} / {subset}"
            elif not row.subset:
                row.subset = subset
        label = record.subset or "ukjent"
        details = f"ARResT: {label}"
        if record.confidence:
            details += f", {record.confidence}"
        if record.score:
            details += f", score {record.score}"
        row.comment = _append_comment(row.comment, details)
