# 面试报告生成格式

仅在用户明确同意生成面试报告后读取本文件。

## 保存规则

- 默认目录：当前已授权工作目录下的 `interview-records/`。
- 默认文件名：`YYYY-MM-DD-目标职位-面试轮次.html`。
- 使用 `scripts/generate_report.py --output-dir <目录>` 时，脚本会自动生成上述文件名，并清理路径分隔符和文件系统不允许的字符。
- 如果目标文件已经存在，脚本默认追加 `-2`、`-3` 等数字后缀，不覆盖旧报告。只有用户明确要求覆盖旧文件时，才可使用 `--overwrite`。
- 用户指定其他已授权路径或只要求保存评价摘要时，按照用户要求执行。
- 用户未同意、意思不明确或明确拒绝时，不得创建文件。
- 不得复制完整原始简历，只保留支持评价所必需的最少摘要。
- 除非用户明确要求，否则不得修改以前的记录。

## 生成流程

1. 将本轮面试整理为一个 JSON payload。
2. 将 payload 写入当前已授权工作区中的临时 JSON 文件。
3. 运行 `python3 scripts/generate_report.py --input <payload.json> --output-dir interview-records/`，或使用 `--output <完整路径>` 指定最终文件。
4. 验证脚本成功输出 HTML 文件后，再告知用户保存位置。
5. 如果用户没有要求保留中间 JSON，默认删除临时 payload 文件。

不得手工替换 `report-template.html` 中的占位符，也不得手工复制重复区块。模板展开必须交给脚本完成。

## 脚本能力

`scripts/generate_report.py` 负责：

- 展开重复区块，如主题、问答、评分维度、优势与改进项；
- 删除未发生的可选区块，如非专业面的开场、未进行的收尾问答；
- 根据总分和推荐结论自动选择颜色等级与 CSS class；
- 校验并兼容支持的报告 payload `schema_version`；
- 校验日期、候选人类型、反馈模式、压力值、维度权重、评分覆盖率、分数范围、总分计算和推荐结论约束；
- 对用户原话、题目内容和摘要做 HTML 转义，避免尖括号、代码片段或脚本内容破坏页面结构；
- 在生成结束前检查是否仍有未替换的占位符。

## 命令用法

```bash
python3 scripts/generate_report.py \
  --input /path/to/report-payload.json \
  --output-dir /path/to/interview-records
```

或：

```bash
python3 scripts/generate_report.py \
  --input /path/to/report-payload.json \
  --output /path/to/interview-records/2026-07-06-高级产品经理-经理面.html
```

仅在用户明确要求覆盖已有报告时使用：

```bash
python3 scripts/generate_report.py \
  --input /path/to/report-payload.json \
  --output /path/to/interview-records/report.html \
  --overwrite
```

## Payload 结构

当前报告 payload 版本为 `mock-interview-report/2.0`。`schema_version` 用于区分报告数据契约，不等同于 `session-state.md` 中的会话状态版本。字段发生不兼容变化时升级主版本；只增加向后兼容字段时升级次版本。生成器继续接受没有 `schema_version` 的旧 payload，并按旧版兼容模式处理；新报告必须显式提供当前版本。

### 顶层必填字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `schema_version` | string | 当前必须为 `mock-interview-report/2.0` |
| `interview_date` | string | 面试日期，格式 `YYYY-MM-DD` |
| `target_position` | string | 目标职位 |
| `interview_round` | string | 面试轮次与类型 |
| `candidate_type` | string | 实习生、应届生或社招候选人 |
| `interview_language` | string | 面试语言 |
| `interviewer_style` | string | 面试官级别与风格 |
| `pressure_value` | int | 压力值，`1～100` |
| `scope_control` | string | 范围控制说明 |
| `feedback_mode` | string | `纯模拟` 或 `教练模式` |
| `resume_summary` | string | 仅保留与评价有关的简历摘要 |
| `completion_status` | string | `completed`、`ended_early` 或 `insufficient_evidence` |
| `total_score` | int or null | 加权总分，`0～100`；没有任何可评分维度时必须为 `null` |
| `scored_weight` | int | 已取得数字得分的维度权重，`0～100`，也是评分覆盖率 |
| `score_coverage_note` | string | 评分覆盖范围、缺失维度和可信度说明 |
| `recommendation` | string | 下一轮建议中的推荐结论，只能是 `强烈建议`、`建议`、`待定`、`不建议` |
| `recommendation_reason` | string | 下一轮建议中的结论依据 |
| `next_round_focus` | string | 下一轮建议中的重点考察方向 |
| `topics` | array | 主题或考察项；用户在取得有效回答前结束时可以为空数组 |
| `dimensions` | array | 至少一个评分维度 |

