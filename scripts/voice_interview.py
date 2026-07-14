#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from voice_interview.launcher import (  # noqa: E402
    WaitAlreadyActive,
    call_runtime_tool,
    open_runtime_room,
    read_runtime,
    start_voice_interview,
    stop_runtime,
    wait_for_runtime_event,
)


def parse_json(value: str, label: str) -> dict:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"{label} 不是有效 JSON：{exc}") from exc
    if not isinstance(parsed, dict):
        raise SystemExit(f"{label} 必须是 JSON 对象。")
    return parsed


def main() -> None:
    parser = argparse.ArgumentParser(description="管理网页语音模拟面试室")
    subparsers = parser.add_subparsers(dest="command", required=True)

    start = subparsers.add_parser("start")
    start.add_argument("--config-summary", required=True)
    start.add_argument("--interviewer", required=True)
    start.add_argument("--language", default="zh-CN")
    start.add_argument("--tts", default='{"rate": 1.0}')
    start.add_argument("--port", type=int)
    start.add_argument("--open-immediately", action="store_true")
    start.add_argument("--no-open", action="store_true", help=argparse.SUPPRESS)

    open_room = subparsers.add_parser("open")
    open_room.add_argument("--runtime", required=True)

    call = subparsers.add_parser("call")
    call.add_argument("--runtime", required=True)
    call.add_argument("--tool", required=True)
    call.add_argument("--arguments", required=True)

    wait = subparsers.add_parser("wait")
    wait.add_argument("--runtime", required=True)
    wait.add_argument("--question-id")
    wait.add_argument("--cursor", type=int, default=0)
    wait.add_argument("--timeout-ms", type=int, default=20_000)

    status = subparsers.add_parser("status")
    status.add_argument("--runtime", required=True)

    stop = subparsers.add_parser("stop")
    stop.add_argument("--runtime", required=True)

    args = parser.parse_args()
    if args.command == "start":
        result = start_voice_interview(
            parse_json(args.config_summary, "config-summary"),
            parse_json(args.interviewer, "interviewer"),
            args.language,
            parse_json(args.tts, "tts"),
            preferred_port=args.port,
            open_browser=args.open_immediately and not args.no_open,
        )
    elif args.command == "open":
        result = open_runtime_room(args.runtime)
    elif args.command == "call":
        result = call_runtime_tool(
            args.runtime, args.tool, parse_json(args.arguments, "arguments")
        )
    elif args.command == "wait":
        try:
            result = wait_for_runtime_event(
                args.runtime,
                question_id=args.question_id,
                cursor=args.cursor,
                timeout_ms=args.timeout_ms,
                on_heartbeat=lambda heartbeat: print(
                    json.dumps(heartbeat, ensure_ascii=False), flush=True
                ),
            )
        except WaitAlreadyActive as exc:
            result = exc.as_result()
    elif args.command == "status":
        runtime = read_runtime(args.runtime)
        result = {
            "session_id": runtime["session_id"],
            "room_url": runtime["room_url"],
            "host": runtime["host"],
            "mode": runtime["mode"],
        }
    else:
        result = stop_runtime(args.runtime)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
