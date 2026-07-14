import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CASES_PATH = ROOT / "tests" / "skill-contract-cases.json"
SKILL_PATH = ROOT / "SKILL.md"
POLICY_PATH = ROOT / "references" / "interview-policy.md"
STATE_PATH = ROOT / "references" / "session-state.md"
SCENARIOS_PATH = ROOT / "references" / "behavior-scenarios.md"
ARCHIVE_PATH = ROOT / "references" / "archive-format.md"
MATRIX_PATH = ROOT / "references" / "interview-matrix.md"
RUBRICS_PATH = ROOT / "references" / "scoring-rubrics.md"
GENERATOR_PATH = ROOT / "scripts" / "generate_report.py"
TEMPLATE_PATH = ROOT / "scripts" / "report-template.html"
README_PATH = ROOT / "README.md"

REQUIRED_SCENARIOS = {
    "resume_missing",
    "multiple_resumes",
    "config_missing",
    "skip_main_question",
    "pause_resume",
    "pressure_adjustment",
    "immersive_feedback_boundary",
    "end_without_evidence",
    "combined_interview",
    "director_depth_profile",
    "follow_up_limit",
    "contradiction_triage",
    "report_consent",
    "evidence_gap_selection",
    "soft_minimum_completion",
    "question_quality_gate",
    "opening_closing_state",
    "blueprint_remains_frozen",
    "report_consent_reopened",
    "confirmed_scope_cap",
    "partial_coverage_score",
    "natural_answer_bridge",
    "challenge_move_gradient",
    "finite_interviewer_knowledge",
    "non_technical_role_defaults",
    "interaction_channel_choice",
    "agent_text_no_web",
    "web_voice_connection_gate",
    "web_voice_boundary_display",
    "web_voice_activity_feedback",
    "web_voice_first_start_retry",
    "web_voice_wait_persistence",
    "web_voice_single_waiter",
    "web_voice_rephrase_reply",
    "web_voice_idempotency",
    "web_voice_reconnect",
    "web_voice_switch_text",
    "web_voice_deploy_failure",
}

REQUIRED_COVERAGE = {
    "preflight",
    "configuration",
    "control",
    "state_transition",
    "immersive_feedback",
    "evidence",
    "early_end",
    "scoring",
    "combination",
    "topic_state",
    "follow_up_limit",
    "contradiction",
    "report_authorization",
    "evidence_gap",
    "question_selection",
    "dynamic_depth",
    "role_mapping",
    "soft_minimum",
    "pressure_depth",
    "question_quality",
    "opening_closing",
    "blueprint_freeze",
    "report_reauthorization",
    "scope_cap",
    "partial_coverage",
    "answer_bridge",
    "challenge_gradient",
    "limited_knowledge",
    "interaction_state",
    "domain_generality",
    "interaction_channel",
    "voice_deployment",
    "voice_start_retry",
    "voice_wait_lifecycle",
    "voice_single_waiter",
    "voice_question_contract",
    "voice_idempotency",
    "voice_reconnect",
    "voice_fallback",
}


class SkillContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = json.loads(CASES_PATH.read_text(encoding="utf-8"))

    def test_contract_has_required_scenarios_and_coverage(self):
        self.assertEqual(
            self.contract["schema_version"], "mock-interview-contract/1.4"
        )
        scenarios = self.contract["scenarios"]
        ids = [scenario["id"] for scenario in scenarios]
        self.assertEqual(len(ids), len(set(ids)), "Scenario IDs must be unique.")
        self.assertTrue(REQUIRED_SCENARIOS.issubset(ids))

        coverage = {
            tag for scenario in scenarios for tag in scenario.get("covers", [])
        }
        self.assertTrue(REQUIRED_COVERAGE.issubset(coverage))

    def test_each_scenario_is_a_complete_given_when_then_contract(self):
        required_fields = {
            "id",
            "covers",
            "given",
            "when",
            "expected_public",
            "forbidden_public",
            "expected_state",
        }
        for scenario in self.contract["scenarios"]:
            with self.subTest(scenario=scenario.get("id")):
                self.assertTrue(required_fields.issubset(scenario))
                for field in required_fields - {"id", "given", "when"}:
                    self.assertIsInstance(scenario[field], list)
                    self.assertTrue(scenario[field])
                self.assertTrue(scenario["given"].strip())
                self.assertTrue(scenario["when"].strip())

    def test_human_readable_scenarios_reference_every_case(self):
        scenarios_doc = SCENARIOS_PATH.read_text(encoding="utf-8")
        for scenario_id in REQUIRED_SCENARIOS:
            with self.subTest(scenario=scenario_id):
                self.assertIn(f"`{scenario_id}`", scenarios_doc)

    def test_report_prompt_is_concise_but_still_requires_consent(self):
        skill = SKILL_PATH.read_text(encoding="utf-8")
        readme = README_PATH.read_text(encoding="utf-8")
        prompt = "是否为本轮面试生成面试报告？"
        self.assertIn(prompt, skill)
        self.assertIn(prompt, readme)
        self.assertNotIn("默认不生成", skill)
        self.assertNotIn("默认不生成", readme)
        self.assertIn("除非用户明确同意，否则不得创建或修改任何面试报告", skill)

    def test_skill_routes_runtime_rules_to_single_sources(self):
        skill = SKILL_PATH.read_text(encoding="utf-8")
        for reference in (
            "references/interview-matrix.md",
            "references/interview-policy.md",
            "references/session-state.md",
            "references/scoring-rubrics.md",
            "references/archive-format.md",
        ):
            with self.subTest(reference=reference):
                self.assertIn(reference, skill)

        policy = POLICY_PATH.read_text(encoding="utf-8")
        self.assertIn("## 证据缺口驱动提问", policy)
        self.assertIn("## 承接上一回答", policy)
        self.assertIn("## 挑战动作梯度", policy)
        self.assertIn("## 面试官有限认知", policy)
        self.assertIn("## 问题质量门", policy)
        self.assertIn("## 矛盾分级", policy)

        state = STATE_PATH.read_text(encoding="utf-8")
        self.assertIn('"schema_version": "mock-interview-session/4.2"', state)
        self.assertIn('"main_question_id": "q-1"', state)
        self.assertIn('"follow_up_count": 2', state)
        self.assertIn('"depth_profile": "standard"', state)
        self.assertIn('"target_follow_up_range": {"min": 3, "max": 4}', state)
        self.assertNotIn('"round_count"', state)
        self.assertIn("## 不变量", state)
        self.assertIn("interviewing <-> paused", state)
        self.assertIn("## 交互状态", state)
        self.assertIn('"bridge_move": "focus"', state)
        self.assertIn('"challenge_move": "test_evidence"', state)
        self.assertIn('"source": "candidate_statement"', state)
        self.assertIn('"interaction_channel": "web_voice"', state)
        self.assertIn('"current_question_push"', state)
        self.assertIn('"current_reply_consumption"', state)
        self.assertIn('"reply_wait_status"', state)
        self.assertIn('"event_cursor"', state)

        voice = (ROOT / "references" / "voice-interview.md").read_text(encoding="utf-8")
        for tool in (
            "create_interview_session",
            "send_interviewer_message",
            "wait_for_candidate_reply",
            "get_session_events",
            "close_interview_session",
        ):
            self.assertIn(tool, voice)

    def test_text_and_voice_channel_boundaries_are_explicit(self):
        skill = SKILL_PATH.read_text(encoding="utf-8")
        self.assertIn("## 选择交互方式", skill)
        self.assertIn("按当前配置开始文字面试", skill)
        self.assertIn("按当前配置开始语音面试", skill)
        self.assertIn("不得先让用户确认配置、再固定追加一次交互方式确认", skill)
        self.assertIn("interaction_channel", skill)
        self.assertIn("选择文字面试时不得读取或启动语音运行时", skill)
        self.assertIn("web_connected", skill)
        self.assertIn("scripts/voice_interview.py wait", skill)
        self.assertIn("不得发送最终答复", skill)
        self.assertIn("already_waiting", skill)
        self.assertIn("message_type: interviewer_question", skill)

        voice = (ROOT / "references" / "voice-interview.md").read_text(encoding="utf-8")
        self.assertIn("functions.wait", voice)
        self.assertIn("外层 25 秒", voice)

        self.assertIn("scripts/voice_interview.py open", skill)
        self.assertIn('`display_text` 只使用“面试开始”', skill)
        self.assertIn('`display_text` 只使用“面试结束”', skill)

    def test_generic_examples_are_not_anchored_to_programmer_interviews(self):
        generic_docs = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (POLICY_PATH, STATE_PATH, ARCHIVE_PATH)
        )
        programmer_example_markers = (
            "Kafka",
            "缓存一致性",
            "消息队列",
            "幂等重试",
            "微服务",
            "后端开发工程师",
        )
        for marker in programmer_example_markers:
            with self.subTest(marker=marker):
                self.assertNotIn(marker, generic_docs)

        readme = README_PATH.read_text(encoding="utf-8")
        for role in ("高级产品经理", "区域运营经理", "大客户销售经理"):
            with self.subTest(role=role):
                self.assertIn(role, readme)
        self.assertIn("技术专项面试", readme)

    def test_runtime_contract_has_no_coaching_mode(self):
        runtime_contract = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (
                SKILL_PATH,
                POLICY_PATH,
                STATE_PATH,
                MATRIX_PATH,
                RUBRICS_PATH,
                GENERATOR_PATH,
                TEMPLATE_PATH,
            )
        )
        for marker in (
            "教练模式",
            "feedback_mode",
            "coaching_note",
            "evidence_origin",
            "coach_interventions",
            '"origin": "coached"',
        ):
            with self.subTest(marker=marker):
                self.assertNotIn(marker, runtime_contract)


if __name__ == "__main__":
    unittest.main()
