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

Edge/CDP port discovery
-----------------------
The hospital deploys Microsoft Edge through a managed broker, and asking the
broker to honour a specific ``--remote-debugging-port=<fixed>`` is unreliable:
the broker may instead bind a different port. The only reliable port source
on Edge 111+ is the ``<user-data-dir>/DevToolsActivePort`` file that Edge
itself writes once its HTTP endpoint is ready, paired with
``--remote-debugging-port=0`` (let the OS pick).

Edge 111+ also enforces Host header / Origin checks on the DevTools
WebSocket. The ``--remote-allow-origins`` switch is removed entirely; the
``websocket-client`` call uses ``suppress_origin=True`` so Edge sees no Origin
header at all (acceptable for the loopback-only local case).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator


class EdgeCdpError(RuntimeError):
    """Microsoft Edge or its local DevTools connection failed."""


class EdgeCdpTimeout(TimeoutError):
    """A CDP navigation or DOM wait exceeded its configured timeout."""


# IMGT's detailed HTML page uses current result numbers 1-17. Sections 4 and 5
# only exist for cDNA when an L/C hit is found. Clinical review needs the
# identifying summary and the evidence for V/J assignment, junction, V-region
# alignment/translation, and mutation burden — not one indiscriminate full-page
# image. The integer tuple stays as the user-facing compact labels in the GUI.
IMGT_SCREENSHOT_SECTIONS: tuple[int, ...] = (1, 2, 3, 4, 5, 6, 9)


@dataclass(frozen=True)
class ImgtScreenshotSpec:
    """One report-oriented crop from a current IMGT detailed result page."""

    key: str
    label: str
    start_selector: str
    end_selector: str | None = None
    optional: bool = False
    max_height: float = 6_000.0


IMGT_SCREENSHOT_SPECS: tuple[ImgtScreenshotSpec, ...] = (
    ImgtScreenshotSpec(
        "00_summary",
        "Sequence and result summary",
        "table.result_summary",
        "h4#sequence1_alv",
        max_height=3_800.0,
    ),
    ImgtScreenshotSpec(
        "01_v_gene",
        "1. V-GENE alignment",
        "h4#sequence1_alv",
        "h4#sequence1_ald",
    ),
    ImgtScreenshotSpec(
        "02_d_gene",
        "2. D-GENE alignment",
        "h4#sequence1_ald",
        "h4#sequence1_alj",
        optional=True,
        max_height=3_500.0,
    ),
    ImgtScreenshotSpec(
        "03_j_gene",
        "3. J-GENE alignment",
        "h4#sequence1_alj",
        "h4#sequence1_alL, h4#sequence1_alC, h4#sequence1_junction",
    ),
    ImgtScreenshotSpec(
        "04_leader",
        "4. L-REGION alignment (cDNA)",
        "h4#sequence1_alL",
        "h4#sequence1_alC, h4#sequence1_junction",
        optional=True,
        max_height=3_500.0,
    ),
    ImgtScreenshotSpec(
        "05_constant",
        "5. C-GENE alignment (cDNA)",
        "h4#sequence1_alC",
        "h4#sequence1_junction",
        optional=True,
        max_height=3_500.0,
    ),
    ImgtScreenshotSpec(
        "06_junction",
        "6. IMGT/JunctionAnalysis",
        "h4#sequence1_junction",
        "h4#sequence1_junction2",
        max_height=5_000.0,
    ),
    ImgtScreenshotSpec(
        "09_v_region_translation",
        "9. V-REGION translation",
        "h4#sequence1_section7",
        "h4#sequence1_section8",
    ),
)

# Default startup budget for Edge to publish DevToolsActivePort + open the
# /json/version HTTP endpoint. Twenty seconds covers a cold start of the
# managed Edge broker on the hospital workstation; we bail early the moment
# the process exits.
EDGE_STARTUP_TIMEOUT_S: float = 20.0
# Polling cadence for the DevToolsActivePort file. 200ms is the right tradeoff
# between latency and CPU on Windows.
DEVTOOLS_POLL_INTERVAL_S: float = 0.2
# DevToolsActivePort is created in this subdirectory of the user-data-dir.
_DEVTOOLS_ACTIVE_PORT_NAME = "DevToolsActivePort"


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


