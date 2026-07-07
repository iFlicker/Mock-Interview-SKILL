import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).with_name("generate_report.py")


class GenerateReportTest(unittest.TestCase):
    def test_generate_report_renders_distinct_sections_and_escapes_html(self):
        payload = {
            "interview_date": "2026-07-06",
            "target_position": "AI/ML Engineer",
            "interview_round": "行为面试/终面",
            "candidate_type": "社招候选人",
            "interview_language": "中文",
            "interviewer_style": "礼貌但直接",
            "pressure_value": 55,
            "scope_control": "2 个考察项",
            "focus_areas": ["跨团队协作", "冲突处理"],
            "special_sections": "无",
            "feedback_mode": "纯模拟",
            "question_bank": "未使用",
            "avoided_topics": "无",
            "resume_summary": "<script>alert('x')</script>",
            "jd_summary": "负责跨团队项目推进",
            "materials_note": "未使用",
            "opening": None,
            "topics": [
                {
                    "title": "冲突处理",
                    "qa_pairs": [
                        {
                            "question": "请讲一次与研发负责人意见不一致的经历。",
                            "answer": "我先确认目标，再同步风险。",
                        }
                    ],
                    "observation": "回答具体，能说明协调路径。",
                },
                {
                    "title": "跨团队协作",
                    "qa_pairs": [
                        {
                            "question": "你怎么推动外部团队按时交付？",
                            "answer": "我会拆节点、设依赖、提前暴露阻塞。",
                        },
                        {
                            "question": "如果对方持续延期呢？",
                            "answer": "我会升级风险并准备替代方案。",
                        },
                    ],
                    "observation": "有节奏感，但对量化结果描述偏少。",
                },
            ],
            "closing": None,
            "total_score": 78,
            "score_coverage": "覆盖了 2 个行为主题，可信度中等。",
            "covered_topics": ["冲突处理", "跨团队协作"],
            "dimensions": [
                {
                    "name": "沟通表达",
                    "weight": "30%",
                    "score": 82,
                    "evidence": "回答结构清楚，能交代背景和行动。",
                },
                {
                    "name": "业务结果",
                    "weight": "20%",
                    "score": None,
                    "evidence": "证据不足：没有给出明确结果数据。",
                },
            ],
            "strengths": ["能先对齐目标，再讨论分歧。"],
            "risks": ["量化结果不足。"],
            "gaps": ["缺少延期后的复盘指标。"],
            "improvements": ["补足结果指标。", "强化升级路径的判定条件。", "补充一次失败案例。"],
            "better_answers": [
                {
                    "question": "如果对方持续延期呢？",
                    "approach": "按时间线说明预警、升级和备选方案。",
                }
            ],
            "recommendation": "建议",
            "recommendation_reason": "沟通与协作能力扎实，但结果证据略弱。",
            "next_round_focus": "进一步验证影响范围和结果量化。",
            "generated_at": "2026-07-06 10:00:00 +08:00",
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            input_path = tmp_path / "payload.json"
            output_dir = tmp_path / "reports"
            input_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "--input",
                    str(input_path),
                    "--output-dir",
                    str(output_dir),
                ],
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)

            outputs = list(output_dir.glob("*.html"))
            self.assertEqual(len(outputs), 1)

            report = outputs[0].read_text(encoding="utf-8")

            self.assertNotIn("{{", report)
            self.assertNotIn("开场", report)
            self.assertNotIn("候选人提问", report)
            self.assertIn("冲突处理", report)
            self.assertIn("跨团队协作", report)
            self.assertIn('href="#sec-topic-1"', report)
            self.assertIn('id="sec-topic-1"', report)
            self.assertIn('href="#sec-topic-2"', report)
            self.assertIn('id="sec-topic-2"', report)
            self.assertIn("如果对方持续延期呢？", report)
            self.assertIn("&lt;script&gt;alert(&#x27;x&#x27;)&lt;/script&gt;", report)
            self.assertIn("fill-na", report)
            self.assertIn("N/A", report)


if __name__ == "__main__":
    unittest.main()
