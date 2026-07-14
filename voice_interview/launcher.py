from __future__ import annotations

import json
import os
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import webbrowser
from pathlib import Path
from typing import Any, Callable

from voice_interview.client import ClientError, call_mcp, http_json
from voice_interview.host_adapter import (
    build_host_plan,
    cleanup_host_connection,
    is_remote_environment,
    prepare_host_connection,
)


ROOT = Path(__file__).resolve().parents[1]
_PROCESSES: dict[int, subprocess.Popen[bytes]] = {}
WAIT_LEASE_DIR = ".wait-owner"
WAIT_LEASE_GRACE_SECONDS = 5.0


class WaitAlreadyActive(RuntimeError):
    def __init__(self, question_id: str | None):
        super().__init__("当前网页会话已经有一个等待进程。")
        self.question_id = question_id

    def as_result(self) -> dict[str, Any]:
        return {
            "status": "already_waiting",
            "action": "resume_existing_wait",
            "question_id": self.question_id,
        }


def _process_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _read_wait_owner(lease_dir: Path) -> dict[str, Any] | None:
    try:
        value = json.loads((lease_dir / "owner.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _acquire_wait_lease(path: str | Path, question_id: str | None) -> dict[str, Any]:
    lease_dir = Path(path).parent / WAIT_LEASE_DIR
    for _attempt in range(3):
        try:
            lease_dir.mkdir(mode=0o700)
        except FileExistsError:
            owner = _read_wait_owner(lease_dir)
            try:
                owner_pid = int((owner or {}).get("pid", 0))
            except (TypeError, ValueError):
                owner_pid = 0
            if owner and _process_is_alive(owner_pid):
                raise WaitAlreadyActive(owner.get("question_id"))
            try:
                age = time.time() - lease_dir.stat().st_mtime
            except OSError:
                continue
            if owner is None and age < WAIT_LEASE_GRACE_SECONDS:
                raise WaitAlreadyActive(None)
            shutil.rmtree(lease_dir, ignore_errors=True)
            continue
        token = secrets.token_urlsafe(18)
        owner = {
            "token": token,
            "pid": os.getpid(),
            "question_id": question_id,
            "created_at": time.time(),
        }
        owner_file = lease_dir / "owner.json"
        try:
            owner_file.write_text(json.dumps(owner), encoding="utf-8")
            owner_file.chmod(0o600)
        except OSError:
            shutil.rmtree(lease_dir, ignore_errors=True)
            raise
        return {"lease_dir": lease_dir, **owner}
    raise RuntimeError("无法取得网页回答等待租约。")


def _release_wait_lease(lease: dict[str, Any]) -> None:
    lease_dir = Path(lease["lease_dir"])
    owner = _read_wait_owner(lease_dir)
    if owner and secrets.compare_digest(
        str(owner.get("token", "")), str(lease.get("token", ""))
    ):
        shutil.rmtree(lease_dir, ignore_errors=True)


def find_available_port(preferred: int | None = None) -> int:
    candidates = [preferred] if preferred else []
    candidates.append(0)
    for candidate in candidates:
        if candidate is None:
            continue
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.bind(("127.0.0.1", candidate))
            return int(sock.getsockname()[1])
        except OSError:
            continue
        finally:
            sock.close()
    raise RuntimeError("没有可用的本地端口。")


def _spawn_server(
    port: int, admin_token: str, startup_log: Path | None = None
) -> subprocess.Popen[bytes]:
    command = [
        sys.executable,
        "-m",
        "voice_interview.server",
        "--port",
        str(port),
        "--admin-token",
        admin_token,
    ]
    error_stream = None
    if startup_log is not None:
        error_stream = startup_log.open("ab", buffering=0)
        try:
            startup_log.chmod(0o600)
        except OSError:
            pass
    kwargs: dict[str, Any] = {
        "cwd": str(ROOT),
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": error_stream or subprocess.DEVNULL,
    }
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    else:
        kwargs["start_new_session"] = True
    try:
        return subprocess.Popen(command, **kwargs)
    finally:
        if error_stream is not None:
            error_stream.close()


def _startup_diagnostic(path: Path, admin_token: str) -> dict[str, str]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")[-8_000:]
    except OSError:
        text = ""
    text = text.replace(admin_token, "<redacted>").strip()
    lowered = text.lower()
    if "address already in use" in lowered:
        category = "port_conflict"
    elif "no module named" in lowered or "modulenotfounderror" in lowered:
        category = "module_import_failed"
    elif "permissionerror" in lowered or "permission denied" in lowered:
        category = "permission_denied"
    elif "syntaxerror" in lowered:
        category = "runtime_incompatible"
    elif text:
        category = "server_process_exited"
    else:
        category = "server_process_exited_without_stderr"
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    summary = lines[-1][:500] if lines else "服务子进程在健康检查前退出，且没有产生错误输出。"
    return {"category": category, "summary": summary}


def _wait_ready(base_url: str, process: subprocess.Popen[bytes], timeout: float = 8) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("本地面试服务启动失败。")
        try:
            if http_json(f"{base_url}/health", timeout=0.4).get("status") == "ok":
                return
        except (ClientError, OSError, TimeoutError):
            time.sleep(0.08)
    raise RuntimeError("本地面试服务启动超时。")


def _terminate_child(process: subprocess.Popen[bytes]) -> None:
    terminate_process(process.pid)
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=2)


def start_voice_interview(
    config_summary: dict[str, Any],
    interviewer: dict[str, Any],
    language: str,
    tts: dict[str, Any] | None = None,
    preferred_port: int | None = None,
    open_browser: bool = False,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    effective_env = dict(os.environ if env is None else env)
    project_dir = Path.cwd()
    if is_remote_environment(effective_env):
        return {
            "ok": False,
            "reason": "remote_environment",
            "message": "当前环境无法让你的浏览器访问本机语音面试室，可以立即切换为文字面试。",
            "fallback": "agent_text",
        }
    plan = build_host_plan(effective_env)
    runtime_dir = Path(tempfile.mkdtemp(prefix="mock-interview-voice-"))
    try:
        runtime_dir.chmod(0o700)
    except OSError:
        pass
    admin_token = secrets.token_urlsafe(36)
    process: subprocess.Popen[bytes] | None = None
    base_url = ""
    last_error: Exception | None = None
    last_diagnostic: dict[str, str] | None = None
    startup_attempts = 0
    for attempt in range(5):
        startup_attempts = attempt + 1
        startup_log = runtime_dir / f"startup-attempt-{startup_attempts}.log"
        try:
            port = find_available_port(preferred_port)
            process = _spawn_server(port, admin_token, startup_log)
        except (OSError, RuntimeError) as exc:
            last_error = exc
            last_diagnostic = {
                "category": "server_spawn_failed",
                "summary": str(exc)[:500],
            }
            preferred_port = None
            if attempt < 4:
                time.sleep(min(0.2 * (2**attempt), 1.6))
            continue
        preferred_port = None
        base_url = f"http://127.0.0.1:{port}"
        try:
            _wait_ready(base_url, process)
            break
        except RuntimeError as exc:
            last_error = exc
            last_diagnostic = _startup_diagnostic(startup_log, admin_token)
            _terminate_child(process)
            process = None
            if attempt < 4:
                time.sleep(min(0.2 * (2**attempt), 1.6))
    for startup_log in runtime_dir.glob("startup-attempt-*.log"):
        try:
            startup_log.unlink()
        except OSError:
            pass
    if process is None:
        shutil.rmtree(runtime_dir, ignore_errors=True)
        return {
            "ok": False,
            "reason": "service_start_failed",
            "message": "语音面试室暂时无法启动，可以立即切换为文字面试。",
            "detail": str(last_error or "unknown"),
            "diagnostic": last_diagnostic,
            "startup_attempts": startup_attempts,
            "fallback": "agent_text",
        }
    try:
        session = call_mcp(
            base_url,
            admin_token,
            "create_interview_session",
            {
                "config_summary": config_summary,
                "interviewer": interviewer,
                "language": language,
                "tts": tts or {"rate": 1.0},
            },
        )
    except Exception as exc:
        _terminate_child(process)
        shutil.rmtree(runtime_dir, ignore_errors=True)
        return {
            "ok": False,
            "reason": "session_create_failed",
            "message": "语音面试会话暂时无法创建，可以立即切换为文字面试。",
            "detail": str(exc),
            "fallback": "agent_text",
        }
    runtime_file = runtime_dir / "runtime.json"
    host_connection = prepare_host_connection(
        plan,
        base_url,
        admin_token,
        f"mock-interview-voice-{session['session_id'][:8]}",
        project_dir,
    )
    runtime = {
        "base_url": base_url,
        "admin_token": admin_token,
        "pid": process.pid,
        "session_id": session["session_id"],
        "room_url": session["room_url"],
        "host": plan.host,
        "mode": host_connection["mode"],
        "registration": host_connection["registration"],
        "registered": host_connection["registered"],
        "limitation": host_connection["limitation"],
        "cleanup_command": host_connection["cleanup_command"],
        "project_dir": str(project_dir),
    }
    try:
        runtime_file.write_text(
            json.dumps(runtime, ensure_ascii=False), encoding="utf-8"
        )
    except OSError as exc:
        cleanup_host_connection(
            host_connection.get("cleanup_command"), project_dir
        )
        _terminate_child(process)
        shutil.rmtree(runtime_dir, ignore_errors=True)
        return {
            "ok": False,
            "reason": "runtime_state_failed",
            "message": "语音面试室暂时无法完成准备，可以立即切换为文字面试。",
            "detail": str(exc),
            "fallback": "agent_text",
        }
    try:
        runtime_file.chmod(0o600)
    except OSError:
        pass
    _PROCESSES[process.pid] = process
    opened = False
    if open_browser:
        try:
            opened = bool(webbrowser.open(session["room_url"], new=2))
        except (webbrowser.Error, OSError):
            opened = False
    return {
        "ok": True,
        **session,
        "runtime_file": str(runtime_file),
        "browser_open_attempted": open_browser,
        "browser_opened": opened,
        "startup_attempts": startup_attempts,
        "host_adapter": {key: value for key, value in host_connection.items() if key != "cleanup_command"},
    }


def open_runtime_room(path: str | Path) -> dict[str, Any]:
    runtime = read_runtime(path)
    try:
        opened = bool(webbrowser.open(runtime["room_url"], new=2))
    except (webbrowser.Error, OSError):
        opened = False
    return {
        "ok": opened,
        "browser_open_attempted": True,
        "browser_opened": opened,
    }


def read_runtime(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def call_runtime_tool(path: str | Path, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
    runtime = read_runtime(path)
    return call_mcp(runtime["base_url"], runtime["admin_token"], tool, arguments)


def wait_for_runtime_event(
    path: str | Path,
    question_id: str | None = None,
    cursor: int = 0,
    timeout_ms: int = 20_000,
    on_heartbeat: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Keep the caller alive while using bounded MCP waits under the hood."""
    if cursor < 0:
        raise ValueError("事件 cursor 不能小于 0。")
    if not 1_000 <= timeout_ms <= 25_000:
        raise ValueError("单次等待必须在 1000 到 25000 毫秒之间。")
    lease = _acquire_wait_lease(path, question_id)
    try:
        current_cursor = cursor
        while True:
            arguments: dict[str, Any] = {
                "session_id": read_runtime(path)["session_id"],
                "cursor": current_cursor,
                "timeout_ms": timeout_ms,
            }
            if question_id:
                arguments["question_id"] = question_id
            result = call_runtime_tool(path, "wait_for_candidate_reply", arguments)
            current_cursor = int(result.get("next_cursor", current_cursor))
            if result.get("status") != "timeout":
                return result
            if on_heartbeat:
                on_heartbeat({"status": "waiting", "next_cursor": current_cursor})
    finally:
        _release_wait_lease(lease)


def stop_runtime(path: str | Path) -> dict[str, Any]:
    runtime_path = Path(path)
    runtime = read_runtime(runtime_path)
    closed: dict[str, Any]
    try:
        closed = call_mcp(
            runtime["base_url"],
            runtime["admin_token"],
            "close_interview_session",
            {"session_id": runtime["session_id"]},
        )
    except ClientError:
        closed = {"closed": False, "service_unreachable": True}
    if closed.get("closed"):
        time.sleep(0.6)
    cleanup_host_connection(runtime.get("cleanup_command"), runtime.get("project_dir") or ROOT)
    terminate_process(int(runtime["pid"]))
    process = _PROCESSES.pop(int(runtime["pid"]), None)
    if process is not None:
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)
    shutil.rmtree(runtime_path.parent, ignore_errors=True)
    return closed


def terminate_process(pid: int) -> None:
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        else:
            os.killpg(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        pass
