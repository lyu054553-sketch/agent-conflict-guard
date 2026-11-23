"""Local web dashboard: GET / serves the page, GET /api/state returns the collected state."""
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .detect import collect

PAGE = Path(__file__).resolve().parent / "web" / "monitor.html"


def make_handler(root: str):
    page = PAGE.read_bytes()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            if self.path.startswith("/api/state"):
                body = json.dumps(collect(root), ensure_ascii=False).encode()
                ctype = "application/json; charset=utf-8"
            elif self.path in ("/", "/index.html"):
                body, ctype = page, "text/html; charset=utf-8"
            else:
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

    return Handler


def serve(root: str, port: int = 4317) -> None:
    srv = ThreadingHTTPServer(("127.0.0.1", port), make_handler(root))
    print(f"监控页面：http://127.0.0.1:{port}   （项目 {root}，Ctrl+C 停止）")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
