"""Local dashboard server: the page, a full state + history fetch, and a server-sent
event stream that pushes each new engine snapshot (at most ~4 a second)."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import ingest

PAGE = Path(__file__).with_name("dashboard.html")
MAPJS = Path(__file__).parent.parent / "web" / "mapbook.js"


def serve(engine, host: str = "127.0.0.1", port: int = 8765) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, body: bytes, ctype: str):
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path in ("/", "/index.html"):
                self._send(PAGE.read_bytes(), "text/html; charset=utf-8")
            elif self.path == "/state":
                with engine.cond:
                    body = engine.snapshot_bytes
                self._send(body, "application/json")
            elif self.path == "/mapbook.js":
                self._send(MAPJS.read_bytes(), "text/javascript; charset=utf-8")
            elif self.path == "/book.json":
                self._send(engine.book_bytes or b"null", "application/json")
            elif self.path == "/history":
                self._send(engine.history_json(), "application/json")
            elif self.path == "/events":
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                seen = -1
                try:
                    while not engine.stop.is_set():
                        with engine.cond:
                            if engine.snapshot_version == seen:
                                engine.cond.wait(timeout=15)
                            v, body = engine.snapshot_version, engine.snapshot_bytes
                        if v == seen:
                            self.wfile.write(b": keepalive\n\n")
                        else:
                            seen = v
                            self.wfile.write(b"data: " + body + b"\n\n")
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    pass
            elif self.path == "/bookmarklet":
                self._send(ingest.bookmarklet(port).encode(), "text/plain; charset=utf-8")
            else:
                self.send_error(404)

        def _cors(self):
            # the bookmark posts from the state's https page to this local server
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Allow-Private-Network", "true")

        def do_OPTIONS(self):
            self.send_response(204)
            self._cors()
            self.end_headers()

        def do_POST(self):
            if not self.path.startswith("/ingest/"):
                return self.send_error(404)
            n = int(self.headers.get("Content-Length") or 0)
            if n <= 0 or n > 20_000_000:
                return self.send_error(413)
            page = self.rfile.read(n).decode("utf-8", "replace")
            try:
                info = ingest.receive(self.path.rsplit("/", 1)[-1].upper(), page)
            except Exception as e:
                info = dict(error=repr(e)[:200], counties=0, votes=0)
            body = json.dumps(info).encode()
            self.send_response(200)
            self._cors()
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    srv = ThreadingHTTPServer((host, port), Handler)
    srv.daemon_threads = True
    return srv
