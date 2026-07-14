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
            "schema_version": "mock-interview-report/3.0",
            "interview_date": "2026-07-06",
            "target_position": "AI/ML Engineer",
            "interview_round": "行为面试/终面",
            "target_seniority": "高级",
            "interview_stage": "终面",
            "interviewer_role": "招聘经理",
            "interview_format": "行为面试",
            "style_modifier": "常规",
            "candidate_type": "社招候选人",
            "interview_language": "中文",
            "interviewer_style": "礼貌但直接",
            "pressure_value": 55,
            "scope_control": "2 个考察项",
            "focus_areas": ["跨团队协作", "冲突处理"],
            "special_sections": "无",
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
            "completion_status": "completed",
            "total_score": 82,
            "scored_weight": 60,
            "score_coverage_note": "沟通表达已评分；业务结果证据不足。",
            "covered_topics": ["冲突处理", "跨团队协作"],
            "dimensions": [
                {
                    "name": "沟通表达",
                    "weight": "60%",
                    "score": 82,
                    "evidence": "回答结构清楚，能交代背景和行动。",
                },
                {
                    "name": "业务结果",
                    "weight": "40%",
                    "score": None,
                    "evidence": "证据不足：没有给出明确结果数据。",
                },
            ],
            "strengths": ["能先对齐目标，再讨论分歧。"],
            "issues": [
                {
                    "type": "风险或不足",
                    "evidence": "量化结果不足。",
                    "impact": "可能影响岗位匹配度或下一轮判断。"
                },
                {
                    "type": "矛盾、模糊点或知识缺口",
                    "evidence": "缺少延期后的复盘指标。",
                    "impact": "需要在后续追问中继续验证。"
                }
            ],
            "action_items": [
                {
                    "priority": "P0",
                    "target": "如果对方持续延期呢？",
                    "action": "补足结果指标。",
                    "better_approach": "按时间线说明预警、升级和备选方案。"
                },
                {
                    "priority": "P1",
                    "target": "改进项 2",
                    "action": "强化升级路径的判定条件。",
                    "better_approach": "按问题背景、个人行动、关键证据和结果复盘组织回答。"
                },
                {
                    "priority": "P2",
                    "target": "改进项 3",
                    "action": "补充一次失败案例。",
                    "better_approach": "按问题背景、个人行动、关键证据和结果复盘组织回答。"
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
            self.assertNotIn("https://fonts.googleapis.com", report)
            self.assertIn('<span class="chat-role i">面试官</span>', report)
            self.assertIn('<span class="chat-role c">候选人</span>', report)
            self.assertIn('href="#sec-topic-1"', report)
            self.assertIn('id="sec-topic-1"', report)
            self.assertIn("主要问题与证据", report)
            self.assertIn("优先改进建议", report)
            self.assertIn("下一轮建议", report)
            self.assertIn("建议进行下一轮面试", report)
            self.assertNotIn("进行下一轮面试：建议", report)
            self.assertIn("<dt>完成状态</dt>", report)
            self.assertIn("<dt>证据说明</dt>", report)
            self.assertIn("<dt>实际覆盖</dt>", report)
            self.assertNotIn("<h3>良好</h3>", report)
            self.assertIn("总结", report)
            self.assertNotIn("观察记录", report)
            self.assertIn("已评分权重 60%", report)
            self.assertIn("目标职级", report)
            self.assertIn("招聘经理", report)
            self.assertNotIn("反馈模式", report)
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

            second_result = subprocess.run(
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
            self.assertEqual(second_result.returncode, 0, second_result.stderr)
            self.assertEqual(len(list(output_dir.glob("*.html"))), 2)
            self.assertTrue(any(path.stem.endswith("-2") for path in output_dir.glob("*.html")))

    def test_generate_report_renders_optional_knowledge_corrections(self):
        payload = {
            "schema_version": "mock-interview-report/3.0",
            "interview_date": "2026-07-06",
            "target_position": "高级产品经理",
            "interview_round": "经理面",
            "candidate_type": "社招候选人",
            "interview_language": "中文",
            "interviewer_style": "直接、关注结果",
            "pressure_value": 65,
            "scope_control": "1 个主题",
            "resume_summary": "负责用户增长产品和新用户激活策略。",
            "topics": [
                {
                    "title": "新用户激活策略",
                    "qa_pairs": [
                        {
                            "question": "你如何判断新引导流程确实提升了激活率？",
                            "answer": "我对比了上线前后的激活率。",
                        }
                    ],
                    "observation": "回答过于简略，缺少对照设计和干扰因素处理。",
                }
            ],
            "dimensions": [
                {
                    "name": "问题分析与解决",
                    "weight": "100%",
                    "score": 62,
                    "evidence": "能说出基础指标，但缺少可靠的效果归因方法。",
                }
            ],
            "completion_status": "completed",
            "total_score": 62,
            "scored_weight": 100,
            "score_coverage_note": "覆盖了 1 个核心主题。",
            "recommendation": "待定",
            "recommendation_reason": "基础方向正确，但实验设计和效果归因仍有缺口。",
            "next_round_focus": "继续验证实验设计、业务取舍和跨部门推进。",
            "strengths": ["知道先定义并观察核心激活指标。"],
            "issues": [
                {
                    "type": "知识缺口",
                    "evidence": "只比较上线前后指标，没有说明对照组或混杂因素处理。",
                    "impact": "无法可靠判断指标变化是否由新引导流程带来。",
                }
            ],
            "action_items": [
                {
                    "priority": "P0",
                    "target": "新引导流程的效果归因",
                    "action": "补充实验假设、对照方案、核心指标和干扰因素处理。",
                    "better_approach": "按目标、假设、实验设计、结果和决策影响回答。",
                }
            ],
            "knowledge_corrections": [
                {
                    "severity": "核心缺口",
                    "topic": "实验设计与效果归因",
                    "observed_issue": "只比较上线前后指标，没有说明对照组、样本分配和混杂因素。",
                    "correct_understanding": "前后指标变化只能说明相关性。更可靠的归因需要先定义假设和指标，再通过随机对照或合理的准实验方法降低同期活动、用户结构和季节变化等因素的影响。",
                    "better_interview_answer": "先说明业务假设和指标口径，再介绍对照方案、样本与周期、干扰因素、实验结果和最终决策。",
                    "learning_entry": ["实验设计", "因果推断", "指标口径"],
                },
                {
                    "severity": "一般缺口",
                    "topic": "护栏指标",
                    "observed_issue": "只关注激活率，没有说明如何防止短期转化提升损害留存或投诉率。",
                    "correct_understanding": "实验不能只观察目标指标，还要设置留存、投诉、退出率或体验质量等护栏指标，避免局部优化掩盖长期或外溢损害。",
                    "better_interview_answer": "说明核心指标之外还监控哪些护栏指标，以及触发什么条件会停止或回滚方案。",
                    "learning_entry": "护栏指标、局部最优",
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
            self.assertIn('<h2 class="sec-t">知识点纠错与学习建议</h2>', report)
            self.assertIn("下一轮建议", report)
            self.assertIn("待定：是否进行下一轮面试", report)
            self.assertIn("本轮发现 2 个需要补齐的知识点，1 个核心缺口，1 个一般缺口。", report)
            self.assertIn('<details class="kc-item" open>', report)
            self.assertIn("全部展开", report)
            self.assertIn("全部收起", report)
            self.assertIn("实验设计与效果归因", report)
            self.assertIn("前后指标变化只能说明相关性", report)
            self.assertIn('<span class="kc-tag">实验设计</span>', report)
            self.assertIn('<span class="kc-tag">因果推断</span>', report)
            self.assertIn('<span class="kc-tag">指标口径</span>', report)

    def test_generate_report_supports_insufficient_evidence_without_numeric_score(self):
        payload = {
            "schema_version": "mock-interview-report/3.0",
            "interview_date": "2026-07-11",
            "target_position": "财务分析师",
            "interview_round": "专业一面",
            "candidate_type": "社招候选人",
            "interview_language": "中文",
            "interviewer_style": "严谨",
            "pressure_value": 55,
            "scope_control": "6 个主题",
            "resume_summary": "负责经营分析和预算跟踪。",
            "completion_status": "insufficient_evidence",
            "topics": [],
            "dimensions": [
                {
                    "name": "专业基础",
                    "weight": "60%",
                    "score": None,
                    "evidence": "证据不足：尚未取得有效回答。",
                },
                {
                    "name": "问题解决能力",
                    "weight": "40%",
                    "score": None,
                    "evidence": "证据不足：尚未取得有效回答。",
                },
            ],
            "total_score": None,
            "scored_weight": 0,
            "score_coverage_note": "面试在取得有效回答前结束，无法计算总分。",
            "recommendation": "待定",
            "recommendation_reason": "没有足够证据支持招聘建议。",
            "next_round_focus": "重新完成财务分析能力和问题解决能力考察。",
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            input_path = tmp_path / "payload.json"
            output_dir = tmp_path / "reports"
            input_path.write_text(
                json.dumps(payload, ensure_ascii=False), encoding="utf-8"
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
            self.assertIn("证据不足", report)
            self.assertIn("已评分权重 0%", report)
            self.assertIn("本轮在取得有效回答前结束", report)
            self.assertNotIn('id="sec-topic-1"', report)

    def test_generate_report_rejects_invalid_dimension_weights(self):
        payload = {
            "interview_date": "2026-07-06",
            "target_position": "区域运营经理",
            "interview_round": "经理面",
            "candidate_type": "社招候选人",
            "interview_language": "中文",
            "interviewer_style": "严谨",
            "pressure_value": 55,
            "scope_control": "1 个主题",
            "resume_summary": "负责区域门店经营和增长改善。",
            "topics": [
                {
                    "title": "门店增长诊断",
                    "qa_pairs": [{"question": "你会如何定位增长放缓？", "answer": "我会分层分析。"}],
                    "observation": "证据有限。",
                }
            ],
            "dimensions": [
                {
                    "name": "专业深度",
                    "weight": "80%",
                    "score": 70,
                    "evidence": "能够说明基础方法。",
                }
            ],
            "total_score": 70,
            "score_coverage": "覆盖有限。",
            "recommendation": "待定",
            "recommendation_reason": "仍需验证。",
            "next_round_focus": "继续验证经营诊断和落地能力。",
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            input_path = tmp_path / "payload.json"
            input_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "--input",
                    str(input_path),
                    "--output-dir",
                    str(tmp_path / "reports"),
                ],
                capture_output=True,
                text=True,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Dimension weights must total 100%", result.stderr)

    def test_generate_report_rejects_unsupported_schema_version(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            input_path = tmp_path / "payload.json"
            input_path.write_text(
                json.dumps({"schema_version": "mock-interview-report/99.0"}),
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "--input",
                    str(input_path),
                    "--output-dir",
                    str(tmp_path / "reports"),
                ],
                capture_output=True,
                text=True,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Unsupported schema_version", result.stderr)


if __name__ == "__main__":
    unittest.main()
