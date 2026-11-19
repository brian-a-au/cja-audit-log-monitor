"""A small local stand-in for IMS and the audit log API, for tests that run a real process.

It listens on 127.0.0.1 only and never talks to the network.
"""

from __future__ import annotations

import json
import os
import sys
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

AUDIT_PATH = "/auditlogs/api/v1/auditlogs"


def raw_entry(i: int, **overrides: Any) -> dict[str, Any]:
    """One audit log entry in the API's own shape."""
    entry: dict[str, Any] = {
        "id": f"id-{i}",
        "dateCreated": f"2026-01-15T10:{i % 60:02d}:00.000Z",
        "action": "CREATE",
        "component": {"id": f"comp-{i}", "idType": "PROJECT", "name": f"Component {i}"},
        "user": {"id": f"U{i}@AdobeID", "name": f"User {i}", "email": f"user{i}@example.com"},
        "description": f"entry {i}",
    }
    entry.update(overrides)
    return entry


@dataclass
class FakeApi:
    """State shared between the test and the server thread."""

    entries: list[dict[str, Any]] = field(default_factory=list)
    requests: list[dict[str, list[str]]] = field(default_factory=list)
    hook_posts: list[dict[str, Any]] = field(default_factory=list)
    # When set, the next audit log request waits until it is cleared.
    block: threading.Event = field(default_factory=threading.Event)
    # Set by the server once a request is held by ``block``.
    blocked: threading.Event = field(default_factory=threading.Event)
    # When set, audit log requests after this many are held, as with ``block``.
    block_after: int | None = None
    url: str = ""
    server: ThreadingHTTPServer | None = None

    def env(self, config_path: Path) -> dict[str, str]:
        """Environment for a child process that talks only to this server."""
        env = dict(os.environ)
        env.update(
            {
                "IMS_BASE_URL": self.url,
                "API_BASE_URL": self.url,
                "ORG_ID": "FAKEORG@AdobeOrg",
                "CLIENT_ID": "fake-client",
                "SECRET": "fake-secret",
                "CJA_CONFIG_PATH": str(config_path),
                "PYTHONUNBUFFERED": "1",
            }
        )
        return env

    def page(self, query: dict[str, list[str]]) -> dict[str, Any]:
        number = int(query.get("pageNumber", ["0"])[0])
        size = int(query.get("pageSize", ["100"])[0])
        chunk = self.entries[number * size : (number + 1) * size]
        total_pages = max(1, -(-len(self.entries) // size))
        return {
            "content": chunk,
            "totalElements": len(self.entries),
            "totalPages": total_pages,
            "numberOfElements": len(chunk),
            "number": number,
            "size": size,
            "first": number == 0,
            "last": number >= total_pages - 1,
        }

    def _hold(self) -> None:
        if self.block.is_set():
            self.blocked.set()
            while self.block.is_set():
                threading.Event().wait(0.05)


def command() -> list[str]:
    """The installed console script, from the same environment as this interpreter."""
    return [str(Path(sys.executable).parent / "cja-audit-log-monitor")]


def start(api: FakeApi) -> FakeApi:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args: Any) -> None:  # keep test output clean
            pass

        def _send(self, status: int, body: Any, headers: dict[str, str] | None = None) -> None:
            data = json.dumps(body).encode() if body is not None else b""
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            for key, value in (headers or {}).items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length)
            path = urlparse(self.path).path
            if path.startswith("/ims/token"):
                self._send(200, {"access_token": "fake-token", "expires_in": 86400})
            elif path == "/hook-block":
                api._hold()
                self._send(200, {})
            elif path == "/redirect":
                self._send(301, None, {"Location": f"{api.url}/moved/SECRETTOKEN"})
            else:
                api.hook_posts.append({"path": path, "body": body.decode(errors="replace")})
                self._send(200, {})

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path != AUDIT_PATH:
                self._send(404, {"error": "not found"})
                return
            query = parse_qs(parsed.query)
            api.requests.append(query)
            if api.block_after is not None and len(api.requests) > api.block_after:
                api.block.set()
            api._hold()
            self._send(200, api.page(query))

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    server.block_on_close = False  # a held request must not hold up the test's teardown
    api.server = server
    api.url = f"http://127.0.0.1:{server.server_address[1]}"
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return api
