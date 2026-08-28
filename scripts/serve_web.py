from __future__ import annotations

import argparse
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
    args = parser.parse_args()
    with make_server(args.host, args.port, app) as server:
        print(f"Shuorenhua Bench: http://{args.host}:{args.port}")
        server.serve_forever()


if __name__ == "__main__":
    main()
