"""Microsoft Edge + Chrome DevTools Protocol (CDP) bridge.

IGHV uses a managed Microsoft Edge install for evidence collection on the
hospital workstation. The hospital has no other browser and no other `.exe`
files are allowed on locked-down machines, so we drive Edge directly over the
CDP HTTP/WebSocket interface instead of using Selenium or Playwright.

This module is intentionally minimal — enough to:

* launch Edge with a dedicated user-data-dir so saved sessions do not collide
  with the user's daily Edge profile,
* open and navigate a single tab,
* take a full-page or element-clipped PNG screenshot,
* extract text from the active page (for IMGT result fields).

The screenshot pipeline is the only piece used in the first iteration; the
text-extraction helpers are placeholders for the follow-up work where the app
parses the IMGT result page directly (sections 1-6 and 9) instead of relying
on the AIRR ZIP file. See the GUI design doc for which sections map to which
rearrangement field.
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator


class EdgeCdpError(RuntimeError):
    """Microsoft Edge or its local DevTools connection failed."""


class EdgeCdpTimeout(TimeoutError):
    """A CDP navigation or DOM wait exceeded its configured timeout."""


# IMGT result page is split into nine numbered sections (1_Summary, 2_..., 9_...).
# The user wants screenshots for sections 1..6 and 9 (sections 7 and 8 are
# large alignment views that would dwarf the report). The mapping is kept here
# so the GUI can show the same label in both the screenshot pane and the report.
IMGT_SCREENSHOT_SECTIONS: tuple[int, ...] = (1, 2, 3, 4, 5, 6, 9)


def find_edge_executable() -> Path:
    """Return the path to the managed Microsoft Edge executable."""
    discovered = shutil.which("msedge")
    candidates: list[Path] = [Path(discovered)] if discovered else []
    for environment_name in ("PROGRAMFILES(X86)", "PROGRAMFILES", "LOCALAPPDATA"):
        root = os.environ.get(environment_name)
        if root:
            candidates.append(
                Path(root) / "Microsoft" / "Edge" / "Application" / "msedge.exe"
            )
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise EdgeCdpError(
        "Microsoft Edge was not found. Ask IT to expose the managed Edge "
        "installation before using the IMGT evidence capture."
    )


# `os` is imported at the top of the file — the diagnostic message just below
# reuses the env vars that `find_edge_executable` already consults.


def edge_cdp_available() -> bool:
    """Return True when both Edge and a usable CDP dependency are present."""
    try:
        find_edge_executable()
    except EdgeCdpError:
        return False
    try:
        import websocket  # noqa: F401
    except ImportError:
        return False
    return True


def _reserve_local_port() -> int:
    """Bind a free TCP port on loopback and return it immediately."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as handle:
        handle.bind(("127.0.0.1", 0))
        return int(handle.getsockname()[1])