`dimensions` 来自面试开始前冻结的评分蓝图，全部权重必须合计为 100%。证据不足的维度使用 `score: null`，但其权重仍计入 100%；`scored_weight` 必须等于有数字得分的维度权重之和。`scored_weight` 大于 0 时，`total_score` 按已评分维度重新归一化计算并四舍五入为整数；等于 0 时，`total_score` 必须为 `null`，不得用 0 分代替证据不足。

### 顶层常用可选字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `focus_areas` | string or array | 重点考察方向；数组会自动拼接 |
| `target_seniority` | string | 目标职级或资历基准 |
| `interview_stage` | string | 初筛、一面、二面、三面、终面等阶段 |
| `interviewer_role` | string | 人力资源、资深员工、经理、总监、高管等角色 |
| `interview_format` | string | 综合专业、行为、算法、系统设计等形式 |
| `style_modifier` | string | 常规或压力面试 |
| `special_sections` | string | 专项环节说明；无则填 `无` |
| `question_bank` | string | 题库使用说明；无则填 `未使用` |
| `avoided_topics` | string | 避免话题；无则填 `无` |
| `jd_summary` | string | 职位描述摘要；无则填 `未提供` |
| `materials_note` | string | 题库或历史记录说明；无则填 `未使用` |
| `covered_topics` | string or array | 实际覆盖的主题或考察项；数组会自动拼接 |
| `score_coverage` | string | 旧版兼容字段；新报告使用 `scored_weight` 和 `score_coverage_note` |
| `coaching_note` | string | 教练模式下说明提示对后续回答和评分可信度的影响；纯模拟可省略 |
| `generated_at` | string | 报告生成时间；缺省时脚本自动写入当前时间 |
| `strengths` | array | 明确优势列表；为空时脚本会写入 `未记录` |
| `issues` | array | 主要问题与证据；为空时脚本会写入 `未记录` |
| `action_items` | array | 优先改进建议；为空时脚本会写入 `未记录` |
| `knowledge_corrections` | array | 知识点纠错与学习建议；为空或省略时报告不展示该模块 |

兼容旧 payload 时，脚本会把 `risks` 和 `gaps` 折叠为 `issues`，把 `improvements` 和 `better_answers` 折叠为 `action_items`。新面试报告应优先使用 `issues` 和 `action_items`。

### 可选对象

#### `opening`

仅在实际有开场环节时传入；没有就直接省略或设为 `null`。

| 字段 | 类型 | 说明 |
|---|---|---|
| `title` | string | 可选，默认 `自我介绍` |
| `question` | string | 开场提问 |
| `answer` | string | 候选人回答 |

#### `closing`

仅在实际有收尾问答时传入；没有就直接省略或设为 `null`。

| 字段 | 类型 | 说明 |
|---|---|---|
| `title` | string | 可选，默认 `候选人提问` |
| `question` | string | 候选人提问 |
| `answer` | string | 面试官回答 |

### 主题结构

`topics` 中每个元素都必须包含：

| 字段 | 类型 | 说明 |
|---|---|---|
| `title` | string | 主题标题 |
| `qa_pairs` | array | 至少一个问答对 |
| `observation` | string | 该主题的总结；保留字段名以兼容已有 payload |

`qa_pairs` 中每个元素都必须包含：

| 字段 | 类型 | 说明 |
|---|---|---|
| `question` | string | 面试官提问 |
| `answer` | string | 候选人回答 |
| `evidence_origin` | string | 可选，`independent` 或 `coached`；教练模式下应提供 |

### 评分维度结构

`dimensions` 中每个元素都必须包含：

| 字段 | 类型 | 说明 |
|---|---|---|
| `name` | string | 评分维度名称 |
| `weight` | string | 权重，例如 `20%` |
| `score` | int or null | 具体得分，或 `null` 表示证据不足 |
| `evidence` | string | 评分依据 |

### 主要问题结构

`issues` 中每个元素包含：

| 字段 | 类型 | 说明 |
|---|---|---|
| `type` | string | 问题类型，例如风险、不足、矛盾、知识缺口或证据不足 |
| `evidence` | string | 对应的具体回答、行为或观察 |
| `impact` | string | 对通过率、职级判断或下一轮考察的影响 |

### 优先改进建议结构

`action_items` 中每个元素包含：

| 字段 | 类型 | 说明 |
|---|---|---|
| `priority` | string | 优先级，例如 P0、P1、P2 |
| `target` | string | 针对的具体问题 |
| `action` | string | 应补充的证据、知识点或练习动作 |
| `better_approach` | string | 更好的回答结构；不得编造经历 |

### 知识点纠错与学习建议结构

`knowledge_corrections` 中每个元素包含：

| 字段 | 类型 | 说明 |
|---|---|---|
| `severity` | string | 严重程度，例如核心缺口、一般缺口或 P0、P1、P2 |
| `topic` | string | 知识点名称 |
| `observed_issue` | string | 本轮表现，只记录实际问到且没答上、答错或关键机制缺失的内容 |
| `correct_understanding` | string | 正确理解，可以比其他字段稍详细，但不要写成大篇幅教程 |
| `better_interview_answer` | string | 面试中更好的回答组织方式 |
| `learning_entry` | string or array | 学习入口；数组会自动拼接为短标签 |

