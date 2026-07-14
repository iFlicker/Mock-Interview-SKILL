from __future__ import annotations

import copy
import secrets
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from voice_interview import PROTOCOL_VERSION


AGENT_STALE_SECONDS = 45.0


class BridgeError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status

    def as_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


@dataclass
class Session:
    session_id: str
    token: str
    config_summary: dict[str, Any]
    interviewer: dict[str, Any]
    language: str
    tts: dict[str, Any]
    room_url: str
    status: str = "ready"
    interaction_channel: str = "web_voice"
    agent_last_seen: float = field(default_factory=time.monotonic)
    web_connection_count: int = 0
    web_client_ids: set[str] = field(default_factory=set)
    next_sequence: int = 1
    events: list[dict[str, Any]] = field(default_factory=list)
    messages: dict[str, dict[str, Any]] = field(default_factory=dict)
    replies: dict[str, dict[str, Any]] = field(default_factory=dict)
    reply_by_question: dict[str, str] = field(default_factory=dict)
    control_requests: dict[str, str] = field(default_factory=dict)
    closed_at: str | None = None
    condition: threading.Condition = field(
        default_factory=lambda: threading.Condition(threading.RLock())
    )


class SessionStore:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self._sessions: dict[str, Session] = {}
        self._lock = threading.RLock()

    def create_session(
        self,
        config_summary: dict[str, Any],
        interviewer: dict[str, Any],
        language: str,
        tts: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not isinstance(config_summary, dict):
            raise BridgeError("invalid_input", "config_summary 必须是对象。")
        if not isinstance(interviewer, dict):
            raise BridgeError("invalid_input", "interviewer 必须是对象。")
        required_string(interviewer, "name")
        required_string(interviewer, "role")
        if not isinstance(language, str) or not language.strip():
            raise BridgeError("invalid_input", "language 必须是非空字符串。")
        if tts is not None and not isinstance(tts, dict):
            raise BridgeError("invalid_input", "tts 必须是对象。")
        rate = (tts or {}).get("rate", 1.0)
        if isinstance(rate, bool) or not isinstance(rate, (int, float)) or not 0.6 <= rate <= 1.6:
            raise BridgeError("invalid_tts_rate", "TTS 语速必须在 0.6 到 1.6 之间。")
        session_id = uuid.uuid4().hex
        token = secrets.token_urlsafe(32)
        room_url = f"{self.base_url}/room/{session_id}#token={token}"
        session = Session(
            session_id=session_id,
            token=token,
            config_summary=copy.deepcopy(config_summary),
            interviewer=copy.deepcopy(interviewer),
            language=language,
            tts=copy.deepcopy(tts or {"rate": 1.0}),
            room_url=room_url,
        )
        with self._lock:
            self._sessions[session_id] = session
        self._append_event(session, "session_ready", {"status": "ready"})
        return {
            "protocol_version": PROTOCOL_VERSION,
            "session_id": session_id,
            "session_token": token,
            "room_url": room_url,
            "agent_connection_status": "connected",
            "capabilities": {
                "websocket": True,
                "http_fallback": True,
                "tts": "browser",
                "stt": "browser_optional",
                "audio_recording": False,
                "event_cursor": True,
            },
        }

    def get(self, session_id: str) -> Session:
        with self._lock:
            session = self._sessions.get(session_id)
        if not session:
            raise BridgeError("session_not_found", "面试会话不存在。", 404)
        return session

    def touch_agent(self, session_id: str) -> None:
        session = self.get(session_id)
        with session.condition:
            session.agent_last_seen = time.monotonic()

    def is_agent_connected(self, session_id: str) -> bool:
        session = self.get(session_id)
        with session.condition:
            return (
                session.status not in {"ended", "switched_to_text"}
                and time.monotonic() - session.agent_last_seen <= AGENT_STALE_SECONDS
            )

    def authenticate_web(self, session_id: str, token: str | None) -> Session:
        session = self.get(session_id)
        if not token or not secrets.compare_digest(session.token, token):
            raise BridgeError("invalid_session_token", "面试链接无效或已失效。", 401)
        return session

    def _append_event(
        self, session: Session, event_type: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        with session.condition:
            event = {
                "schema_version": PROTOCOL_VERSION,
                "event_id": uuid.uuid4().hex,
                "sequence": session.next_sequence,
                "type": event_type,
                "timestamp": utc_now(),
                "payload": copy.deepcopy(payload),
            }
            session.next_sequence += 1
            session.events.append(event)
            session.condition.notify_all()
            return copy.deepcopy(event)

    def send_interviewer_message(self, args: dict[str, Any]) -> dict[str, Any]:
        session = self.get_required(args, "session_id")
        message_id = required_string(args, "message_id")
        with session.condition:
            existing = session.messages.get(message_id)
            if existing:
                comparable = self._normalise_message(args, existing["timestamp"])
                if existing != comparable:
                    raise BridgeError(
                        "message_id_conflict",
                        "同一 message_id 不能对应不同内容。",
                        409,
                    )
                return {"accepted": True, "duplicate": True, "message": copy.deepcopy(existing)}
            message = self._normalise_message(args)
            if session.status == "switched_to_text":
                raise BridgeError("session_closed", "面试已经结束或切回文字模式。", 409)
            if session.status == "ended" and message["message_type"] != "interview_end":
                raise BridgeError("session_closed", "面试已经结束或切回文字模式。", 409)
            if session.status == "paused" and message["message_type"] not in {"system_status", "interview_end"}:
                raise BridgeError("session_paused", "面试处于暂停状态。", 409)
            session.messages[message_id] = message
        event_type = "system_message" if message["message_type"] in {"system_status", "interview_end"} else "interviewer_message"
        event = self._append_event(session, event_type, {"message": message})
        return {
            "accepted": True,
            "duplicate": False,
            "message": copy.deepcopy(message),
            "sequence": event["sequence"],
        }

    @staticmethod
    def _normalise_message(
        args: dict[str, Any], default_timestamp: str | None = None
    ) -> dict[str, Any]:
        text = required_string(args, "display_text")
        message_type = args.get("message_type", "interviewer_question")
        if message_type not in {
            "interviewer_question",
            "interviewer_message",
            "system_status",
            "interview_end",
        }:
            raise BridgeError("invalid_message_type", "消息类型无效。")
        return {
            "message_id": required_string(args, "message_id"),
            "message_type": message_type,
            "display_text": text,
            "speech_text": args.get("speech_text") or text,
            "auto_speak": bool(args.get("auto_speak", True)),
            "language": args.get("language") or "zh-CN",
            "timestamp": args.get("timestamp") or default_timestamp or utc_now(),
        }

    def submit_candidate_reply(
        self, session_id: str, token: str, args: dict[str, Any]
    ) -> dict[str, Any]:
        session = self.authenticate_web(session_id, token)
        reply_id = required_string(args, "reply_id")
        question_id = required_string(args, "question_id")
        text = required_string(args, "text").strip()
        if not text:
            raise BridgeError("empty_reply", "回答不能为空。")
        source = args.get("source", "keyboard")
        if source not in {"voice", "keyboard", "mixed"}:
            raise BridgeError("invalid_reply_source", "回答来源无效。")
        with session.condition:
            if session.status in {"ended", "switched_to_text"}:
                raise BridgeError("session_closed", "面试已经结束，不能继续回答。", 409)
            if session.status == "paused":
                raise BridgeError("session_paused", "请先继续面试再提交回答。", 409)
            existing = session.replies.get(reply_id)
            if existing:
                comparable = {
                    "reply_id": reply_id,
                    "question_id": question_id,
                    "text": text,
                    "raw_transcript": args.get("raw_transcript"),
                    "source": source,
                    "duration_ms": optional_nonnegative_int(args.get("duration_ms")),
                    "timestamp": args.get("timestamp") or existing["timestamp"],
                }
                if existing != comparable:
                    raise BridgeError(
                        "reply_id_conflict",
                        "同一 reply_id 不能对应不同回答。",
                        409,
                    )
                return {"accepted": True, "duplicate": True, "reply": copy.deepcopy(existing)}
            existing_id = session.reply_by_question.get(question_id)
            if existing_id:
                return {
                    "accepted": True,
                    "duplicate": True,
                    "reply": copy.deepcopy(session.replies[existing_id]),
                }
            if question_id not in session.messages or session.messages[question_id]["message_type"] != "interviewer_question":
                raise BridgeError("question_not_found", "当前问题不存在。", 404)
            reply = {
                "reply_id": reply_id,
                "question_id": question_id,
                "text": text,
                "raw_transcript": args.get("raw_transcript"),
                "source": source,
                "duration_ms": optional_nonnegative_int(args.get("duration_ms")),
                "timestamp": args.get("timestamp") or utc_now(),
            }
            session.replies[reply_id] = reply
            session.reply_by_question[question_id] = reply_id
        event = self._append_event(session, "candidate_reply", {"reply": reply})
        return {
            "accepted": True,
            "duplicate": False,
            "reply": copy.deepcopy(reply),
            "sequence": event["sequence"],
        }

    def add_control(
        self,
        session_id: str,
        token: str,
        control: str,
        control_id: str | None = None,
    ) -> dict[str, Any]:
        session = self.authenticate_web(session_id, token)
        allowed = {"pause", "resume", "skip", "end", "switch_to_text"}
        if control not in allowed:
            raise BridgeError("invalid_control", "不支持的面试控制指令。")
        control_id = control_id or uuid.uuid4().hex
        with session.condition:
            existing_control = session.control_requests.get(control_id)
            if existing_control:
                if existing_control != control:
                    raise BridgeError(
                        "control_id_conflict",
                        "同一 control_id 不能对应不同控制指令。",
                        409,
                    )
                return {
                    "accepted": True,
                    "duplicate": True,
                    "status": session.status,
                }
            if session.status in {"ended", "switched_to_text"}:
                if control in {"end", "switch_to_text"}:
                    return {"accepted": True, "duplicate": True, "status": session.status}
                raise BridgeError("session_closed", "面试会话已经关闭。", 409)
            session.control_requests[control_id] = control
            if control == "pause":
                if session.status == "paused":
                    return {"accepted": True, "duplicate": True, "status": "paused"}
                session.status = "paused"
            elif control == "resume":
                if session.status != "paused":
                    return {"accepted": True, "duplicate": True, "status": session.status}
                session.status = "active"
            elif control == "end":
                session.status = "ended"
                session.closed_at = utc_now()
            elif control == "switch_to_text":
                session.status = "switched_to_text"
                session.interaction_channel = "agent_text"
                session.closed_at = utc_now()
        event = self._append_event(
            session,
            {"pause": "interview_paused", "resume": "interview_resumed", "skip": "question_skipped", "end": "interview_ended", "switch_to_text": "switch_to_text"}[control],
            {"control": control, "status": session.status},
        )
        return {
            "accepted": True,
            "duplicate": False,
            "status": session.status,
            "sequence": event["sequence"],
        }

    def web_connected(
        self,
        session_id: str,
        token: str,
        reconnected: bool,
        client_id: str | None = None,
    ) -> None:
        session = self.authenticate_web(session_id, token)
        client_id = client_id or uuid.uuid4().hex
        with session.condition:
            if client_id in session.web_client_ids:
                return
            session.web_client_ids.add(client_id)
            session.web_connection_count = len(session.web_client_ids)
        self._append_event(
            session,
            "web_reconnected" if reconnected else "web_connected",
            {"connections": session.web_connection_count},
        )

    def web_disconnected(self, session_id: str, client_id: str | None = None) -> None:
        try:
            session = self.get(session_id)
        except BridgeError:
            return
        with session.condition:
            if client_id:
                if client_id not in session.web_client_ids:
                    return
                session.web_client_ids.discard(client_id)
            elif session.web_client_ids:
                session.web_client_ids.pop()
            else:
                return
            session.web_connection_count = len(session.web_client_ids)
        self._append_event(
            session, "web_disconnected", {"connections": session.web_connection_count}
        )

    def get_events(
        self, session_id: str, after: int = 0, timeout_ms: int = 0
    ) -> dict[str, Any]:
        session = self.get(session_id)
        if after < 0:
            raise BridgeError("invalid_cursor", "事件 cursor 不能小于 0。")
        timeout_ms = max(0, min(int(timeout_ms), 25_000))
        deadline = time.monotonic() + timeout_ms / 1000
        with session.condition:
            while timeout_ms and not any(e["sequence"] > after for e in session.events):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                session.condition.wait(remaining)
            events = [copy.deepcopy(e) for e in session.events if e["sequence"] > after]
            next_cursor = events[-1]["sequence"] if events else after
            return {
                "session_id": session_id,
                "events": events,
                "next_cursor": next_cursor,
                "status": session.status,
                "agent_connected": self.is_agent_connected(session_id),
                "timed_out": not events and timeout_ms > 0,
            }

    def wait_for_candidate_reply(self, args: dict[str, Any]) -> dict[str, Any]:
        session_id = required_string(args, "session_id")
        question_id = args.get("question_id")
        cursor = int(args.get("cursor", 0))
        timeout_ms = min(max(int(args.get("timeout_ms", 20_000)), 0), 25_000)
        session = self.get(session_id)
        if question_id:
            with session.condition:
                question = session.messages.get(question_id)
                if not question or question["message_type"] != "interviewer_question":
                    raise BridgeError(
                        "question_not_found",
                        "等待回答时必须使用已推送的 interviewer_question ID。",
                        404,
                    )
                existing_reply_id = session.reply_by_question.get(question_id)
                if existing_reply_id:
                    reply = copy.deepcopy(session.replies[existing_reply_id])
                    sequence = next(
                        (
                            event["sequence"]
                            for event in session.events
                            if event["type"] == "candidate_reply"
                            and event["payload"]["reply"]["reply_id"] == existing_reply_id
                        ),
                        cursor,
                    )
                    return {
                        "status": "reply",
                        "reply": reply,
                        "control": None,
                        "next_cursor": max(cursor, sequence),
                        "duplicate": True,
                    }
        result = self.get_events(session_id, cursor, timeout_ms)
        for event in result["events"]:
            if event["type"] == "candidate_reply":
                reply = event["payload"]["reply"]
                if not question_id or reply["question_id"] == question_id:
                    return {
                        "status": "reply",
                        "reply": reply,
                        "control": None,
                        "next_cursor": event["sequence"],
                    }
            if event["type"] in {
                "interview_paused",
                "interview_resumed",
                "question_skipped",
                "interview_ended",
                "switch_to_text",
            }:
                return {
                    "status": "control",
                    "reply": None,
                    "control": event["payload"]["control"],
                    "next_cursor": event["sequence"],
                }
        return {
            "status": "timeout",
            "reply": None,
            "control": None,
            "next_cursor": result["next_cursor"],
        }

    def snapshot(self, session_id: str, token: str) -> dict[str, Any]:
        session = self.authenticate_web(session_id, token)
        with session.condition:
            timeline = []
            for event in session.events:
                if event["type"] in {"interviewer_message", "system_message"}:
                    item = event["payload"]["message"]
                    timeline.append(
                        {
                            "kind": "system" if event["type"] == "system_message" else "interviewer",
                            "timestamp": item["timestamp"],
                            "data": copy.deepcopy(item),
                        }
                    )
                elif event["type"] == "candidate_reply":
                    item = event["payload"]["reply"]
                    timeline.append(
                        {"kind": "candidate", "timestamp": item["timestamp"], "data": copy.deepcopy(item)}
                    )
            return {
                "protocol_version": PROTOCOL_VERSION,
                "session_id": session.session_id,
                "interviewer": copy.deepcopy(session.interviewer),
                "language": session.language,
                "tts": copy.deepcopy(session.tts),
                "status": session.status,
                "agent_connected": self.is_agent_connected(session_id),
                "interaction_channel": session.interaction_channel,
                "timeline": timeline,
                "cursor": session.next_sequence - 1,
            }

    def close_session(self, args: dict[str, Any]) -> dict[str, Any]:
        session = self.get_required(args, "session_id")
        reason = args.get("reason", "completed")
        if reason not in {"completed", "switch_to_text"}:
            raise BridgeError("invalid_close_reason", "关闭原因无效。")
        with session.condition:
            if session.status == "ended":
                return {"closed": True, "duplicate": True, "status": "ended"}
            if session.status == "switched_to_text":
                return {"closed": True, "duplicate": True, "status": "switched_to_text"}
            session.status = "switched_to_text" if reason == "switch_to_text" else "ended"
            if reason == "switch_to_text":
                session.interaction_channel = "agent_text"
            session.closed_at = utc_now()
        event = self._append_event(
            session,
            "switch_to_text" if reason == "switch_to_text" else "interview_ended",
            {
                "control": "switch_to_text" if reason == "switch_to_text" else "end",
                "status": session.status,
            },
        )
        return {"closed": True, "duplicate": False, "status": session.status, "sequence": event["sequence"]}

    def get_required(self, args: dict[str, Any], key: str) -> Session:
        return self.get(required_string(args, key))


def required_string(args: dict[str, Any], key: str) -> str:
    value = args.get(key)
    if not isinstance(value, str) or not value.strip():
        raise BridgeError("invalid_input", f"{key} 必须是非空字符串。")
    return value


def optional_nonnegative_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise BridgeError("invalid_duration", "duration_ms 必须是非负整数。")
    return value
