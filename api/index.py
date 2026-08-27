"""Minimal Vercel entrypoint for the benchmark service.

The repository is primarily a library and CLI. This small WSGI app gives Vercel
an explicit health/API surface without pulling the benchmark's optional
evaluation dependencies into the deployment.
"""

import json
from typing import Callable, Iterable


def app(environ: dict, start_response: Callable) -> Iterable[bytes]:
    path = environ.get("PATH_INFO", "/")
    if path == "/health":
        payload = {"status": "ok", "service": "shuorenhua-bench"}
        status = "200 OK"
    elif path in {"/", ""}:
        payload = {
            "name": "Shuorenhua Bench",
            "version": "0.1.0",
            "message": "Benchmark API is running. Use the repository CLI for evaluation.",
        }
        status = "200 OK"
    else:
        payload = {"error": "not found"}
        status = "404 Not Found"

    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    start_response(
        status,
        [("Content-Type", "application/json; charset=utf-8"), ("Content-Length", str(len(body)))],
    )
    return [body]
