from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).parents[1]
EXPECTED_K_PATH = (
    r"K:\Felles\KDI\Delte\PAT\Molekylaerpatologi\Molpat OCCI\Diagnostikk"
    r"\Analyser,oppsett,kontroller\Hemapatologi\IGHV\CFB\IGH_app"
)


def test_python_felles_requirements_are_pinned():
    assert (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines() == [
        "openpyxl==3.1.5",
        "PyQt6==6.11.0",
        "reportlab==5.0.0",
        "requests==2.34.2",
        "truststore==0.10.4",
    ]


def test_python_felles_scripts_use_expected_k_path_and_no_python_subprocess():
    installer = (ROOT / "install_python_felles_KDI.py").read_text(encoding="utf-8")
    starter = (ROOT / "start_python_felles_KDI.py").read_text(encoding="utf-8")
    commands = (ROOT / "PYTHON_FELLES_KOMMANDOER.txt").read_text(encoding="utf-8")

    assert r"\Hemapatologi\IGHV\CFB\IGH_app" in installer
    assert r"\Hemapatologi\IGHV\CFB\IGH_app" in starter
    assert EXPECTED_K_PATH in commands
    assert "subprocess" not in installer
    assert "sys.executable" not in installer
    assert ".python_felles_packages" in installer
    assert "requirements_sha256" in starter
    assert "exec(open(" in commands