def _http_json(url: str, *, method: str = "GET", timeout: float = 5.0) -> dict[str, Any]:
    """Tiny urllib wrapper for the CDP HTTP endpoint."""
    request = urllib.request.Request(url, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
        raise EdgeCdpError(f"CDP HTTP {method} {url} failed: {exc}") from exc


@dataclass
class EdgeCdpPage:
    target_id: str
    websocket_url: str
    origin: str

    def __post_init__(self) -> None:
        import websocket  # local import: only needed when actually driving a page

        self._websocket_module = websocket
        address = urllib.parse.urlsplit(self.websocket_url)
        if address.scheme != "ws" or address.hostname not in {
            "127.0.0.1",
            "localhost",
            "::1",
        }:
            raise EdgeCdpError("DevTools must use a local loopback WebSocket.")
        try:
            self._socket = websocket.create_connection(
                self.websocket_url, timeout=15, origin=self.origin
            )
        except Exception as exc:
            raise EdgeCdpError(f"Could not connect to Microsoft Edge CDP: {exc}") from exc
        self._next_id = 1

    def close(self) -> None:
        try:
            self._socket.close()
        except Exception:  # pragma: no cover - best effort
            pass

    def call(self, method: str, params: dict[str, Any] | None = None,
             *, timeout_s: float = 30.0) -> dict[str, Any]:
        command_id = self._next_id
        self._next_id += 1
        payload: dict[str, Any] = {"id": command_id, "method": method}
        if params is not None:
            payload["params"] = params
        self._socket.send(json.dumps(payload))
        self._socket.settimeout(timeout_s)
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            try:
                message = json.loads(self._socket.recv())
            except self._websocket_module.WebSocketTimeoutException as exc:
                raise EdgeCdpTimeout(f"Edge timed out during {method}.") from exc
            if message.get("id") == command_id:
                if "error" in message:
                    raise EdgeCdpError(
                        f"Edge rejected {method}: {message['error'].get('message')}"
                    )
                return dict(message.get("result") or {})
        raise EdgeCdpTimeout(f"Edge timed out during {method}.")

    # ----- High-level helpers --------------------------------------------
    def navigate(self, url: str, *, timeout_s: float = 60.0) -> None:
        """Navigate the page and wait for the load event."""
        self.call("Page.enable", timeout_s=timeout_s)
        self.call("Page.navigate", {"url": url}, timeout_s=timeout_s)
        self._wait_for_load(timeout_s=timeout_s)

    def _wait_for_load(self, *, timeout_s: float) -> None:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            try:
                self._socket.settimeout(2.0)
                message = json.loads(self._socket.recv())
            except self._websocket_module.WebSocketTimeoutException:
                continue
            if message.get("method") == "Page.loadEventFired":
                return
        raise EdgeCdpTimeout("Edge did not fire Page.loadEventFired in time.")

    def capture_full_page(self, path: Path) -> Path:
        """Save a full-page PNG screenshot of the current tab."""
        path = path.expanduser().resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        metrics = self.call("Page.getLayoutMetrics")
        content_size = metrics.get("contentSize", {})
        width = max(1, int(float(content_size.get("width", 1280))))
        height = max(1, int(float(content_size.get("height", 720))))
        result = self.call(
            "Page.captureScreenshot",
            {
                "format": "png",
                "captureBeyondViewport": True,
                "clip": {
                    "x": 0,
                    "y": 0,
                    "width": width,
                    "height": height,
                    "scale": 1,
                },
            },
            timeout_s=60.0,
        )
        _write_png(path, result["data"])
        return path

    def capture_element(self, selector: str, path: Path) -> Path | None:
        """Capture a clipped screenshot of a single element. Returns None if missing."""
        path = path.expanduser().resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        expression = (
            "(selector) => { const el = document.querySelector(selector);"
            " if (!el) return null; const r = el.getBoundingClientRect();"
            " return {x: r.x, y: r.y, width: r.width, height: r.height,"
            " devicePixelRatio: window.devicePixelRatio || 1}; }"
        )
        box = self.evaluate(expression, args=[selector])
        if not box:
            return None
        result = self.call(
            "Page.captureScreenshot",
            {
                "format": "png",
                "clip": {
                    "x": float(box["x"]),
                    "y": float(box["y"]),
                    "width": float(box["width"]),
                    "height": float(box["height"]),
                    "scale": 1,
                },
            },
            timeout_s=30.0,
        )
        _write_png(path, result["data"])
        return path

    def evaluate(self, expression: str, *, args: list[Any] | None = None) -> Any:
        params: dict[str, Any] = {"expression": expression, "returnByValue": True}
        if args is not None:
            params["arguments"] = [{"value": value} for value in args]
        result = self.call("Runtime.evaluate", params, timeout_s=30.0)
        outcome = result.get("result", {})
        if "value" in outcome:
            return outcome["value"]
        if outcome.get("type") == "undefined":
            return None
        return outcome


def _write_png(path: Path, data_b64: str) -> None:
    """Decode base64-encoded PNG bytes and write them atomically."""
    import base64

    payload = base64.b64decode(data_b64)
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_bytes(payload)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


# ----- Context manager -----------------------------------------------------


@contextmanager
def launch_edge(profile_directory: Path, *,
                background: bool = True,
                viewport: dict[str, int] | None = None) -> Iterator["EdgeCdpSession"]:
    """Launch a dedicated Microsoft Edge instance and yield a connected session."""
    profile_directory = profile_directory.expanduser().resolve()
    profile_directory.mkdir(parents=True, exist_ok=True)
    edge = find_edge_executable()
    port = _reserve_local_port()
    origin = f"http://127.0.0.1:{port}"
    viewport = viewport or {"width": 1440, "height": 1000}
    arguments = [
        str(edge),
        f"--remote-debugging-port={port}",
        "--remote-debugging-address=127.0.0.1",
        f"--remote-allow-origins={origin}",
        f"--user-data-dir={profile_directory}",
        f"--window-size={int(viewport['width'])},{int(viewport['height'])}",
        "--no-first-run",
        "--no-default-browser-check",
        "--new-window",
        "about:blank",
    ]
    if background:
        arguments[1:1] = [
            "--start-minimized",
            "--window-position=-32000,-32000",
        ]
    creation_flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    startup_log = profile_directory / "ighv-edge-startup.log"
    with startup_log.open("ab") as log:
        process = subprocess.Popen(
            arguments, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
            creationflags=creation_flags,
        )
    session = EdgeCdpSession(process=process, origin=origin,
                             profile_directory=profile_directory)
    try:
        session.wait_for_endpoint(timeout_s=20.0)
        yield session
    finally:
        session.close()


class EdgeCdpSession:
    def __init__(self, *, process: subprocess.Popen[bytes], origin: str,
                 profile_directory: Path) -> None:
        self.process = process
        self.origin = origin
        self.profile_directory = profile_directory
        self._closed = False
        self._page: EdgeCdpPage | None = None

    def wait_for_endpoint(self, *, timeout_s: float) -> None:
        deadline = time.monotonic() + timeout_s
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            try:
                _http_json(f"{self.origin}/json/version", timeout=1.0)
                return
            except EdgeCdpError as exc:
                last_error = exc
                if self.process.poll() is not None:
                    raise EdgeCdpError(
                        f"Microsoft Edge exited (code {self.process.returncode}) "
                        f"before its DevTools endpoint opened. {last_error}"
                    ) from exc
                time.sleep(0.2)
        raise EdgeCdpTimeout(
            f"Edge opened but the DevTools endpoint never answered: {last_error}"
        )

    @property
    def page(self) -> EdgeCdpPage:
        if self._page is None:
            targets = _http_json(f"{self.origin}/json/list", timeout=2.0)
            page_targets = [t for t in targets if t.get("type") == "page"]
            if not page_targets:
                target = _http_json(
                    f"{self.origin}/json/new?about:blank",
                    method="PUT", timeout=3.0,
                )
            else:
                target = page_targets[0]
            self._page = EdgeCdpPage(
                target_id=str(target["id"]),
                websocket_url=str(target["webSocketDebuggerUrl"]),
                origin=self.origin,
            )
        return self._page

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._page is not None:
            try:
                self._page.close()
            except Exception:  # pragma: no cover
                pass
        try:
            self.process.terminate()
            self.process.wait(timeout=5)
        except Exception:  # pragma: no cover
            try:
                self.process.kill()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# IMGT-specific helpers
# ---------------------------------------------------------------------------


def imgt_search_url(sequence: str, *, molecule_type: str = "gDNA") -> str:
    """Build the public IMGT/V-QUEST URL for an inline search.

    The IMGT service accepts a fasta payload via POST so the page first
    arrives on the form, then we let the GUI submit it; the URL we return is
    the entry point with the locus pre-selected.
    """
    params = {
        "species": "human",
        "receptorOrLocusType": "IGH",
        "moleculeType": "cDNA" if molecule_type == "cDNA" else "gDNA",
    }
    return "https://www.imgt.org/IMGT_vquest/vquest?" + urllib.parse.urlencode(params)


def extract_imgt_text(page: EdgeCdpPage) -> dict[str, str]:
    """Read the most useful IMGT result fields from the live result page.

    IMGT numbers its result tables 1-9. The user wants to capture screenshots
    for 1-6 and 9; this helper grabs the text for the same sections so the
    follow-up GUI can paste them straight into the Word report.
    """
    sections: dict[str, str] = {}
    for section_number in IMGT_SCREENSHOT_SECTIONS:
        selector = f"a[name='{section_number}']"
        text = page.evaluate(
            "(sel) => { const el = document.querySelector(sel);"
            " return el ? el.parentElement.innerText : ''; }",
            args=[selector],
        )
        sections[f"section_{section_number}"] = (text or "").strip()
    return sections
