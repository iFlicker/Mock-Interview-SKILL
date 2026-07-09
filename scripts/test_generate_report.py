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
            self.assertNotIn("badge-yes", report)
            self.assertNotIn("RECOMMENDATION_BADGE_CLASS", report)
            self.assertIn("scrollIntoView", report)
            self.assertIn("is-scrolling", report)
            self.assertIn('href="#sec-topic-1"', report)
            self.assertIn('id="sec-topic-1"', report)
            self.assertIn("主要问题与证据", report)
            self.assertIn("优先改进建议", report)
            self.assertIn("下一轮建议", report)
            self.assertIn("进行下一轮面试：建议", report)
            self.assertNotIn("下一轮展望", report)
            self.assertIn("风险或不足", report)
            self.assertIn("按时间线说明预警、升级和备选方案。", report)
            self.assertNotIn("矛盾、模糊点或知识缺口</h2>", report)
            self.assertNotIn("关键问题的更优回答思路</h2>", report)
            self.assertNotIn('id="sec-knowledge"', report)
            self.assertIn('href="#sec-topic-2"', report)
            self.assertIn('id="sec-topic-2"', report)
            self.assertNotIn('href="#sec-topic-1">主题 1 ·', report)
            self.assertNotIn('href="#sec-topic-2">主题 2 ·', report)
            self.assertIn("如果对方持续延期呢？", report)
            self.assertIn("&lt;script&gt;alert(&#x27;x&#x27;)&lt;/script&gt;", report)
            self.assertIn("fill-na", report)
            self.assertIn("N/A", report)
            self.assertNotIn("Interview Report</div>", report)
            self.assertNotIn('<div class="sidebar-hd">', report)

    def test_generate_report_renders_optional_knowledge_corrections(self):
        payload = {
            "interview_date": "2026-07-06",
            "target_position": "后端开发工程师",
            "interview_round": "专业二面",
            "candidate_type": "社招候选人",
            "interview_language": "中文",
            "interviewer_style": "严谨、重视细节",
            "pressure_value": 55,
            "scope_control": "1 个主题",
            "feedback_mode": "纯模拟",
            "resume_summary": "负责交易链路服务治理。",
            "topics": [
                {
                    "title": "缓存一致性",
                    "qa_pairs": [
                        {
                            "question": "你如何处理缓存与数据库双写一致性？",
                            "answer": "我会删除缓存。",
                        }
                    ],
                    "observation": "回答过于简略，缺少异常路径。",
                }
            ],
            "dimensions": [
                {
                    "name": "专业深度",
                    "weight": "100%",
                    "score": 62,
                    "evidence": "能说出基础策略，但缺少并发和补偿机制。",
                }
            ],
            "total_score": 62,
            "score_coverage": "覆盖了 1 个核心主题。",
            "recommendation": "待定",
            "recommendation_reason": "基础方向正确，但关键机制缺失。",
            "next_round_focus": "继续验证一致性边界和异常补偿。",
            "strengths": ["知道缓存失效是一个可选方向。"],
            "issues": [
                {
                    "type": "知识缺口",
                    "evidence": "没有解释并发写和失败补偿。",
                    "impact": "影响高并发场景下的方案可信度。",
                }
            ],
            "action_items": [
                {
                    "priority": "P0",
                    "target": "缓存一致性",
                    "action": "补充异常路径和补偿机制。",
                    "better_approach": "按目标、路径、异常、监控回答。",
                }
            ],
            "knowledge_corrections": [
                {
                    "severity": "核心缺口",
                    "topic": "缓存与数据库一致性",
                    "observed_issue": "只回答了删除缓存，没有解释并发写、失败补偿和一致性边界。",
                    "correct_understanding": "这类问题通常不是追求绝对强一致，而是先判断业务能否接受短暂不一致，再通过更新数据库后删除缓存、失败重试、消息补偿、幂等处理和监控告警，把不一致窗口控制在可接受范围内。",
                    "better_interview_answer": "先说明一致性目标，再拆正常路径、异常路径、补偿机制、监控指标和取舍边界。",
                    "learning_entry": ["缓存失效策略", "最终一致性", "幂等重试"],
                },
                {
                    "severity": "一般缺口",
                    "topic": "延迟双删",
                    "observed_issue": "没有说明延迟双删的适用前提。",
                    "correct_understanding": "延迟双删用于降低部分并发读写导致脏缓存的概率，但不能替代补偿、监控和业务侧一致性判断。",
                    "better_interview_answer": "说明它解决的问题、不能解决的问题和替代方案。",
                    "learning_entry": "缓存并发读写、脏缓存",
                },
            ],
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

            report = next(output_dir.glob("*.html")).read_text(encoding="utf-8")

            self.assertNotIn("{{", report)
            self.assertIn('href="#sec-knowledge"', report)
            self.assertIn('id="sec-knowledge"', report)
            self.assertIn("知识点纠错与学习建议", report)
            self.assertIn("下一轮建议", report)
            self.assertIn("进行下一轮面试：待定", report)
            self.assertIn("本轮发现 2 个需要补齐的知识点，1 个核心缺口，1 个一般缺口。", report)
            self.assertIn('<details class="kc-item" open>', report)
            self.assertIn("全部展开", report)
            self.assertIn("全部收起", report)
            self.assertIn("缓存与数据库一致性", report)
            self.assertIn("这类问题通常不是追求绝对强一致", report)
            self.assertIn("缓存失效策略、最终一致性、幂等重试", report)


if __name__ == "__main__":
    unittest.main()
