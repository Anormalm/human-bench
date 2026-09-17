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
from api.rater import create_rater_app


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve the local annotation interface")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8000, type=int)
    parser.add_argument("--report", type=Path, help="Evaluation report to display")
    parser.add_argument("--bundle", type=Path, help="Assigned annotation packet to display")
    parser.add_argument("--judge-audit", type=Path, help="Judge comparison audit to display")
    parser.add_argument("--rater-site", type=Path, help="Serve a frozen rater site with no workbench routes")
    parser.add_argument("--collection", type=Path, help="Verified coordinator collection snapshot to display")
    args = parser.parse_args()
    if args.rater_site and any((args.report, args.bundle, args.judge_audit, args.collection)):
        parser.error("--rater-site cannot be combined with workbench report options")
    application = create_rater_app(args.rater_site) if args.rater_site else app
    for name, path in (("SHUORENHUA_REPORT", args.report), ("SHUORENHUA_BUNDLE", args.bundle),
                       ("SHUORENHUA_JUDGE_AUDIT", args.judge_audit),
                       ("SHUORENHUA_COLLECTION", args.collection)):
        if path is not None:
            if not path.is_file():
                parser.error(f"file does not exist: {path}")
            os.environ[name] = str(path.resolve())
    with make_server(args.host, args.port, application) as server:
        print(f"Shuorenhua Bench: http://{args.host}:{args.port}")
        if args.rater_site:
            print(f"Rater-only server. Assigned links: {args.rater_site.resolve() / 'README.md'}")
        server.serve_forever()


if __name__ == "__main__":
    main()
