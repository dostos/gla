"""Minimal HTTP client for talking to the engine REST API.

The CLI reaches the engine either over a Unix domain socket (production —
the socket lives inside the session directory) or via plain TCP on
``127.0.0.1:<port>``.  Tests typically inject a pre-bound callable
(e.g. ``starlette.testclient.TestClient``) so we never touch the network.

Usage:

    client = RestClient.from_session(session)
    ov = client.get_json("/api/v1/frames/current/overview")

Raises :class:`RestError` on non-2xx HTTP responses or transport errors.
"""

from __future__ import annotations

import http.client
import json
import socket
import urllib.parse
import urllib.request
from typing import Any, Callable, Dict, Optional


class RestError(Exception):
    """Transport or HTTP-level failure when talking to the engine."""

    def __init__(self, message: str, *, status: Optional[int] = None):
        super().__init__(message)
        self.status = status


class _UDSHTTPConnection(http.client.HTTPConnection):
    """HTTPConnection that talks over a Unix domain socket."""

    def __init__(self, socket_path: str, timeout: float = 5.0):
        # Host is unused by HTTPConnection's transport code once we override
        # the socket, but it does end up in the ``Host:`` header.
        super().__init__("localhost", timeout=timeout)
        self._socket_path = socket_path

    def connect(self):  # pragma: no cover - exercised only against a live engine
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        sock.connect(self._socket_path)
        self.sock = sock


HttpCallable = Callable[[str, str, Dict[str, str]], Any]
"""A pluggable transport used by tests.

Signature: ``(method, path, headers) -> dict``. The implementation is
responsible for performing auth and JSON decoding.
"""


class RestClient:
    """Thin JSON-over-HTTP client with pluggable transport.

    Production path: connects over either a Unix socket or 127.0.0.1:<port>.
    Test path: pass ``http_callable=<fn>`` and we hand everything to that fn.
    """

    def __init__(
        self,
        *,
        token: str = "",
        socket_path: Optional[str] = None,
        host: str = "127.0.0.1",
        port: Optional[int] = None,
        http_callable: Optional[HttpCallable] = None,
        timeout: float = 5.0,
    ):
        self._token = token
        self._socket_path = socket_path
        self._host = host
        self._port = port
        self._http_callable = http_callable
        self._timeout = timeout

    # ---- Construction helpers ------------------------------------------------

    @classmethod
    def from_session(cls, session, *, timeout: float = 5.0) -> "RestClient":
        """Build a client pointing at the given :class:`Session` via TCP.

        (UDS support is available via the ``socket_path`` kwarg; the engine
        currently listens on 127.0.0.1 for localhost REST, so TCP is the
        default.)
        """
        return cls(
            token=session.read_token(),
            port=session.read_port(),
            timeout=timeout,
        )

    # ---- Public API ----------------------------------------------------------

    def get_json(self, path: str) -> Any:
        return self._request("GET", path)

    def post_json(self, path: str, body: Any) -> Any:
        return self._request("POST", path, body=body)

    # ---- Internals -----------------------------------------------------------

    def _headers(self) -> Dict[str, str]:
        hdrs: Dict[str, str] = {"Accept": "application/json"}
        if self._token:
            hdrs["Authorization"] = f"Bearer {self._token}"
        return hdrs

    def _request(self, method: str, path: str, *, body: Any = None) -> Any:
        headers = self._headers()
        # -------- Injected transport path (tests) ---------------------
        if self._http_callable is not None:
            return self._http_callable(method, path, headers, body)

        # -------- UDS path --------------------------------------------
        if self._socket_path is not None:  # pragma: no cover - live-engine only
            conn = _UDSHTTPConnection(self._socket_path, timeout=self._timeout)
            payload = None
            if body is not None:
                payload = json.dumps(body).encode("utf-8")
                headers["Content-Type"] = "application/json"
            try:
                conn.request(method, path, body=payload, headers=headers)
                resp = conn.getresponse()
                raw = resp.read()
                if resp.status >= 400:
                    raise RestError(
                        f"{method} {path} → HTTP {resp.status}: {raw!r}",
                        status=resp.status,
                    )
                return json.loads(raw) if raw else None
            finally:
                conn.close()

        # -------- TCP path (default for current engine) ---------------
        if self._port is None:
            raise RestError("No transport configured (no port, socket, or callable)")
        url = f"http://{self._host}:{self._port}{path}"
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                raw = resp.read()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as exc:  # pragma: no cover
            raise RestError(
                f"{method} {path} → HTTP {exc.code}: {exc.read()!r}",
                status=exc.code,
            ) from exc
        except urllib.error.URLError as exc:  # pragma: no cover
            raise RestError(f"{method} {path} transport error: {exc}") from exc
