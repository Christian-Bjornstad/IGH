from __future__ import annotations

import runpy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

INSTALL_SCRIPT = ROOT / "install_python_felles.py"
START_SCRIPT = ROOT / "start_python_felles.py"
INSTALL_CMD = ROOT / "INSTALL_IGH_MERGE.cmd"
START_CMD = ROOT / "START_IGH_MERGE.cmd"
INSTALLER_ALIAS_CMD = ROOT / "INSTALL_IGH_MERGE_INSTALLER.cmd"
REQUIREMENTS = ROOT / "requirements.txt"
PYPROJECT = ROOT / "pyproject.toml"

EXPECTED_PIP_ARGS = ["install", "--user", "--disable-pip-version-check", "-e"]
EXPECTED_IMPORTS = [
    "openpyxl",
    "PyQt6",
    "reportlab",
    "requests",
    "truststore",
    "docx",
    "websocket",
    "igh_merge",
]


def test_installer_installs_editable_project_and_verifies_imports(tmp_path: Path) -> None:
    functions = runpy.run_path(str(INSTALL_SCRIPT))
    (tmp_path / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    (tmp_path / "src" / "igh_merge").mkdir(parents=True)
    pip_calls: list[list[str]] = []
    imported: list[str] = []

    result = functions["install"](
        project_dir=tmp_path,
        user_site=tmp_path / "user-site",
        pip_main=lambda args: pip_calls.append(list(args)) or 0,
        importer=lambda name: imported.append(name) or object(),
    )

    assert result == 0
    assert pip_calls == [
        EXPECTED_PIP_ARGS + [f"{tmp_path.resolve()}[dev]"]
    ]
    assert imported == EXPECTED_IMPORTS


def test_start_launches_the_gui_main(tmp_path: Path) -> None:
    functions = runpy.run_path(str(START_SCRIPT))
    (tmp_path / "src" / "igh_merge").mkdir(parents=True)
    calls: list[bool] = []

    result = functions["start"](
        project_dir=tmp_path,
        user_site=tmp_path / "user-site",
        app_main=lambda: calls.append(True) or 0,
    )

    assert result == 0
    assert calls == [True]


@pytest.mark.parametrize(
    ("script_name", "stage", "log_name"),
    [
        ("install_python_felles.py", "installer_start_failed", "install.log"),
        ("start_python_felles.py", "igh_merge_start_failed", "start.log"),
    ],
)
def test_main_logs_full_bootstrap_failure(
    tmp_path: Path, monkeypatch, script_name: str, stage: str, log_name: str
) -> None:
    functions = runpy.run_path(str(ROOT / script_name))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))

    result = functions["main"](project_dir=tmp_path / "missing")

    assert result == 1
    content = (tmp_path / "local" / "IGH" / "logs" / log_name).read_text(
        encoding="utf-8"
    )
    assert stage in content
    assert "RuntimeError" in content
    assert "Traceback" in content


def test_launchers_are_generic_without_hardcoded_paths() -> None:
    """The launchers must resolve the project from __file__, never K:."""
    for script in (INSTALL_SCRIPT, START_SCRIPT):
        source = script.read_text(encoding="utf-8")
        assert "if __name__" in source, f"{script.name} needs a __main__ entry"
        assert "__file__" in source, f"{script.name} must use __file__ resolution"
        assert "KDI" not in source, f"{script.name} still mentions KDI"
        assert "K:\\" not in source, f"{script.name} hard-codes the K: drive"


def test_requirements_txt_remains_exactly_five_pinned_lines() -> None:
    """Guard the hospital-wide Python FELLES pin contract."""
    lines = [
        line.strip()
        for line in REQUIREMENTS.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert lines == [
        "openpyxl==3.1.5",
        "PyQt6==6.11.0",
        "reportlab==5.0.0",
        "requests==2.34.2",
        "truststore==0.10.4",
    ]


def test_pyproject_declares_the_extra_dependencies() -> None:
    """python-docx and websocket-client must live in pyproject.toml only."""
    text = PYPROJECT.read_text(encoding="utf-8")
    assert "python-docx" in text
    assert "websocket-client" in text
    reqs = REQUIREMENTS.read_text(encoding="utf-8")
    assert "python-docx" not in reqs
    assert "websocket-client" not in reqs


def test_cmd_files_use_pure_cmd_without_powershell() -> None:
    """The .cmd wrappers must be pure cmd (clip.exe), no powershell.exe."""
    for cmd_path in (INSTALL_CMD, START_CMD):
        text = cmd_path.read_text(encoding="utf-8")
        low = text.lower()
        assert "pwrgate.exe" in low, f"{cmd_path.name} must open Ivanti PowerGate"
        assert "15694" in text, f"{cmd_path.name} must use the Python FELLES slot"
        assert "clip" in low, f"{cmd_path.name} must copy via clip.exe"
        assert "powershell" not in low, f"{cmd_path.name} must not use PowerShell"
        assert ".ps1" not in low, f"{cmd_path.name} must not call .ps1 helpers"
        payload = (
            "import runpy; runpy.run_path(r'"
            + ("install_python_felles.py" if "INSTALL" in cmd_path.name else "start_python_felles.py")
        )
        assert payload not in text or "%~dp0" in text  # placeholder only via variable


def test_installer_alias_cmd_routes_to_install_cmd() -> None:
    """INSTALL_IGH_MERGE_INSTALLER.cmd is a friendly alias (MolStat pattern)."""
    text = INSTALLER_ALIAS_CMD.read_text(encoding="utf-8")
    assert "INSTALL_IGH_MERGE.cmd" in text


def test_old_kdi_and_ps1_files_are_removed() -> None:
    """Legacy launchers must be gone after the generic redesign."""
    for legacy in (
        ROOT / "install_python_felles_KDI.py",
        ROOT / "start_python_felles_KDI.py",
        ROOT / "Start-IGH-Merge.ps1",
    ):
        assert not legacy.exists(), f"{legacy.name} must be removed"
