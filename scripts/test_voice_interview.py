import json
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock
from urllib.error import HTTPError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from voice_interview.host_adapter import (
    build_host_plan,
    detect_host,
    is_remote_environment,
    prepare_host_connection,
)
from voice_interview.client import http_json
from voice_interview.launcher import (
    WaitAlreadyActive,
    _acquire_wait_lease,
    _release_wait_lease,
    _spawn_server,
    call_runtime_tool,
    open_runtime_room,
    read_runtime,
    start_voice_interview,
    stop_runtime,
    wait_for_runtime_event,
)
from voice_interview.mcp import MCPApplication, TOOLS
from voice_interview.server import VoiceBridgeServer
from voice_interview.store import BridgeError, SessionStore


class VoiceBridgeContractTest(unittest.TestCase):
    def setUp(self):
        self.store = SessionStore("http://127.0.0.1:34567")
        self.created = self.store.create_session(
            {"target_position": "产品经理", "interaction_channel": "web_voice"},
            {"name": "陈老师", "role": "产品负责人"},
            "zh-CN",
            {"rate": 1.0},
        )
        self.session_id = self.created["session_id"]
        self.token = self.created["session_token"]

    def message_args(self, message_id="q-1", text="请做一个简短的自我介绍。"):
        return {
            "session_id": self.session_id,
            "message_id": message_id,
            "message_type": "interviewer_question",
            "display_text": text,
            "speech_text": text,
            "auto_speak": True,
            "language": "zh-CN",
            "timestamp": "2026-07-14T10:00:00+08:00",
        }

    def test_mcp_tool_input_output_contract(self):
        self.assertEqual(
            {tool["name"] for tool in TOOLS},
            {
                "create_interview_session",
                "send_interviewer_message",
                "wait_for_candidate_reply",
                "get_session_events",
                "close_interview_session",
            },
        )
        for tool in TOOLS:
            self.assertEqual(tool["inputSchema"]["type"], "object")
            self.assertIn("properties", tool["inputSchema"])
        app = MCPApplication(self.store)
        response = app.handle_jsonrpc({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        self.assertEqual(len(response["result"]["tools"]), 5)
        self.assertIn("serverInfo", app.handle_jsonrpc({
            "jsonrpc": "2.0", "id": 2, "method": "initialize", "params": {}
        })["result"])

    def test_session_token_is_unpredictable_and_required(self):
        second = self.store.create_session({}, {"name": "A", "role": "B"}, "en-US")
        self.assertNotEqual(self.token, second["session_token"])
        self.assertGreaterEqual(len(self.token), 32)
        with self.assertRaisesRegex(BridgeError, "链接无效"):
            self.store.snapshot(self.session_id, "wrong-token")
        snapshot = self.store.snapshot(self.session_id, self.token)
        self.assertEqual(snapshot["session_id"], self.session_id)

    def test_duplicate_message_id_is_idempotent_and_conflicts_are_rejected(self):
        first = self.store.send_interviewer_message(self.message_args())
        duplicate = self.store.send_interviewer_message(self.message_args())
        self.assertFalse(first["duplicate"])
        self.assertTrue(duplicate["duplicate"])
        self.assertEqual(len(self.store.get(self.session_id).messages), 1)
        with self.assertRaisesRegex(BridgeError, "不能对应不同内容"):
            self.store.send_interviewer_message(self.message_args(text="不同的问题"))

    def test_duplicate_reply_is_idempotent_and_only_one_reply_per_question(self):
        self.store.send_interviewer_message(self.message_args())
        payload = {
            "reply_id": "reply-1",
            "question_id": "q-1",
            "text": "这是我确认后的回答。",
            "source": "mixed",
        }
        first = self.store.submit_candidate_reply(self.session_id, self.token, payload)
        duplicate = self.store.submit_candidate_reply(self.session_id, self.token, payload)
        second_click = self.store.submit_candidate_reply(
            self.session_id,
            self.token,
            {**payload, "reply_id": "reply-2"},
        )
        self.assertFalse(first["duplicate"])
        self.assertTrue(duplicate["duplicate"])
        self.assertTrue(second_click["duplicate"])
        self.assertEqual(len(self.store.get(self.session_id).replies), 1)

    def test_event_sequence_cursor_and_wait_timeout(self):
        initial = self.store.get_events(self.session_id, 0)
        self.assertEqual([event["sequence"] for event in initial["events"]], [1])
        self.store.send_interviewer_message(self.message_args())
        later = self.store.get_events(self.session_id, 1)
        self.assertEqual([event["sequence"] for event in later["events"]], [2])
        waited = self.store.wait_for_candidate_reply({
            "session_id": self.session_id, "cursor": later["next_cursor"], "timeout_ms": 1
        })
        self.assertEqual(waited["status"], "timeout")
        self.assertEqual(waited["next_cursor"], 2)
        self.assertEqual(self.store.get(self.session_id).status, "ready")

    def test_agent_presence_expires_and_is_refreshed_by_mcp_polling(self):
        session = self.store.get(self.session_id)
        session.agent_last_seen -= 60
        self.assertFalse(self.store.snapshot(self.session_id, self.token)["agent_connected"])
        MCPApplication(self.store).call_tool(
            "get_session_events", {"session_id": self.session_id, "cursor": 0}
        )
        self.assertTrue(self.store.snapshot(self.session_id, self.token)["agent_connected"])

    def test_wait_cursor_does_not_skip_events_after_a_reply(self):
        self.store.send_interviewer_message(self.message_args())
        self.store.submit_candidate_reply(
            self.session_id,
            self.token,
            {"reply_id": "r-1", "question_id": "q-1", "text": "回答", "source": "keyboard"},
        )
        self.store.add_control(self.session_id, self.token, "pause")
        waited = self.store.wait_for_candidate_reply({
            "session_id": self.session_id, "cursor": 2, "timeout_ms": 0
        })
        self.assertEqual(waited["status"], "reply")
        self.assertEqual(waited["next_cursor"], 3)
        remaining = self.store.get_events(self.session_id, waited["next_cursor"])
        self.assertEqual(remaining["events"][0]["type"], "interview_paused")

    def test_waiting_again_for_an_answered_question_returns_the_original_reply(self):
        self.store.send_interviewer_message(self.message_args())
        submitted = self.store.submit_candidate_reply(
            self.session_id,
            self.token,
            {"reply_id": "r-existing", "question_id": "q-1", "text": "已提交", "source": "keyboard"},
        )
        waited = self.store.wait_for_candidate_reply({
            "session_id": self.session_id,
            "question_id": "q-1",
            "cursor": submitted["sequence"] + 5,
            "timeout_ms": 1,
        })
        self.assertEqual(waited["status"], "reply")
        self.assertTrue(waited["duplicate"])
        self.assertEqual(waited["reply"]["reply_id"], "r-existing")

    def test_wait_rejects_a_non_question_message_id(self):
        self.store.send_interviewer_message({
            **self.message_args("notice-1", "请稍候。"),
            "message_type": "interviewer_message",
        })
        with self.assertRaisesRegex(BridgeError, "interviewer_question"):
            self.store.wait_for_candidate_reply({
                "session_id": self.session_id,
                "question_id": "notice-1",
                "cursor": 0,
                "timeout_ms": 1,
            })

    def test_disconnect_reconnect_and_refresh_restore_without_duplicate_messages(self):
        self.store.send_interviewer_message(self.message_args())
        self.store.web_connected(self.session_id, self.token, False)
        self.store.web_disconnected(self.session_id)
        self.store.web_connected(self.session_id, self.token, True)
        event_types = [event["type"] for event in self.store.get_events(self.session_id, 0)["events"]]
        self.assertIn("web_connected", event_types)
        self.assertIn("web_disconnected", event_types)
        self.assertIn("web_reconnected", event_types)
        first_snapshot = self.store.snapshot(self.session_id, self.token)
        second_snapshot = self.store.snapshot(self.session_id, self.token)
        self.assertEqual(first_snapshot["timeline"], second_snapshot["timeline"])
        self.assertEqual(len(first_snapshot["timeline"]), 1)

    def test_close_rejects_new_messages_and_replies(self):
        self.store.send_interviewer_message(self.message_args())
        self.store.close_session({"session_id": self.session_id})
        with self.assertRaisesRegex(BridgeError, "已经结束"):
            self.store.send_interviewer_message(self.message_args("q-2", "新问题"))
        with self.assertRaisesRegex(BridgeError, "已经结束"):
            self.store.submit_candidate_reply(
                self.session_id,
                self.token,
                {"reply_id": "r-1", "question_id": "q-1", "text": "迟到的回答", "source": "keyboard"},
            )

    def test_end_control_allows_only_the_idempotent_end_boundary(self):
        self.store.send_interviewer_message(self.message_args())
        self.store.add_control(self.session_id, self.token, "end")
        end_boundary = self.store.send_interviewer_message({
            "session_id": self.session_id,
            "message_id": "boundary-end",
            "message_type": "interview_end",
            "display_text": "面试结束",
            "auto_speak": False,
        })
        self.assertTrue(end_boundary["accepted"])
        self.assertEqual(end_boundary["message"]["display_text"], "面试结束")
        self.assertFalse(end_boundary["message"]["auto_speak"])
        with self.assertRaises(BridgeError):
            self.store.send_interviewer_message(self.message_args("q-2", "不能再问"))

    def test_duplicate_control_id_is_idempotent(self):
        first = self.store.add_control(
            self.session_id, self.token, "skip", "control-1"
        )
        duplicate = self.store.add_control(
            self.session_id, self.token, "skip", "control-1"
        )
        self.assertFalse(first["duplicate"])
        self.assertTrue(duplicate["duplicate"])
        events = self.store.get_events(self.session_id, 0)["events"]
        self.assertEqual(
            [event["type"] for event in events].count("question_skipped"), 1
        )

    def test_voice_to_text_transition_preserves_history(self):
        self.store.send_interviewer_message(self.message_args())
        before = self.store.snapshot(self.session_id, self.token)["timeline"]
        switched = self.store.add_control(self.session_id, self.token, "switch_to_text")
        after = self.store.snapshot(self.session_id, self.token)
        self.assertEqual(switched["status"], "switched_to_text")
        self.assertEqual(after["interaction_channel"], "agent_text")
        self.assertEqual(after["timeline"], before)
        event_types = [event["type"] for event in self.store.get_events(self.session_id, 0)["events"]]
        self.assertEqual(event_types.count("switch_to_text"), 1)
        closed = self.store.close_session({"session_id": self.session_id})
        self.assertEqual(closed["status"], "switched_to_text")
        event_types = [event["type"] for event in self.store.get_events(self.session_id, 0)["events"]]
        self.assertNotIn("interview_ended", event_types)

    def test_web_activity_feedback_is_ephemeral_and_accessible(self):
        app_source = (ROOT / "voice_interview" / "web" / "app.js").read_text(encoding="utf-8")
        style_source = (ROOT / "voice_interview" / "web" / "styles.css").read_text(encoding="utf-8")
        self.assertIn('setActivity("opening", "已连接，面试官正在准备。...")', app_source)
        self.assertIn('setActivity("thinking", "思考中...")', app_source)
        self.assertIn('delivery.textContent = "已发送"', app_source)
        self.assertIn('label.textContent = "发送中"', app_source)
        self.assertIn('wrapper.setAttribute("role", "status")', app_source)
        self.assertIn('wrapper.setAttribute("aria-live", "polite")', app_source)
        self.assertIn("@keyframes spin", style_source)
        self.assertNotIn('systemMessage("思考中...")', app_source)


class HostAndDeploymentTest(unittest.TestCase):
    def test_persistent_wait_retries_timeouts_until_real_event(self):
        heartbeats = []
        responses = [
            {"status": "timeout", "next_cursor": 4},
            {"status": "timeout", "next_cursor": 6},
            {"status": "reply", "next_cursor": 7, "reply": {"reply_id": "r-1"}},
        ]
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch(
                "voice_interview.launcher.read_runtime",
                return_value={"session_id": "session-1"},
            ), mock.patch(
                "voice_interview.launcher.call_runtime_tool", side_effect=responses
            ) as call:
                result = wait_for_runtime_event(
                    Path(directory) / "runtime.json",
                    question_id="q-1",
                    cursor=2,
                    timeout_ms=1_000,
                    on_heartbeat=heartbeats.append,
                )
        self.assertEqual(result["status"], "reply")
        self.assertEqual([item["next_cursor"] for item in heartbeats], [4, 6])
        self.assertEqual(
            [item.args[2]["cursor"] for item in call.call_args_list], [2, 4, 6]
        )

    def test_only_one_wait_lease_can_be_active_per_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = Path(directory) / "runtime.json"
            first = _acquire_wait_lease(runtime, "q-1")
            try:
                with self.assertRaises(WaitAlreadyActive) as duplicate:
                    _acquire_wait_lease(runtime, "q-1")
                self.assertEqual(duplicate.exception.question_id, "q-1")
            finally:
                _release_wait_lease(first)
            second = _acquire_wait_lease(runtime, "q-2")
            _release_wait_lease(second)

    def test_stale_wait_lease_is_recovered(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = Path(directory) / "runtime.json"
            lease_dir = Path(directory) / ".wait-owner"
            lease_dir.mkdir()
            (lease_dir / "owner.json").write_text(
                json.dumps({"token": "stale", "pid": 99_999_999, "question_id": "old"}),
                encoding="utf-8",
            )
            lease = _acquire_wait_lease(runtime, "q-new")
            try:
                self.assertEqual(lease["question_id"], "q-new")
            finally:
                _release_wait_lease(lease)

    def test_cli_rejects_a_concurrent_wait_process(self):
        started = start_voice_interview(
            {"target_position": "回归测试"},
            {"name": "陈老师", "role": "测试面试官"},
            "zh-CN",
            open_browser=False,
            env={"MOCK_INTERVIEW_FORCE_LOCAL": "1", "MOCK_INTERVIEW_HOST": "codex"},
        )
        self.assertTrue(started["ok"])
        runtime_path = Path(started["runtime_file"])
        session_id = started["session_id"]
        call_runtime_tool(
            runtime_path,
            "send_interviewer_message",
            {
                "session_id": session_id,
                "message_id": "q-concurrent",
                "message_type": "interviewer_question",
                "display_text": "请回答并发等待回归问题。",
            },
        )
        command = [
            sys.executable,
            str(ROOT / "scripts" / "voice_interview.py"),
            "wait",
            "--runtime",
            str(runtime_path),
            "--question-id",
            "q-concurrent",
            "--timeout-ms",
            "1000",
        ]
        first = subprocess.Popen(
            command,
            cwd=str(ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            deadline = time.monotonic() + 3
            while not (runtime_path.parent / ".wait-owner" / "owner.json").is_file():
                if time.monotonic() >= deadline:
                    self.fail("first wait process did not acquire its lease")
                time.sleep(0.02)
            second = subprocess.run(
                command,
                cwd=str(ROOT),
                capture_output=True,
                text=True,
                timeout=5,
                check=True,
            )
            duplicate = json.loads(second.stdout.strip().splitlines()[-1])
            self.assertEqual(duplicate["status"], "already_waiting")
            self.assertEqual(duplicate["action"], "resume_existing_wait")

            runtime = read_runtime(runtime_path)
            http_json(
                f"{runtime['base_url']}/api/session/{session_id}/control?token={started['session_token']}",
                {"control": "end", "control_id": "end-concurrent-test"},
            )
            stdout, stderr = first.communicate(timeout=5)
            self.assertEqual(first.returncode, 0, stderr)
            finished = json.loads(stdout.strip().splitlines()[-1])
            self.assertEqual(finished["status"], "control")
            self.assertEqual(finished["control"], "end")
        finally:
            if first.poll() is None:
                first.kill()
                first.wait(timeout=2)
            if runtime_path.exists():
                stop_runtime(runtime_path)

    def test_detects_supported_hosts(self):
        cases = {
            "codex": {"CODEX_HOME": "/tmp/codex"},
            "claude_code": {"CLAUDE_CODE": "1"},
            "cursor": {"CURSOR_TRACE_ID": "trace"},
            "opencode": {"OPENCODE": "1"},
            "other": {},
        }
        for expected, env in cases.items():
            with self.subTest(expected=expected):
                self.assertEqual(detect_host(env), expected)
        self.assertFalse(build_host_plan({"CODEX_HOME": "/tmp/codex"}).can_hot_register)

    def test_remote_environment_prevents_local_service_start(self):
        with mock.patch("voice_interview.launcher._spawn_server") as spawn:
            result = start_voice_interview(
                {}, {"name": "陈老师", "role": "经理"}, "zh-CN",
                open_browser=False,
                env={"MOCK_INTERVIEW_FORCE_REMOTE": "1"},
            )
        self.assertFalse(result["ok"])
        self.assertEqual(result["fallback"], "agent_text")
        spawn.assert_not_called()
        self.assertTrue(is_remote_environment({"SSH_CONNECTION": "example"}))

    def test_local_service_start_failure_returns_text_fallback(self):
        with mock.patch(
            "voice_interview.launcher._spawn_server",
            side_effect=OSError("blocked"),
        ), mock.patch("voice_interview.launcher.time.sleep"):
            result = start_voice_interview(
                {},
                {"name": "陈老师", "role": "经理"},
                "zh-CN",
                open_browser=False,
                env={"MOCK_INTERVIEW_FORCE_LOCAL": "1"},
            )
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "service_start_failed")
        self.assertEqual(result["fallback"], "agent_text")
        self.assertEqual(result["startup_attempts"], 5)
        self.assertEqual(result["diagnostic"]["category"], "server_spawn_failed")

    def test_first_spawn_failure_recovers_inside_the_same_start_request(self):
        calls = 0

        def flaky_spawn(port, admin_token, startup_log):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise OSError("transient spawn failure")
            return _spawn_server(port, admin_token, startup_log)

        result = None
        with mock.patch(
            "voice_interview.launcher._spawn_server", side_effect=flaky_spawn
        ), mock.patch("voice_interview.launcher.time.sleep"):
            result = start_voice_interview(
                {"target_position": "产品经理"},
                {"name": "陈老师", "role": "产品负责人"},
                "zh-CN",
                open_browser=False,
                env={"MOCK_INTERVIEW_FORCE_LOCAL": "1", "MOCK_INTERVIEW_HOST": "codex"},
            )
        try:
            self.assertTrue(result["ok"])
            self.assertEqual(result["startup_attempts"], 2)
            runtime_dir = Path(result["runtime_file"]).parent
            self.assertEqual(list(runtime_dir.glob("startup-attempt-*.log")), [])
        finally:
            if result and result.get("runtime_file"):
                stop_runtime(result["runtime_file"])

    def test_claude_code_registration_is_automatic_and_has_cleanup(self):
        completed = mock.Mock(returncode=0)
        with mock.patch("voice_interview.host_adapter.shutil.which", return_value="/usr/bin/claude"), mock.patch(
            "voice_interview.host_adapter.subprocess.run", return_value=completed
        ) as run:
            plan = build_host_plan({"MOCK_INTERVIEW_HOST": "claude_code"}, system="Linux")
            result = prepare_host_connection(
                plan,
                "http://127.0.0.1:32100",
                "agent-secret",
                "mock-interview-voice-test",
                ROOT,
            )
        self.assertTrue(result["registered"])
        self.assertEqual(result["mode"], "mcp_http_with_cli_fallback")
        command = run.call_args.args[0]
        self.assertIn("mcp", command)
        self.assertIn("add", command)
        self.assertIn("--scope", command)
        self.assertEqual(result["cleanup_command"][-3:], ["mock-interview-voice-test", "--scope", "local"])

    def test_auto_deployment_and_port_conflict_recovery(self):
        occupied = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        occupied.bind(("127.0.0.1", 0))
        occupied.listen(1)
        port = occupied.getsockname()[1]
        result = None
        try:
            result = start_voice_interview(
                {"target_position": "产品经理"},
                {"name": "陈老师", "role": "产品负责人"},
                "zh-CN",
                preferred_port=port,
                open_browser=False,
                env={"MOCK_INTERVIEW_FORCE_LOCAL": "1", "MOCK_INTERVIEW_HOST": "codex"},
            )
            self.assertTrue(result["ok"])
            self.assertNotIn(f":{port}/", result["room_url"])
            self.assertEqual(result["host_adapter"]["host"], "codex")
            self.assertTrue(Path(result["runtime_file"]).is_file())
        finally:
            occupied.close()
            if result and result.get("runtime_file"):
                stop_runtime(result["runtime_file"])

    def test_room_is_opened_only_after_start_returns(self):
        result = None
        with mock.patch("voice_interview.launcher.webbrowser.open", return_value=True) as browser:
            try:
                result = start_voice_interview(
                    {"target_position": "产品经理"},
                    {"name": "陈老师", "role": "产品负责人"},
                    "zh-CN",
                    env={"MOCK_INTERVIEW_FORCE_LOCAL": "1", "MOCK_INTERVIEW_HOST": "codex"},
                )
                self.assertTrue(result["ok"])
                self.assertFalse(result["browser_open_attempted"])
                browser.assert_not_called()

                opened = open_runtime_room(result["runtime_file"])
                self.assertTrue(opened["ok"])
                self.assertTrue(opened["browser_open_attempted"])
                browser.assert_called_once_with(result["room_url"], new=2)
            finally:
                if result and result.get("runtime_file"):
                    stop_runtime(result["runtime_file"])

    def test_frontend_contains_required_progressive_voice_behaviour(self):
        app = (ROOT / "voice_interview" / "web" / "app.js").read_text(encoding="utf-8")
        html = (ROOT / "voice_interview" / "web" / "index.html").read_text(encoding="utf-8")
        for marker in (
            "speechSynthesis", "onboundary", "sentence", "SpeechRecognition",
            "webkitSpeechRecognition", "continuous = true", "interimResults = true",
            "getUserMedia", "Typeless", "微信输入法", "beforeunload", "devicechange",
            "agent_status", "window.confirm", "awaitingNextQuestion",
            "renderBoundary", 'systemMessage(kind === "start" ? "面试开始" : "面试结束")',
        ):
            self.assertIn(marker, app)
        self.assertNotIn('systemMessage("本轮面试已结束，请返回当前应用查看评价")', app)
        self.assertIn("浏览器厂商的在线服务", html)
        self.assertIn("Ctrl/⌘ + Enter", html)


class LiveWebSocketTest(unittest.TestCase):
    def test_http_session_token_and_origin_are_enforced(self):
        server = VoiceBridgeServer(("127.0.0.1", 0), "agent-token")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        created = server.store.create_session({}, {"name": "陈老师", "role": "经理"}, "zh-CN")
        base = f"http://127.0.0.1:{server.server_port}"
        try:
            wrong_token = Request(
                f"{base}/api/session/{created['session_id']}/snapshot?token=wrong",
                headers={"Origin": base},
            )
            with self.assertRaises(HTTPError) as token_error:
                urlopen(wrong_token, timeout=2)
            self.assertEqual(token_error.exception.code, 401)

            wrong_origin = Request(
                f"{base}/api/session/{created['session_id']}/snapshot?token={created['session_token']}",
                headers={"Origin": "https://evil.example"},
            )
            with self.assertRaises(HTTPError) as origin_error:
                urlopen(wrong_origin, timeout=2)
            self.assertEqual(origin_error.exception.code, 403)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_websocket_disconnect_and_reconnect_use_same_session(self):
        server = VoiceBridgeServer(("127.0.0.1", 0), "agent-token")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        created = server.store.create_session({}, {"name": "陈老师", "role": "经理"}, "zh-CN")
        port = server.server_port

        def connect(reconnect):
            connection = socket.create_connection(("127.0.0.1", port), timeout=2)
            request = (
                f"GET /ws?session_id={created['session_id']}&token={created['session_token']}&after=0&reconnect={reconnect} HTTP/1.1\r\n"
                f"Host: 127.0.0.1:{port}\r\n"
                f"Origin: http://127.0.0.1:{port}\r\n"
                "Upgrade: websocket\r\n"
                "Connection: Upgrade\r\n"
                "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n"
                "Sec-WebSocket-Version: 13\r\n\r\n"
            )
            connection.sendall(request.encode("ascii"))
            response = connection.recv(4096)
            self.assertIn(b"101 Switching Protocols", response)
            return connection

        try:
            first = connect(0)
            first.close()
            time.sleep(0.08)
            second = connect(1)
            second.close()
            time.sleep(0.08)
            event_types = [
                event["type"]
                for event in server.store.get_events(created["session_id"], 0)["events"]
            ]
            self.assertIn("web_connected", event_types)
            self.assertIn("web_disconnected", event_types)
            self.assertIn("web_reconnected", event_types)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
