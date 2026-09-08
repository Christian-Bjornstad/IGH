"""Tests for the dynamic Edge/CDP port discovery path.

The original implementation pre-reserved a TCP port with ``socket.bind`` and
then asked Edge to bind to the same port. Under the managed Edge broker on
the hospital workstation that contract is unreliable: the broker can
listen on a different port while we keep probing a dead one.

The replacement path:

* launches Edge with ``--remote-debugging-port=0`` so the OS picks the port;
* deletes any stale ``DevToolsActivePort`` file before launch;
* reads the actual port from the file Edge writes on startup;
* probes ``/json/version`` through a proxy-free urllib opener (the
  hospital's enterprise proxy would otherwise intercept loopback traffic);
* connects to the websocket with ``suppress_origin=True`` (no Origin
  header), and no longer passes ``--remote-allow-origins``.

These tests exercise the helpers in isolation — they never spawn the real
``msedge.exe``.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

import pytest

from igh_merge import edge_cdp
from igh_merge.edge_cdp import (
    EdgeCdpError,
    EdgeCdpTimeout,
    EdgeCdpSession,
    _DEVTOOLS_ACTIVE_PORT_NAME,
    _is_loopback_host,
    _proxy_free_opener,
    _read_devtools_active_port,
    launch_edge,
)


# ---------------------------------------------------------------------------
# _read_devtools_active_port
# ---------------------------------------------------------------------------


def _write_devtools_port(profile: Path, port: int) -> None:
    """Helper: write a valid DevToolsActivePort file."""
    (profile / _DEVTOOLS_ACTIVE_PORT_NAME).write_text(
        f"{port}\nC:\\does\\not\\exist\\{port}\n", encoding="utf-8"
    )


def test_read_devtools_active_port_returns_announced_port(tmp_path: Path) -> None:
    _write_devtools_port(tmp_path, 9222)
    assert _read_devtools_active_port(tmp_path) == 9222


def test_read_devtools_active_port_missing_returns_none(tmp_path: Path) -> None:
    assert _read_devtools_active_port(tmp_path) is None


def test_read_devtools_active_port_rejects_zero(tmp_path: Path) -> None:
    (tmp_path / _DEVTOOLS_ACTIVE_PORT_NAME).write_text("0\nignored\n", encoding="utf-8")
    assert _read_devtools_active_port(tmp_path) is None


def test_read_devtools_active_port_rejects_out_of_range(tmp_path: Path) -> None:
    (tmp_path / _DEVTOOLS_ACTIVE_PORT_NAME).write_text("70000\n", encoding="utf-8")
    assert _read_devtools_active_port(tmp_path) is None
    (tmp_path / _DEVTOOLS_ACTIVE_PORT_NAME).write_text("not-a-port\n", encoding="utf-8")
    assert _read_devtools_active_port(tmp_path) is None


# ---------------------------------------------------------------------------
# _proxy_free_opener
# ---------------------------------------------------------------------------


def test_proxy_free_opener_has_no_proxy_handler() -> None:
    opener = _proxy_free_opener()
    # ``build_opener(ProxyHandler({}))`` strips the default handlers; the
    # resulting opener must not have a ProxyHandler installed.
    proxy_handlers = [
        handler for handler in opener.handlers
        if handler.__class__.__name__ == "ProxyHandler"
    ]
    assert proxy_handlers == []


# ---------------------------------------------------------------------------
# launch_edge arguments (no real Edge)
# ---------------------------------------------------------------------------


class _FakeProcess:
    def __init__(self, returncode: int | None = None) -> None:
        self.returncode = returncode

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.returncode = -1

    def wait(self, timeout: float | None = None) -> int:
        return -1

    def kill(self) -> None:
        self.returncode = -9


def _build_fake_session(process: _FakeProcess, profile: Path,
                        port_reader=None, opener_factory=None,
                        sleeper=None) -> EdgeCdpSession:
    return EdgeCdpSession(
        process=process,  # type: ignore[arg-type]
        profile_directory=profile,
        startup_timeout_s=2.0,
        sleeper=sleeper or (lambda _s: None),
        opener_factory=opener_factory or (lambda: _proxy_free_opener()),
        port_reader=port_reader or _read_devtools_active_port,
    )


def _version_opener(port: int) -> urllib.request.OpenerDirector:
    """Build an opener that returns a plausible /json/version payload.

    The opener's ``open`` does not actually touch the network; it just
    returns a ``_FakeResponse`` carrying a ``webSocketDebuggerUrl`` whose
    hostname is loopback. That is enough for ``wait_for_endpoint`` to
    consider Edge ready.
    """

    class _FakeResponse:
        def __init__(self, payload: bytes) -> None:
            self._payload = payload

        def read(self) -> bytes:
            return self._payload

        def __enter__(self) -> "_FakeResponse":
            return self

        def __exit__(self, *exc_info: object) -> None:
            return None

    body = json.dumps(
        {
            "Browser": "Edg/151.0.0.0",
            "Protocol-Version": "1.3",
            "User-Agent": "Edg/151.0.0.0",
            "V8-Version": "0",
            "WebKit-Version": "0",
            "webSocketDebuggerUrl": (
                f"ws://127.0.0.1:{port}/devtools/browser/abc"
            ),
        }
    ).encode("utf-8")

    class _FakeOpener:
        def open(self, request, timeout=5.0):  # noqa: ARG002
            return _FakeResponse(body)

    return _FakeOpener()  # type: ignore[return-value]


def test_launch_edge_passes_dynamic_port_zero_and_no_allow_origins(tmp_path: Path) -> None:
    """The launch command must use port 0 and must NOT pass --remote-allow-origins."""
    captured: dict[str, list[str]] = {}

    def fake_runner(arguments, *args, **kwargs):
        captured["arguments"] = list(arguments)
        return _FakeProcess(returncode=None)

    def fake_port_reader(profile: Path) -> int | None:
        # On the first read, publish the announced port. The session's
        # ``wait_for_endpoint`` only checks the file once per deadline tick,
        # so this is enough to break out of the loop.
        file = profile / _DEVTOOLS_ACTIVE_PORT_NAME
        if not file.exists():
            file.write_text("9333\nignored\n", encoding="utf-8")
        return 9333

    profile = tmp_path / "profile"
    profile.mkdir()
    with launch_edge(
        profile,
        background=False,
        startup_timeout_s=1.0,
        sleeper=lambda _s: None,
        opener_factory=lambda: _version_opener(9333),
        process_runner=fake_runner,
        port_reader=fake_port_reader,
    ) as session:
        # Session.port is what Edge actually announced (9333), not 0.
        assert session.port == 9333

    args = captured["arguments"]
    assert "--remote-debugging-port=0" in args
    assert not any(arg.startswith("--remote-allow-origins") for arg in args)


def test_launch_edge_deletes_stale_devtools_port_file(tmp_path: Path) -> None:
    """A stale DevToolsActivePort from a prior crash must be removed before launch."""
    profile = tmp_path / "profile"
    profile.mkdir()
    stale = profile / _DEVTOOLS_ACTIVE_PORT_NAME
    stale.write_text("5555\n", encoding="utf-8")
    assert stale.exists()

    def fake_runner(arguments, *args, **kwargs):
        # The runner is only invoked after the stale file was deleted.
        assert not stale.exists()
        return _FakeProcess(returncode=None)

    with launch_edge(
        profile,
        background=False,
        startup_timeout_s=1.0,
        sleeper=lambda _s: None,
        opener_factory=lambda: _version_opener(9222),
        process_runner=fake_runner,
        port_reader=lambda _p: 9222,  # pretend the file was already republished
    ):
        pass


# ---------------------------------------------------------------------------
# wait_for_endpoint failure modes
# ---------------------------------------------------------------------------


def test_wait_for_endpoint_raises_when_process_exits_early(tmp_path: Path) -> None:
    profile = tmp_path / "profile"
    profile.mkdir()
    process = _FakeProcess(returncode=42)
    session = _build_fake_session(process, profile)

    with pytest.raises(EdgeCdpError) as excinfo:
        session.wait_for_endpoint(timeout_s=2.0)
    assert "exited" in str(excinfo.value).lower()
    assert "42" in str(excinfo.value)


def test_wait_for_endpoint_raises_when_no_port_published(tmp_path: Path) -> None:
    profile = tmp_path / "profile"
    profile.mkdir()
    process = _FakeProcess(returncode=None)
    session = _build_fake_session(
        process, profile,
        sleeper=lambda _s: None,  # do not sleep; fail fast
    )

    with pytest.raises(EdgeCdpTimeout) as excinfo:
        session.wait_for_endpoint(timeout_s=0.05)
    assert "devtoolsactiveport" in str(excinfo.value).lower()


def test_wait_for_endpoint_uses_announced_port_and_origin(tmp_path: Path) -> None:
    """Once a port is announced, session.port/origin must reflect it."""
    profile = tmp_path / "profile"
    profile.mkdir()
    process = _FakeProcess(returncode=None)
    session = _build_fake_session(
        process, profile,
        sleeper=lambda _s: None,
    )
    # Pre-seed the file so the first read returns a port.
    _write_devtools_port(profile, 9444)
    # Pretend /json/version succeeds and announces the same port.
    session._opener_factory = lambda: _version_opener(9444)
    session.wait_for_endpoint(timeout_s=1.0)
    # After a successful wait_for_endpoint, the port and origin are live.
    assert session.port == 9444
    assert session.origin == "http://127.0.0.1:9444"


# ---------------------------------------------------------------------------
# websocket.create_connection suppression
# ---------------------------------------------------------------------------


def test_edge_cdp_page_uses_suppress_origin_and_no_origin() -> None:
    """EdgeCdpPage must not send an Origin header (Edge 111+ rejects it)."""
    captured: dict[str, object] = {}

    class FakeWebSocket:
        def __init__(self, *args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs

        def close(self) -> None:  # pragma: no cover - unused here
            pass

    fake_module = type("M", (), {
        "create_connection": lambda *a, **kw: FakeWebSocket(*a, **kw),
    })
    with patch.dict("sys.modules", {"websocket": fake_module}):
        page = edge_cdp.EdgeCdpPage(
            target_id="abc",
            websocket_url="ws://127.0.0.1:9333/devtools/page/abc",
        )
    page.close()
    kwargs = captured["kwargs"]
    assert kwargs.get("suppress_origin") is True
    assert "origin" not in kwargs


def test_edge_cdp_page_rejects_non_loopback_websocket_host() -> None:
    with patch.dict("sys.modules", {"websocket": type("M", (), {
        "create_connection": lambda *a, **kw: object(),
    })()}):
        with pytest.raises(EdgeCdpError) as excinfo:
            edge_cdp.EdgeCdpPage(
                target_id="abc",
                websocket_url="ws://example.com/devtools/page/abc",
            )
    assert "loopback" in str(excinfo.value).lower()


def test_edge_cdp_page_rejects_non_devtools_websocket_path() -> None:
    with patch.dict("sys.modules", {"websocket": type("M", (), {
        "create_connection": lambda *a, **kw: object(),
    })()}):
        with pytest.raises(EdgeCdpError):
            edge_cdp.EdgeCdpPage(
                target_id="abc",
                websocket_url="ws://127.0.0.1:9333/notdevtools",
            )


# ---------------------------------------------------------------------------
# Helpers exposed for the GUI still work
# ---------------------------------------------------------------------------


def test_is_loopback_host_recognises_canonical_names() -> None:
    assert _is_loopback_host("127.0.0.1")
    assert _is_loopback_host("localhost")
    assert _is_loopback_host("::1")
    assert _is_loopback_host("LOCALHOST")
    assert not _is_loopback_host("example.com")
    assert not _is_loopback_host(None)
    assert not _is_loopback_host("")
