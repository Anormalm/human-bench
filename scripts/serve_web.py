from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from wsgiref.simple_server import make_server

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.index import app


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve the local annotation interface")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8000, type=int)
    parser.add_argument("--report", type=Path, help="Evaluation report to display")
    parser.add_argument("--bundle", type=Path, help="Assigned annotation packet to display")
    parser.add_argument("--judge-audit", type=Path, help="Judge comparison audit to display")
    args = parser.parse_args()
    for name, path in (("SHUORENHUA_REPORT", args.report), ("SHUORENHUA_BUNDLE", args.bundle),
                       ("SHUORENHUA_JUDGE_AUDIT", args.judge_audit)):
        if path is not None:
            if not path.is_file():
                parser.error(f"file does not exist: {path}")
            os.environ[name] = str(path.resolve())
    with make_server(args.host, args.port, app) as server:
        print(f"Shuorenhua Bench: http://{args.host}:{args.port}")
        server.serve_forever()


if __name__ == "__main__":
    main()
