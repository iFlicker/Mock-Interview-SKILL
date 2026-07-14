from __future__ import annotations

import json
import sys
from typing import Any, Callable

from voice_interview import PROTOCOL_VERSION
from voice_interview.store import BridgeError, SessionStore


TOOLS: list[dict[str, Any]] = [
    {
        "name": "create_interview_session",
        "description": "创建本地网页语音面试会话。不要传递完整简历。",
        "inputSchema": {
            "type": "object",
            "required": ["config_summary", "interviewer", "language"],
            "properties": {
                "config_summary": {"type": "object"},
                "interviewer": {
                    "type": "object",
                    "required": ["name", "role"],
                    "properties": {
                        "name": {"type": "string"},
                        "role": {"type": "string"},
                    },
                },
                "language": {"type": "string"},
                "tts": {
                    "type": "object",
                    "properties": {"rate": {"type": "number", "minimum": 0.6, "maximum": 1.6}},
                },
            },
        },
    },
    {
        "name": "send_interviewer_message",
        "description": "幂等地推送面试官消息。凡是要求候选人回答的内容必须使用 interviewer_question 和新的 message_id；interviewer_message 只用于不要求回答的陈述。",
        "inputSchema": {
            "type": "object",
            "required": ["session_id", "message_id", "display_text"],
            "properties": {
                "session_id": {"type": "string"},
                "message_id": {"type": "string"},
                "message_type": {
                    "type": "string",
                    "enum": [
                        "interviewer_question",
                        "interviewer_message",
                        "system_status",
                        "interview_end",
                    ],
                },
                "display_text": {"type": "string"},
                "speech_text": {"type": "string"},
                "auto_speak": {"type": "boolean"},
                "language": {"type": "string"},
                "timestamp": {"type": "string"},
            },
        },
    },
    {
        "name": "wait_for_candidate_reply",
        "description": "短暂等待指定 interviewer_question 的回答或控制指令；已回答的问题会立即返回原回答，最多等待 25 秒。",
        "inputSchema": {
            "type": "object",
            "required": ["session_id"],
            "properties": {
                "session_id": {"type": "string"},
                "question_id": {"type": "string"},
                "cursor": {"type": "integer", "minimum": 0},
                "timeout_ms": {"type": "integer", "minimum": 0, "maximum": 25000},
            },
        },
    },
    {
        "name": "get_session_events",
        "description": "按递增 sequence 获取 cursor 之后的会话事件。",
        "inputSchema": {
            "type": "object",
            "required": ["session_id"],
            "properties": {
                "session_id": {"type": "string"},
                "cursor": {"type": "integer", "minimum": 0},
                "timeout_ms": {"type": "integer", "minimum": 0, "maximum": 25000},
            },
        },
    },
    {
        "name": "close_interview_session",
        "description": "幂等地关闭网页会话，停止网页继续提交，不删除面试证据。",
        "inputSchema": {
            "type": "object",
            "required": ["session_id"],
            "properties": {
                "session_id": {"type": "string"},
                "reason": {"type": "string", "enum": ["completed", "switch_to_text"]},
            },
        },
    },
]


class MCPApplication:
    def __init__(self, store: SessionStore):
        self.store = store

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        session_id = arguments.get("session_id")
        if name != "create_interview_session" and isinstance(session_id, str) and session_id:
            self.store.touch_agent(session_id)
        handlers: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
            "create_interview_session": lambda args: self.store.create_session(
                args.get("config_summary") or {},
                args.get("interviewer") or {},
                args.get("language") or "zh-CN",
                args.get("tts") or {},
            ),
            "send_interviewer_message": self.store.send_interviewer_message,
            "wait_for_candidate_reply": self.store.wait_for_candidate_reply,
            "get_session_events": lambda args: self.store.get_events(
                args.get("session_id", ""),
                int(args.get("cursor", 0)),
                int(args.get("timeout_ms", 0)),
            ),
            "close_interview_session": self.store.close_session,
        }
        handler = handlers.get(name)
        if not handler:
            raise BridgeError("tool_not_found", f"未知工具：{name}", 404)
        return handler(arguments)

    def handle_jsonrpc(self, request: dict[str, Any]) -> dict[str, Any] | None:
        if not isinstance(request, dict):
            return self._error(None, -32600, "Invalid Request")
        request_id = request.get("id")
        method = request.get("method")
        if not isinstance(method, str):
            return self._error(request_id, -32600, "Invalid Request")
        if method.startswith("notifications/"):
            return None
        try:
            if method == "initialize":
                params = request.get("params") or {}
                if not isinstance(params, dict):
                    raise TypeError("params must be an object")
                result = {
                    "protocolVersion": params.get("protocolVersion", "2024-11-05"),
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": "mock-interview-voice", "version": PROTOCOL_VERSION},
                    "instructions": "网页仅是输入输出通道。面试策略、证据账本、评分和报告仍由 Mock-Interview Skill 维护。等待回答请使用不超过 25 秒的短轮询并携带 cursor。",
                }
            elif method == "tools/list":
                result = {"tools": TOOLS}
            elif method == "tools/call":
                params = request.get("params") or {}
                if not isinstance(params, dict):
                    raise TypeError("params must be an object")
                arguments = params.get("arguments") or {}
                if not isinstance(arguments, dict):
                    raise TypeError("arguments must be an object")
                payload = self.call_tool(params.get("name", ""), arguments)
                result = {
                    "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}],
                    "structuredContent": payload,
                    "isError": False,
                }
            elif method == "ping":
                result = {}
            else:
                return self._error(request_id, -32601, "Method not found")
            return {"jsonrpc": "2.0", "id": request_id, "result": result}
        except BridgeError as exc:
            return self._error(request_id, -32000, exc.message, {"bridge_code": exc.code})
        except (TypeError, ValueError) as exc:
            return self._error(request_id, -32602, str(exc))

    @staticmethod
    def _error(
        request_id: Any, code: int, message: str, data: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        error: dict[str, Any] = {"code": code, "message": message}
        if data:
            error["data"] = data
        return {"jsonrpc": "2.0", "id": request_id, "error": error}


def run_stdio(store: SessionStore) -> None:
    app = MCPApplication(store)
    for line in sys.stdin:
        try:
            request = json.loads(line)
            response = app.handle_jsonrpc(request)
        except json.JSONDecodeError:
            response = MCPApplication._error(None, -32700, "Parse error")
        if response is not None:
            sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            sys.stdout.flush()