展示规则：

- 仅在专业面试中使用；非专业面通常不需要构造本字段。
- 没有需要纠错或补课的知识点时，省略该字段或传空数组，报告中不会展示该模块。
- 只记录本轮实际问到的知识点，不扩展成完整课程。
- `correct_understanding` 允许稍微展开，目标是给用户正确答案的骨架和关键边界，而不是完整教材。
- 同一知识点如果已经写入 `knowledge_corrections`，`issues` 中只保留一句诊断和影响，不展开正确理解、学习入口或完整回答思路。

## 最小示例

```json
{
  "schema_version": "mock-interview-report/2.0",
  "interview_date": "2026-07-06",
  "target_position": "高级产品经理",
  "interview_round": "经理面",
  "candidate_type": "社招候选人",
  "interview_language": "中文",
  "interviewer_style": "直接、关注结果",
  "pressure_value": 65,
  "scope_control": "6 个主题",
  "feedback_mode": "纯模拟",
  "completion_status": "completed",
  "resume_summary": "最近三年负责用户增长产品和新用户激活策略。",
  "jd_summary": "负责增长机会识别、产品决策和跨部门落地。",
  "topics": [
    {
      "title": "新用户激活策略",
      "qa_pairs": [
        {
          "question": "你如何判断新引导流程确实提升了激活率？",
          "answer": "我对比了上线前后的激活率，并跟踪了关键步骤的转化。"
        }
      ],
      "observation": "能说明核心指标和转化漏斗，但没有建立可靠的对照或排除同期活动影响。"
    }
  ],
  "dimensions": [
    {
      "name": "问题分析与解决",
      "weight": "60%",
      "score": 78,
      "evidence": "能定义激活指标并拆解关键转化环节。"
    },
    {
      "name": "业务结果",
      "weight": "40%",
      "score": null,
      "evidence": "证据不足：缺少量化结果。"
    }
  ],
  "total_score": 78,
  "scored_weight": 60,
  "score_coverage_note": "问题分析与解决已评分；业务结果证据不足，结论可信度有限。",
  "covered_topics": ["新用户激活策略"],
  "strengths": ["能定义激活指标并拆解关键转化环节。"],
  "issues": [
    {
      "type": "知识缺口",
      "evidence": "只比较上线前后数据，没有说明对照组或混杂因素处理。",
      "impact": "无法可靠判断指标提升是否由新引导流程带来。"
    },
    {
      "type": "证据不足",
      "evidence": "没有给出实验持续时间、样本规模或分群结果。",
      "impact": "削弱了业务结果和个人贡献的可信度。"
    }
  ],
  "action_items": [
    {
      "priority": "P0",
      "target": "新引导流程的效果归因",
      "action": "补充实验假设、对照方案、核心指标、护栏指标和干扰因素处理。",
      "better_approach": "按目标、假设、实验设计、结果、干扰因素和决策影响组织回答。"
    }
  ],
  "knowledge_corrections": [
    {
      "severity": "核心缺口",
      "topic": "实验设计与效果归因",
      "observed_issue": "只比较了上线前后指标，没有说明对照组、样本分配和混杂因素。",
      "correct_understanding": "前后指标变化只能说明相关性。更可靠的归因需要先定义假设、核心指标和护栏指标，再通过随机对照或合理的准实验方法降低同期活动、用户结构和季节变化等因素的影响，同时检查样本量、实验周期和分群差异。",
      "better_interview_answer": "先说明业务假设和指标口径，再介绍对照方案、样本与周期、干扰因素、实验结果和最终决策。",
      "learning_entry": ["实验设计", "因果推断", "指标口径", "护栏指标"]
    }
  ],
  "recommendation": "建议",
  "recommendation_reason": "分析框架较完整，但还需要更可靠的效果归因证据。",
  "next_round_focus": "验证实验设计、业务取舍和跨部门推进能力。"
}
```

## 注意事项

- 只记录实际提出的问题和用户实际给出的回答。
- 教练模式下为问答记录 `evidence_origin`，并在 `coaching_note` 中说明提示对评分的影响。
- 非专业面通常没有开场自我介绍；没有就不要构造 `opening`。
- 未进行收尾问答时，不要构造 `closing`。
- 保留不确定性和“证据不足”标记，不得为了显得完整而改写报告内容。
- 用户在取得有效回答前结束时，允许 `topics: []`、`scored_weight: 0` 和 `total_score: null`；此时 `completion_status` 必须为 `insufficient_evidence`，推荐结论只能为 `待定` 或 `不建议`。
- 最终 HTML 文件是自包含的，不引用网络字体或其他外部资源，可以离线打开、查看或打印。
