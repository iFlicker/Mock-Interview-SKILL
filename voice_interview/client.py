from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class ClientError(RuntimeError):
    pass


def http_json(
    url: str,
    payload: dict[str, Any] | None = None,
    token: str | None = None,
    timeout: float = 30,
) -> dict[str, Any]:
    headers = {"Accept": "application/json"}
    body = None
    method = "GET"
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
        method = "POST"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(url, data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            data = response.read()
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise ClientError(f"服务请求失败（{exc.code}）：{detail}") from exc
    except URLError as exc:
        raise ClientError("无法连接本地面试服务。") from exc
    return json.loads(data) if data else {}


def call_mcp(
    base_url: str,
    admin_token: str,
    tool_name: str,
    arguments: dict[str, Any],
    request_id: str = "voice-interview-cli",
) -> dict[str, Any]:
    response = http_json(
        f"{base_url.rstrip('/')}/mcp",
        {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        },
        token=admin_token,
        timeout=30,
    )
    if "error" in response:
        raise ClientError(response["error"].get("message", "MCP 工具调用失败。"))
    result = response.get("result", {})
    if result.get("isError"):
        raise ClientError("MCP 工具调用失败。")
    return result.get("structuredContent") or {}
