from __future__ import annotations

import importlib.util
from pathlib import Path


def load_security_module():
    path = Path(__file__).parents[1] / "tools" / "check_no_clinical_data.py"
    spec = importlib.util.spec_from_file_location("security_check", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_security_check_blocks_clinical_extensions_and_identifiers(tmp_path, monkeypatch):
    module = load_security_module()
    monkeypatch.chdir(tmp_path)
    workbook = tmp_path / "clinical.xlsx"
    workbook.write_bytes(b"data")
    source = tmp_path / "note.txt"
    clinical_id = "99" + "OUM" + "12345"
    source.write_text(f"Eksempel {clinical_id}", encoding="utf-8")
    errors = module.scan_paths([Path("clinical.xlsx"), Path("note.txt")])
    assert any("filtype" in error for error in errors)
    assert any("prøve-ID" in error for error in errors)


def test_security_check_blocks_long_dna_lines(tmp_path, monkeypatch):
    module = load_security_module()
    monkeypatch.chdir(tmp_path)
    source = tmp_path / "sequence.txt"
    source.write_text("ACGT" * 30, encoding="utf-8")
    errors = module.scan_paths([Path("sequence.txt")])
    assert any("DNA-sekvens" in error for error in errors)