def _read_devtools_active_port(profile_directory: Path) -> int | None:
    """Return the port announced in ``<profile>/DevToolsActivePort``.

    Edge writes this file on startup with the format::

        <port>\\n<socket_path>\\n

    Returns ``None`` if the file is missing or unreadable so the caller can
    keep polling.
    """
    path = profile_directory / _DEVTOOLS_ACTIVE_PORT_NAME
    try:
        raw = path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return None
    first_line = raw.splitlines()[0].strip() if raw else ""
    if not first_line.isdigit():
        return None
    port = int(first_line)
    if not 1024 <= port <= 65535:
        return None
    return port


def _wait_for_devtools_active_port(
    process: subprocess.Popen[bytes],
    profile_directory: Path,
    *,
    timeout_s: float,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    """Poll ``DevToolsActivePort`` until a valid port appears or time runs out.

    Raises ``EdgeCdpError`` if the Edge process exits before publishing its
    port, and ``EdgeCdpTimeout`` if the deadline is reached.
    """
    deadline = time.monotonic() + timeout_s
    while True:
        port = _read_devtools_active_port(profile_directory)
        if port is not None:
            return port
        if process.poll() is not None:
            raise EdgeCdpError(
                f"Microsoft Edge exited (code {process.returncode}) before "
                f"writing {profile_directory / _DEVTOOLS_ACTIVE_PORT_NAME}."
            )
        if time.monotonic() >= deadline:
            raise EdgeCdpTimeout(
                "Microsoft Edge did not publish DevToolsActivePort within "
                f"{timeout_s:.0f}s."
            )
        sleep(DEVTOOLS_POLL_INTERVAL_S)


def _proxy_free_opener() -> urllib.request.OpenerDirector:
    """Build a urllib opener that bypasses any system/enterprise proxy.

    Hospital workstations route everything through an enterprise proxy. The
    DevTools HTTP endpoint only listens on loopback so the proxy must NOT
    be involved; otherwise the request never reaches Edge and we get a
    useless 502/504 from the proxy.
    """
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _http_json(
    url: str,
    *,
    method: str = "GET",
    timeout: float = 5.0,
    opener: urllib.request.OpenerDirector | None = None,
) -> dict[str, Any]:
    """Tiny urllib wrapper for the CDP HTTP endpoint, with proxy bypass."""
    request = urllib.request.Request(url, method=method)
    try:
        with (opener or _proxy_free_opener()).open(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
        raise EdgeCdpError(f"CDP HTTP {method} {url} failed: {exc}") from exc


def _is_loopback_host(hostname: str | None) -> bool:
    if not hostname:
        return False
    lowered = hostname.lower()
    return lowered in {"127.0.0.1", "localhost", "::1"}


@dataclass
class EdgeCdpPage:
    target_id: str
    websocket_url: str

    def __post_init__(self) -> None:
        import websocket  # local import: only needed when actually driving a page

        self._websocket_module = websocket
        address = urllib.parse.urlsplit(self.websocket_url)
        if address.scheme != "ws" or not _is_loopback_host(address.hostname):
            raise EdgeCdpError("DevTools must use a local loopback WebSocket.")
        prefix = address.path or ""
        if not prefix.startswith("/devtools/"):
            raise EdgeCdpError(
                "DevTools WebSocket path must be under /devtools/ (got "
                f"{prefix!r})."
            )
        try:
            self._socket = websocket.create_connection(
                self.websocket_url,
                timeout=15,
                suppress_origin=True,
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
        """Capture a clipped screenshot of one element, including overflow."""
        return self.capture_region(selector, path)

    def capture_region(
        self,
        start_selector: str,
        path: Path,
        *,
        end_selector: str | None = None,
        padding: float = 12.0,
        max_height: float = 6_000.0,
    ) -> Path | None:
        """Capture a document-space region between two IMGT elements.

        ``getBoundingClientRect`` is viewport-relative and the old helper also
        clipped a heading alone. IMGT result sections are headed by ``h4``
        elements and extend until the next ``h4.section_title``; this helper
        measures that whole range in document coordinates and captures it with
        ``captureBeyondViewport``. ``max_height`` protects reports from huge
        alignment screenshots.
        """
        path = path.expanduser().resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        expression = f"""(() => {{
            const start = document.querySelector({json.dumps(start_selector)});
            if (!start) return null;
            const explicitEnd = {json.dumps(end_selector)};
            const end = explicitEnd
                ? document.querySelector(explicitEnd)
                : (() => {{
                    let node = start.nextElementSibling;
                    while (node) {{
                        if (node.matches && node.matches('h4.section_title')) return node;
                        node = node.nextElementSibling;
                    }}
                    return null;
                }})();
            const sr = start.getBoundingClientRect();
            const y = sr.top + window.scrollY;
            const endY = end
                ? end.getBoundingClientRect().top + window.scrollY
                : document.documentElement.scrollHeight;
            const width = Math.max(
                document.documentElement.scrollWidth,
                document.body ? document.body.scrollWidth : 0,
                sr.right + window.scrollX
            );
            return {{x: 0, y, width, height: Math.max(sr.height, endY - y)}};
        }})()"""
        box = self.evaluate(expression)
        if not box:
            return None
        x = max(0.0, float(box["x"]) - padding)
        y = max(0.0, float(box["y"]) - padding)
        width = max(1.0, float(box["width"]) - x + padding)
        height = min(max_height, max(1.0, float(box["height"]) + 2 * padding))
        result = self.call(
            "Page.captureScreenshot",
            {
                "format": "png",
                "captureBeyondViewport": True,
                "clip": {
                    "x": x,
                    "y": y,
                    "width": width,
                    "height": height,
                    "scale": 1,
                },
            },
            timeout_s=60.0,
        )
        _write_png(path, result["data"])
        return path

    def evaluate(self, expression: str, *, args: list[Any] | None = None) -> Any:
        # Runtime.evaluate does not accept an ``arguments`` parameter (that is
        # Runtime.callFunctionOn). Wrap callable expressions explicitly so the
        # selectors are JSON-escaped and the browser evaluates the function.
        if args is not None:
            encoded = ", ".join(json.dumps(value) for value in args)
            expression = f"({expression})({encoded})"
        params: dict[str, Any] = {"expression": expression, "returnByValue": True}
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
                viewport: dict[str, int] | None = None,
                startup_timeout_s: float = EDGE_STARTUP_TIMEOUT_S,
                sleeper: Callable[[float], None] = time.sleep,
                opener_factory: Callable[[], urllib.request.OpenerDirector] | None = None,
                process_runner: Callable[..., subprocess.Popen[bytes]] | None = None,
                port_reader: Callable[[Path], int | None] | None = None) -> Iterator["EdgeCdpSession"]:
    """Launch a dedicated Microsoft Edge instance and yield a connected session.

    Edge is launched with ``--remote-debugging-port=0`` so the managed broker
    picks the actual port; we then read it from
    ``<user-data-dir>/DevToolsActivePort`` before opening the proxy-free HTTP
    endpoint. No ``--remote-allow-origins`` is passed: the websocket connects
    with ``suppress_origin=True`` instead (the only configuration Edge 111+
    accepts on loopback without a paired allow-list).
    """
    profile_directory = profile_directory.expanduser().resolve()
    profile_directory.mkdir(parents=True, exist_ok=True)
    # Defensive: delete any stale DevToolsActivePort file left over from a
    # crashed/cleaned-up previous run. If we read the old port, we would
    # race against Edge rebinding to it.
    stale_port_file = profile_directory / _DEVTOOLS_ACTIVE_PORT_NAME
    try:
        stale_port_file.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        # If we cannot remove the stale file the launch will simply overwrite
        # it; not worth raising here.
        pass

    edge = find_edge_executable()
    viewport = viewport or {"width": 1440, "height": 1000}
    arguments = [
        str(edge),
        "--remote-debugging-port=0",
        "--remote-debugging-address=127.0.0.1",
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
    runner = process_runner or subprocess.Popen
    with startup_log.open("ab") as log:
        process = runner(
            arguments, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
            creationflags=creation_flags,
        )
    opener_factory = opener_factory or _proxy_free_opener
    port_reader = port_reader or _read_devtools_active_port
    session = EdgeCdpSession(
        process=process,
        profile_directory=profile_directory,
        startup_timeout_s=startup_timeout_s,
        sleeper=sleeper,
        opener_factory=opener_factory,
        port_reader=port_reader,
    )
    try:
        session.wait_for_endpoint(timeout_s=startup_timeout_s)
        yield session
    finally:
        session.close()


class EdgeCdpSession:
    def __init__(self, *, process: subprocess.Popen[bytes],
                 profile_directory: Path,
                 startup_timeout_s: float = EDGE_STARTUP_TIMEOUT_S,
                 sleeper: Callable[[float], None] = time.sleep,
                 opener_factory: Callable[[], urllib.request.OpenerDirector] | None = None,
                 port_reader: Callable[[Path], int | None] | None = None) -> None:
        self.process = process
        self.profile_directory = profile_directory
        self._closed = False
        self._page: EdgeCdpPage | None = None
        self._actual_port: int | None = None
        self._startup_timeout_s = startup_timeout_s
        self._sleeper = sleeper
        self._opener_factory = opener_factory or _proxy_free_opener
        self._port_reader = port_reader or _read_devtools_active_port

    @property
    def port(self) -> int:
        """Return the loopback port Edge actually published."""
        if self._actual_port is None:
            raise EdgeCdpError(
                "Edge session has not yet discovered the DevTools port."
            )
        return self._actual_port

    @property
    def origin(self) -> str:
        """Return the http://127.0.0.1:<port> base URL Edge actually listens on."""
        return f"http://127.0.0.1:{self.port}"

    def wait_for_endpoint(self, *, timeout_s: float | None = None) -> None:
        budget = self._startup_timeout_s if timeout_s is None else timeout_s
        # Step 1: discover the actual port from DevToolsActivePort. The file
        # is written before the HTTP endpoint is listening, so this can take
        # a moment longer; we re-check poll() each iteration.
        deadline = time.monotonic() + budget
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            port = self._port_reader(self.profile_directory)
            if port is not None:
                self._actual_port = port
                break
            if self.process.poll() is not None:
                raise EdgeCdpError(
                    f"Microsoft Edge exited (code {self.process.returncode}) "
                    f"before publishing DevToolsActivePort."
                )
            self._sleeper(DEVTOOLS_POLL_INTERVAL_S)
        else:
            raise EdgeCdpTimeout(
                "Microsoft Edge did not publish DevToolsActivePort within "
                f"{budget:.0f}s."
            )
        # Step 2: probe /json/version via a proxy-free opener. This is the
        # contractual readiness signal: returning a webSocketDebuggerUrl
        # means the websocket is actually open.
        probe_deadline = time.monotonic() + budget
        opener = self._opener_factory()
        while time.monotonic() < probe_deadline:
            try:
                payload = _http_json(
                    f"{self.origin}/json/version",
                    timeout=1.0,
                    opener=opener,
                )
                if not _is_loopback_host(
                    urllib.parse.urlsplit(
                        str(payload.get("webSocketDebuggerUrl", ""))
                    ).hostname
                ):
                    raise EdgeCdpError(
                        "Edge /json/version returned a non-loopback "
                        "webSocketDebuggerUrl; refusing to connect."
                    )
                return
            except EdgeCdpError as exc:
                last_error = exc
                if self.process.poll() is not None:
                    raise EdgeCdpError(
                        f"Microsoft Edge exited (code {self.process.returncode}) "
                        f"before /json/version answered: {exc}"
                    ) from exc
                self._sleeper(DEVTOOLS_POLL_INTERVAL_S)
        raise EdgeCdpTimeout(
            f"Edge opened but the DevTools endpoint never answered: {last_error}"
        )

    @property
    def page(self) -> EdgeCdpPage:
        if self._page is None:
            opener = self._opener_factory()
            targets = _http_json(
                f"{self.origin}/json/list", timeout=2.0, opener=opener,
            )
            page_targets = [t for t in targets if t.get("type") == "page"]
            if not page_targets:
                target = _http_json(
                    f"{self.origin}/json/new?about:blank",
                    method="PUT", timeout=3.0, opener=opener,
                )
            else:
                target = page_targets[0]
            websocket_url = str(target["webSocketDebuggerUrl"])
            if not websocket_url:
                raise EdgeCdpError(
                    "Edge /json/list returned a target without "
                    "webSocketDebuggerUrl."
                )
            self._page = EdgeCdpPage(
                target_id=str(target["id"]),
                websocket_url=websocket_url,
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
    """Build the public IMGT/V-QUEST URL for an inline search."""
    params = {
        "species": "human",
        "receptorOrLocusType": "IGH",
        "moleculeType": "cDNA" if molecule_type == "cDNA" else "gDNA",
    }
    return "https://www.imgt.org/IMGT_vquest/vquest?" + urllib.parse.urlencode(params)


def submit_imgt_detailed(
    page: EdgeCdpPage,
    *,
    external_id: str,
    sequence: str,
    molecule_type: str,
    timeout_s: float = 180.0,
) -> None:
    """Submit one pseudonymized sequence for IMGT Detailed HTML output.

    Capturing one sequence at a time guarantees that ``sequence1_*`` DOM IDs
    refer to the expected External ID. The transient form is created in the
    browser; no extra HTTP client, driver, or executable is involved.
    """
    normalized_sequence = "".join(sequence.split()).upper()
    if not normalized_sequence or set(normalized_sequence) - set("ACGTN"):
        raise EdgeCdpError("IMGT evidence sequence contains invalid characters.")
    fasta = f">{external_id}\n{normalized_sequence}\n"
    fields = {
        "species": "human",
        "receptorOrLocusType": "IGH",
        "moleculeType": "cDNA" if molecule_type == "cDNA" else "gDNA",
        "inputType": "inline",
        "sequences": fasta,
        "resultType": "detailed",
        "outputType": "html",
        "dv_nbNtPerLine": "60",
        "dv_nbAlignedSequence": "5",
        "dv_V_GENEalignment": "true",
        "dv_D_GENEalignment": "true",
        "dv_J_GENEalignment": "true",
        "dv_L_REGIONalignment": "true",
        "dv_C_DOMAINalignment": "true",
        "dv_IMGTjctaResults": "true",
        "dv_eligibleD_GENE": "false",
        "dv_JUNCTIONseq": "true",
        "dv_V_REGIONalignment": "true",
        "dv_V_REGIONtranlation": "true",
        "dv_V_REGIONprotdisplay": "true",
        "dv_V_REGIONmuttable": "true",
        "dv_V_REGIONmutstats": "true",
        "dv_V_REGIONhotspots": "true",
        "dv_C_REGIONtranslation": "true",
        "IMGTrefdirSet": "1",
        "IMGTrefdirAlleles": "true",
        "ref_dir_adjustment": "true",
        "V_REGIONsearchIndel": "true",
        "nbD_GENE": "-1",
        "nbVmut": "-1",
        "nbDmut": "-1",
        "nbJmut": "-1",
        "nb5V_REGIONignoredNt": "0",
        "nb3V_REGIONaddedNt": "0",
        "scfv": "false",
        "cllSubsetSearch": "true",
    }
    page.navigate("https://www.imgt.org/IMGT_vquest/analysis", timeout_s=60.0)
    submitted = page.evaluate(
        """(fields) => {
            const form = document.createElement('form');
            form.method = 'POST';
            form.action = '/IMGT_vquest/analysis';
            for (const [name, value] of Object.entries(fields)) {
                const input = document.createElement(name === 'sequences' ? 'textarea' : 'input');
                input.name = name;
                input.value = value;
                form.appendChild(input);
            }
            document.body.appendChild(form);
            form.submit();
            return true;
        }""",
        args=[fields],
    )
    if not submitted:
        raise EdgeCdpError("Could not submit the IMGT Detailed-view form.")
    page._wait_for_load(timeout_s=timeout_s)
    shown_id = page.evaluate(
        "document.querySelector('h3.sequence_title')?.innerText || ''"
    )
    if external_id not in str(shown_id):
        message = page.evaluate(
            "document.querySelector('h3.sequence_title')?.innerText || document.body.innerText"
        )
        raise EdgeCdpError(
            f"IMGT did not return Detailed results for {external_id}: "
            f"{' '.join(str(message).split())[:300]}"
        )


def imgt_result_sequence_count(page: EdgeCdpPage) -> int:
    """Return the number of detailed sequence blocks on the current page."""
    value = page.evaluate("document.querySelectorAll('h3.sequence_title').length")
    return int(value or 0)


def imgt_screenshot_specs(
    page: EdgeCdpPage,
) -> tuple[ImgtScreenshotSpec, ...]:
    """Return the screenshot specs that exist on this IMGT result page."""
    available: list[ImgtScreenshotSpec] = []
    for spec in IMGT_SCREENSHOT_SPECS:
        exists = page.evaluate(
            "(sel) => Boolean(document.querySelector(sel))",
            args=[spec.start_selector],
        )
        if exists:
            available.append(spec)
        elif not spec.optional:
            raise EdgeCdpError(
                f"IMGT result section is missing: {spec.label} "
                f"({spec.start_selector})."
            )
    return tuple(available)


def capture_imgt_evidence(
    page: EdgeCdpPage,
    directory: Path,
    *,
    include_full_page: bool = False,
) -> tuple[Path, ...]:
    """Capture report-oriented crops from one detailed IMGT result page.

    The page must contain exactly one sequence. That makes the on-screen
    External ID unambiguous and prevents one patient's report from silently
    receiving another sequence's screenshots.
    """
    count = imgt_result_sequence_count(page)
    if count != 1:
        raise EdgeCdpError(
            "IMGT evidence capture requires a Detailed view containing exactly "
            f"one analysed sequence (found {count})."
        )
    directory = directory.expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True)
    captured: list[Path] = []
    if include_full_page:
        captured.append(page.capture_full_page(directory / "99_full_page.png"))
    for spec in imgt_screenshot_specs(page):
        path = directory / f"{spec.key}.png"
        result = page.capture_region(
            spec.start_selector,
            path,
            end_selector=spec.end_selector,
            max_height=spec.max_height,
        )
        if result is not None:
            captured.append(result)
    return tuple(captured)


def extract_imgt_text(page: EdgeCdpPage) -> dict[str, str]:
    """Extract the same report-oriented IMGT sections captured as PNGs."""
    sections: dict[str, str] = {}
    for spec in imgt_screenshot_specs(page):
        text = page.evaluate(
            """(startSelector, endSelector) => {
                const start = document.querySelector(startSelector);
                if (!start) return '';
                const end = endSelector ? document.querySelector(endSelector) : null;
                const values = [start.innerText || ''];
                let node = start.nextElementSibling;
                while (node && node !== end) {
                    if (node.matches && node.matches('h4.section_title')) break;
                    values.push(node.innerText || '');
                    node = node.nextElementSibling;
                }
                return values.join('\\n').trim();
            }""",
            args=[spec.start_selector, spec.end_selector],
        )
        sections[spec.key] = (text or "").strip()
    return sections
