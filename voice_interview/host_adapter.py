from __future__ import annotations

import os
import platform
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


@dataclass(frozen=True)
class HostPlan:
    host: str
    operating_system: str
    mode: str
    registration: str
    can_hot_register: bool
    limitation: str | None


def detect_host(env: Mapping[str, str] | None = None) -> str:
    values = dict(os.environ if env is None else env)
    explicit = values.get("MOCK_INTERVIEW_HOST", "").strip().lower()
    if explicit in {"codex", "claude_code", "cursor", "opencode", "other"}:
        return explicit
    if values.get("CODEX_HOME") or values.get("CODEX_THREAD_ID") or values.get("CODEX_SANDBOX"):
        return "codex"
    if values.get("CLAUDE_CODE") or values.get("CLAUDE_CODE_ENTRYPOINT"):
        return "claude_code"
    if values.get("CURSOR_TRACE_ID") or values.get("CURSOR_AGENT"):
        return "cursor"
    if values.get("OPENCODE") or values.get("OPENCODE_CONFIG"):
        return "opencode"
    return "other"


def is_remote_environment(env: Mapping[str, str] | None = None) -> bool:
    values = dict(os.environ if env is None else env)
    if values.get("MOCK_INTERVIEW_FORCE_LOCAL") == "1":
        return False
    if values.get("MOCK_INTERVIEW_FORCE_REMOTE") == "1":
        return True
    remote_markers = (
        "SSH_CONNECTION",
        "SSH_CLIENT",
        "CODESPACES",
        "GITPOD_WORKSPACE_ID",
        "REMOTE_CONTAINERS",
        "CODEX_CLOUD_TASK_ID",
        "CURSOR_BACKGROUND_AGENT",
    )
    return any(values.get(marker) for marker in remote_markers)


def build_host_plan(
    env: Mapping[str, str] | None = None, system: str | None = None
) -> HostPlan:
    host = detect_host(env)
    os_name = (system or platform.system()).lower()
    if host == "claude_code":
        available = shutil.which("claude") is not None
        return HostPlan(
            host, os_name, "mcp_http_pending" if available else "local_bridge_cli",
            "claude mcp add --scope local", available,
            None if available else "Claude Code CLI 不可用，当前会话使用同一服务的本地控制通道。",
        )
    if host == "codex":
        return HostPlan(
            host, os_name, "local_bridge_cli", "shared Codex MCP config", False,
            "Codex 新增 MCP 配置后需要客户端重启，当前任务使用同一 MCP 服务的本地控制通道。",
        )
    if host == "cursor":
        return HostPlan(
            host, os_name, "local_bridge_cli", "Cursor extension API or .cursor/mcp.json", False,
            "只有 Cursor 扩展可以热注册 MCP；普通 Skill 会话使用本地控制通道。",
        )
    if host == "opencode":
        return HostPlan(
            host, os_name, "local_bridge_cli", "opencode.json mcp entry", False,
            "OpenCode 的 mcp add 是交互式配置，当前会话使用本地控制通道。",
        )
    return HostPlan(
        host, os_name, "local_bridge_cli", "host-specific MCP configuration", False,
        "当前宿主没有可验证的热注册接口，使用本地控制通道。",
    )


def prepare_host_connection(
    plan: HostPlan,
    base_url: str,
    admin_token: str,
    registration_name: str,
    project_dir: str | Path,
) -> dict[str, Any]:
    result = {
        "host": plan.host,
        "operating_system": plan.operating_system,
        "mode": plan.mode,
        "registration": plan.registration,
        "can_hot_register": plan.can_hot_register,
        "registered": False,
        "limitation": plan.limitation,
        "cleanup_command": None,
    }
    if plan.host != "claude_code" or not plan.can_hot_register:
        return result
    executable = shutil.which("claude")
    if not executable:
        result["mode"] = "local_bridge_cli"
        result["limitation"] = "Claude Code CLI 不可用，当前会话使用同一服务的本地控制通道。"
        return result
    command = [
        executable,
        "mcp",
        "add",
        "--transport",
        "http",
        "--scope",
        "local",
        registration_name,
        f"{base_url.rstrip('/')}/mcp",
        "--header",
        f"Authorization: Bearer {admin_token}",
    ]
    try:
        completed = subprocess.run(
            command,
            cwd=str(project_dir),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=12,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        completed = None
    if completed and completed.returncode == 0:
        result["mode"] = "mcp_http_with_cli_fallback"
        result["registered"] = True
        result["cleanup_command"] = [
            executable,
            "mcp",
            "remove",
            registration_name,
            "--scope",
            "local",
        ]
        result["limitation"] = "当前 Claude Code 版本仍可能需要刷新工具清单；本地控制通道保持可用。"
    else:
        result["mode"] = "local_bridge_cli"
        result["limitation"] = "Claude Code 未接受临时 MCP 注册，当前会话使用同一服务的本地控制通道。"
    return result


def cleanup_host_connection(
    cleanup_command: list[str] | None, project_dir: str | Path
) -> None:
    if not cleanup_command:
        return
    try:
        subprocess.run(
            cleanup_command,
            cwd=str(project_dir),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return
