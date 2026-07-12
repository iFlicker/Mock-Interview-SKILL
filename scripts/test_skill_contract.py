import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CASES_PATH = ROOT / "tests" / "skill-contract-cases.json"
SKILL_PATH = ROOT / "SKILL.md"
POLICY_PATH = ROOT / "references" / "interview-policy.md"
STATE_PATH = ROOT / "references" / "session-state.md"
SCENARIOS_PATH = ROOT / "references" / "behavior-scenarios.md"

REQUIRED_SCENARIOS = {
    "resume_missing",
    "multiple_resumes",
    "config_missing",
    "skip_main_question",
    "pause_resume",
    "pressure_adjustment",
    "coach_evidence",
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
}

REQUIRED_COVERAGE = {
    "preflight",
    "configuration",
    "control",
    "state_transition",
    "coaching",
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
}


class SkillContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = json.loads(CASES_PATH.read_text(encoding="utf-8"))

    def test_contract_has_required_scenarios_and_coverage(self):
        self.assertEqual(
            self.contract["schema_version"], "mock-interview-contract/1.0"
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
        self.assertIn("## 问题质量门", policy)
        self.assertIn("## 矛盾分级", policy)

        state = STATE_PATH.read_text(encoding="utf-8")
        self.assertIn('"schema_version": "mock-interview-session/3.1"', state)
        self.assertIn('"main_question_id": "q-1"', state)
        self.assertIn('"follow_up_count": 2', state)
        self.assertIn('"depth_profile": "standard"', state)
        self.assertIn('"target_follow_up_range": {"min": 3, "max": 4}', state)
        self.assertNotIn('"round_count"', state)
        self.assertIn("## 不变量", state)
        self.assertIn("interviewing <-> paused", state)


if __name__ == "__main__":
    unittest.main()
