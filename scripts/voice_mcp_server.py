#!/usr/bin/env python3
from __future__ import annotations

import argparse
import secrets
import sys
import threading
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from voice_interview.launcher import find_available_port  # noqa: E402
from voice_interview.mcp import run_stdio  # noqa: E402
from voice_interview.server import VoiceBridgeServer  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Mock-Interview stdio MCP server")
    parser.add_argument("--port", type=int)
    args = parser.parse_args()
    port = find_available_port(args.port)
    server = VoiceBridgeServer(("127.0.0.1", port), secrets.token_urlsafe(36))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        run_stdio(server.store)
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
