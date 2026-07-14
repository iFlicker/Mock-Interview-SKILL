from __future__ import annotations

import argparse
import base64
import hashlib
import json
import socket
import struct
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from voice_interview import PROTOCOL_VERSION
from voice_interview.mcp import MCPApplication
from voice_interview.store import BridgeError, SessionStore


WEB_ROOT = Path(__file__).with_name("web")
MAX_BODY_BYTES = 256 * 1024
WEBSOCKET_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


class VoiceBridgeServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], admin_token: str):
        super().__init__(address, VoiceBridgeHandler)
        host, port = self.server_address
        self.admin_token = admin_token
        self.store = SessionStore(f"http://{host}:{port}")
        self.mcp = MCPApplication(self.store)


class VoiceBridgeHandler(BaseHTTPRequestHandler):
    server: VoiceBridgeServer
    protocol_version = "HTTP/1.1"

    def log_message(self, _format: str, *_args: Any) -> None:
        # Intentionally avoid request logging: URLs and payloads may be sensitive.
        return

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/health":
                self._json(200, {"status": "ok", "bind": "127.0.0.1"})
                return
            if parsed.path.startswith("/room/"):
                self._serve_file(WEB_ROOT / "index.html", "text/html; charset=utf-8")
                return
            if parsed.path.startswith("/assets/"):
                name = parsed.path.removeprefix("/assets/")
                if name not in {"app.js", "styles.css"}:
                    raise BridgeError("not_found", "资源不存在。", 404)
                content_type = (
                    "text/javascript; charset=utf-8"
                    if name.endswith(".js")
                    else "text/css; charset=utf-8"
                )
                self._serve_file(WEB_ROOT / name, content_type)
                return
            if parsed.path.startswith("/api/session/"):
                self._handle_api_get(parsed)
                return
            if parsed.path == "/ws":
                self._handle_websocket(parsed)
                return
            raise BridgeError("not_found", "页面不存在。", 404)
        except BridgeError as exc:
            self._json(exc.status, {"error": exc.as_dict()})
        except (TypeError, ValueError):
            self._json(400, {"error": {"code": "invalid_input", "message": "请求参数无效。"}})
        except (BrokenPipeError, ConnectionResetError):
            return

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/mcp":
                self._require_admin()
                request = self._read_json()
                response = self.server.mcp.handle_jsonrpc(request)
                if response is None:
                    self.send_response(HTTPStatus.ACCEPTED)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                else:
                    self._json(
                        200,
                        response,
                        extra_headers={"Mcp-Session-Id": "mock-interview-voice"},
                    )
                return
            if parsed.path.startswith("/api/session/"):
                self._handle_api_post(parsed)
                return
            raise BridgeError("not_found", "接口不存在。", 404)
        except BridgeError as exc:
            self._json(exc.status, {"error": exc.as_dict()})
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._json(400, {"error": {"code": "invalid_json", "message": "请求内容不是有效 JSON。"}})
        except (TypeError, ValueError):
            self._json(400, {"error": {"code": "invalid_input", "message": "请求参数无效。"}})

    def _handle_api_get(self, parsed: Any) -> None:
        self._require_allowed_origin()
        parts = parsed.path.strip("/").split("/")
        if len(parts) != 4:
            raise BridgeError("not_found", "接口不存在。", 404)
        _, _, session_id, action = parts
        query = parse_qs(parsed.query)
        token = first(query, "token")
        if action == "snapshot":
            self._json(200, self.server.store.snapshot(session_id, token or ""))
            return
        if action == "events":
            self.server.store.authenticate_web(session_id, token)
            after = int(first(query, "after") or 0)
            timeout_ms = int(first(query, "timeout_ms") or 0)
            self._json(200, self.server.store.get_events(session_id, after, timeout_ms))
            return
        raise BridgeError("not_found", "接口不存在。", 404)

    def _handle_api_post(self, parsed: Any) -> None:
        self._require_allowed_origin()
        parts = parsed.path.strip("/").split("/")
        if len(parts) != 4:
            raise BridgeError("not_found", "接口不存在。", 404)
        _, _, session_id, action = parts
        query = parse_qs(parsed.query)
        token = first(query, "token") or ""
        payload = self._read_json()
        if action == "candidate-reply":
            self._json(
                200,
                self.server.store.submit_candidate_reply(session_id, token, payload),
            )
            return
        if action == "control":
            self._json(
                200,
                self.server.store.add_control(
                    session_id,
                    token,
                    payload.get("control", ""),
                    payload.get("control_id"),
                ),
            )
            return
        if action == "connect":
            self.server.store.web_connected(
                session_id,
                token,
                bool(payload.get("reconnected")),
                payload.get("client_id"),
            )
            self._json(200, {"connected": True})
            return
        if action == "disconnect":
            self.server.store.authenticate_web(session_id, token)
            self.server.store.web_disconnected(session_id, payload.get("client_id"))
            self._json(200, {"disconnected": True})
            return
        raise BridgeError("not_found", "接口不存在。", 404)

    def _require_admin(self) -> None:
        expected = f"Bearer {self.server.admin_token}"
        actual = self.headers.get("Authorization", "")
        if not secrets_equal(actual, expected):
            raise BridgeError("unauthorized", "Agent 访问凭证无效。", 401)

    def _require_allowed_origin(self) -> None:
        origin = self.headers.get("Origin")
        if not origin:
            return
        parsed = urlparse(origin)
        allowed_hosts = {"127.0.0.1", "localhost", "[::1]", "::1"}
        if (
            parsed.scheme != "http"
            or parsed.hostname not in allowed_hosts
            or parsed.port != self.server.server_port
        ):
            raise BridgeError("origin_not_allowed", "网页来源未获允许。", 403)

    def _read_json(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise BridgeError("invalid_length", "请求长度无效。") from exc
        if length <= 0 or length > MAX_BODY_BYTES:
            raise BridgeError("invalid_body_size", "请求内容为空或过大。", 413)
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(payload, dict):
            raise BridgeError("invalid_json_shape", "请求内容必须是 JSON 对象。")
        return payload

    def _serve_file(self, path: Path, content_type: str) -> None:
        if not path.is_file():
            raise BridgeError("not_found", "资源不存在。", 404)
        body = path.read_bytes()
        self.send_response(200)
        self._security_headers()
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(
        self, status: int, payload: dict[str, Any], extra_headers: dict[str, str] | None = None
    ) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self._security_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        for key, value in (extra_headers or {}).items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _security_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("Permissions-Policy", "camera=(), geolocation=(), microphone=(self)")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; connect-src 'self' ws://127.0.0.1:* ws://localhost:*; "
            "script-src 'self'; style-src 'self'; img-src 'self' data:; media-src 'none'; frame-ancestors 'none'",
        )

    def _handle_websocket(self, parsed: Any) -> None:
        self._require_allowed_origin()
        if self.headers.get("Upgrade", "").lower() != "websocket":
            raise BridgeError("upgrade_required", "需要 WebSocket 连接。", 426)
        query = parse_qs(parsed.query)
        session_id = first(query, "session_id") or ""
        token = first(query, "token") or ""
        after = int(first(query, "after") or 0)
        reconnect = first(query, "reconnect") == "1"
        client_id = first(query, "client_id") or ""
        self.server.store.authenticate_web(session_id, token)
        key = self.headers.get("Sec-WebSocket-Key")
        if not key:
            raise BridgeError("invalid_websocket", "WebSocket 握手无效。")
        accept = base64.b64encode(
            hashlib.sha1((key + WEBSOCKET_GUID).encode()).digest()
        ).decode()
        self.send_response(101, "Switching Protocols")
        self.send_header("Upgrade", "websocket")
        self.send_header("Connection", "Upgrade")
        self.send_header("Sec-WebSocket-Accept", accept)
        self.end_headers()
        self.close_connection = True
        self.connection.settimeout(0.5)
        self.server.store.web_connected(session_id, token, reconnect, client_id)
        try:
            last_agent_connected = self.server.store.is_agent_connected(session_id)
            self._ws_send_json({
                "type": "connected",
                "cursor": after,
                "agent_connected": last_agent_connected,
            })
            while True:
                events = self.server.store.get_events(session_id, after, 500)
                for event in events["events"]:
                    self._ws_send_json({"type": "event", "event": event})
                    after = max(after, event["sequence"])
                agent_connected = self.server.store.is_agent_connected(session_id)
                if agent_connected != last_agent_connected:
                    self._ws_send_json({
                        "type": "agent_status",
                        "agent_connected": agent_connected,
                    })
                    last_agent_connected = agent_connected
                try:
                    incoming = self._ws_read_frame()
                except socket.timeout:
                    continue
                if incoming is None:
                    break
                opcode, payload = incoming
                if opcode == 0x8:
                    self._ws_send_frame(0x8, b"")
                    break
                if opcode == 0x9:
                    self._ws_send_frame(0xA, payload)
                    continue
                if opcode != 0x1:
                    continue
                self._handle_ws_message(session_id, token, json.loads(payload.decode("utf-8")))
        except (BrokenPipeError, ConnectionResetError, OSError, json.JSONDecodeError):
            pass
        finally:
            self.server.store.web_disconnected(session_id, client_id)

    def _handle_ws_message(
        self, session_id: str, token: str, message: dict[str, Any]
    ) -> None:
        message_type = message.get("type")
        request_id = message.get("request_id")
        try:
            if message_type == "candidate_reply":
                result = self.server.store.submit_candidate_reply(
                    session_id, token, message.get("payload") or {}
                )
            elif message_type == "control":
                result = self.server.store.add_control(
                    session_id,
                    token,
                    (message.get("payload") or {}).get("control", ""),
                    (message.get("payload") or {}).get("control_id") or request_id,
                )
            elif message_type == "ping":
                result = {"pong": True}
            else:
                raise BridgeError("invalid_web_message", "网页消息类型无效。")
            self._ws_send_json({"type": "ack", "request_id": request_id, "result": result})
        except BridgeError as exc:
            self._ws_send_json({"type": "error", "request_id": request_id, "error": exc.as_dict()})

    def _ws_read_frame(self) -> tuple[int, bytes] | None:
        header = read_exact(self.connection, 2)
        if not header:
            return None
        first_byte, second_byte = header
        opcode = first_byte & 0x0F
        masked = bool(second_byte & 0x80)
        length = second_byte & 0x7F
        if length == 126:
            length = struct.unpack("!H", read_exact(self.connection, 2))[0]
        elif length == 127:
            length = struct.unpack("!Q", read_exact(self.connection, 8))[0]
        if length > MAX_BODY_BYTES:
            raise OSError("WebSocket frame too large")
        mask = read_exact(self.connection, 4) if masked else b""
        payload = read_exact(self.connection, length)
        if masked:
            payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        return opcode, payload

    def _ws_send_json(self, payload: dict[str, Any]) -> None:
        payload.setdefault("schema_version", PROTOCOL_VERSION)
        payload.setdefault("message_id", uuid.uuid4().hex)
        self._ws_send_frame(0x1, json.dumps(payload, ensure_ascii=False).encode("utf-8"))

    def _ws_send_frame(self, opcode: int, payload: bytes) -> None:
        length = len(payload)
        header = bytes([0x80 | opcode])
        if length < 126:
            header += bytes([length])
        elif length < 65536:
            header += bytes([126]) + struct.pack("!H", length)
        else:
            header += bytes([127]) + struct.pack("!Q", length)
        self.connection.sendall(header + payload)


def read_exact(connection: socket.socket, size: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < size:
        chunk = connection.recv(size - len(chunks))
        if not chunk:
            if not chunks:
                return b""
            raise ConnectionResetError("Connection closed mid-frame")
        chunks.extend(chunk)
    return bytes(chunks)


def first(query: dict[str, list[str]], key: str) -> str | None:
    values = query.get(key)
    return values[0] if values else None


def secrets_equal(left: str, right: str) -> bool:
    import hmac

    return hmac.compare_digest(left.encode(), right.encode())


def run_server(port: int, admin_token: str) -> None:
    server = VoiceBridgeServer(("127.0.0.1", port), admin_token)
    server.serve_forever(poll_interval=0.25)


def main() -> None:
    parser = argparse.ArgumentParser(description="Mock-Interview local voice bridge")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--admin-token", required=True)
    args = parser.parse_args()
    run_server(args.port, args.admin_token)


if __name__ == "__main__":
    main()
