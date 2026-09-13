"""Read-only WSGI workbench. Only explicitly allowlisted files are served."""
from __future__ import annotations

import json
import os
from collections.abc import Callable, Iterable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUNDLE_PATH = ROOT / "data/web/demo_bundle.json"
REPORT_PATH = ROOT / "data/web/demo_report.json"
STATIC = {"/": ("index.html", "text/html"), "/app.js": ("app.js", "text/javascript"),
          "/styles.css": ("styles.css", "text/css")}


def _response(start_response, status, content_type, body):
    start_response(status, [
        ("Content-Type", content_type + "; charset=utf-8"), ("Content-Length", str(len(body))),
        ("X-Content-Type-Options", "nosniff"), ("Cache-Control", "no-store"),
        ("Referrer-Policy", "no-referrer"),
        ("Content-Security-Policy", ("default-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
         "font-src 'self' https://fonts.gstatic.com; script-src 'self'; img-src 'self' data:; "
         "object-src 'none'; base-uri 'none'; frame-ancestors 'none'")),
    ])
    return [body]


def app(environ: dict, start_response: Callable) -> Iterable[bytes]:
    path = environ.get("PATH_INFO", "/") or "/"
    if environ.get("REQUEST_METHOD", "GET") not in {"GET", "HEAD"}:
        return _response(start_response, "405 Method Not Allowed", "application/json",
                         b'{"error":"read-only interface"}')
    if path == "/health":
        return _response(start_response, "200 OK", "application/json",
                         json.dumps({"status": "ok", "service": "shuorenhua-bench", "version": "0.5.0"}).encode())
    if path in STATIC:
        file, mime = STATIC[path]
        return _response(start_response, "200 OK", mime, (ROOT / "web" / file).read_bytes())
    if path == "/api/judge-audit":
        configured = os.environ.get("SHUORENHUA_JUDGE_AUDIT")
        target = Path(configured) if configured else None
        if target is not None and target.is_file():
            return _response(start_response, "200 OK", "application/json", target.read_bytes())
        return _response(start_response, "503 Service Unavailable", "application/json",
                         b'{"error":"judge audit not configured"}')
    if path in {"/api/bundle", "/api/report"}:
        target = (Path(os.environ.get("SHUORENHUA_BUNDLE", str(BUNDLE_PATH))) if path == "/api/bundle"
                  else Path(os.environ.get("SHUORENHUA_REPORT", str(REPORT_PATH))))
        if target.is_file():
            return _response(start_response, "200 OK", "application/json", target.read_bytes())
        return _response(start_response, "503 Service Unavailable", "application/json",
                         b'{"error":"file not configured"}')
    return _response(start_response, "404 Not Found", "application/json", b'{"error":"not found"}')
