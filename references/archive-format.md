# 面试报告生成格式

仅在用户明确同意生成面试报告后读取本文件。

## 保存规则

- 默认目录：当前已授权工作目录下的 `interview-records/`。
- 默认文件名：`YYYY-MM-DD-目标职位-面试轮次.html`。
- 使用 `scripts/generate_report.py --output-dir <目录>` 时，脚本会自动生成上述文件名，并清理路径分隔符和文件系统不允许的字符。
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
  --output /path/to/interview-records/2026-07-06-后端开发-专业二面.html
```

## Payload 结构

### 顶层必填字段

| 字段 | 类型 | 说明 |
|---|---|---|
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
| `total_score` | int | 加权总分，`0～100` |
| `score_coverage` | string | 评分覆盖度与可信度说明 |
| `recommendation` | string | 下一轮建议中的推荐结论，只能是 `强烈建议`、`建议`、`待定`、`不建议` |
| `recommendation_reason` | string | 下一轮建议中的结论依据 |
| `next_round_focus` | string | 下一轮建议中的重点考察方向 |
| `topics` | array | 至少一个主题或考察项 |
| `dimensions` | array | 至少一个评分维度 |

### 顶层常用可选字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `focus_areas` | string or array | 重点考察方向；数组会自动拼接 |
| `special_sections` | string | 专项环节说明；无则填 `无` |
| `question_bank` | string | 题库使用说明；无则填 `未使用` |
| `avoided_topics` | string | 避免话题；无则填 `无` |
| `jd_summary` | string | 职位描述摘要；无则填 `未提供` |
| `materials_note` | string | 题库或历史记录说明；无则填 `未使用` |
| `covered_topics` | string or array | 实际覆盖的主题或考察项；数组会自动拼接 |
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
| `observation` | string | 该主题的关键观察记录 |

`qa_pairs` 中每个元素都必须包含：

| 字段 | 类型 | 说明 |
|---|---|---|
| `question` | string | 面试官提问 |
| `answer` | string | 候选人回答 |

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
  "interview_date": "2026-07-06",
  "target_position": "后端开发工程师",
  "interview_round": "专业二面",
  "candidate_type": "社招候选人",
  "interview_language": "中文",
  "interviewer_style": "严谨、重视细节",
  "pressure_value": 55,
  "scope_control": "6 个主题",
  "feedback_mode": "纯模拟",
  "resume_summary": "最近三年负责交易链路服务治理和稳定性优化。",
  "jd_summary": "负责高并发交易系统的设计与优化。",
  "topics": [
    {
      "title": "缓存一致性",
      "qa_pairs": [
        {
          "question": "你如何处理缓存与数据库双写一致性？",
          "answer": "我会按写路径拆分失效时机，并补偿异常重试。"
        }
      ],
      "observation": "能回答主流程，但对极端失败场景展开不够。"
    }
  ],
  "dimensions": [
    {
      "name": "专业深度",
      "weight": "20%",
      "score": 78,
      "evidence": "能解释主要一致性策略与风险点。"
    },
    {
      "name": "业务结果",
      "weight": "15%",
      "score": null,
      "evidence": "证据不足：缺少量化结果。"
    }
  ],
  "total_score": 78,
  "score_coverage": "覆盖了 1 个核心主题，可信度有限。",
  "covered_topics": ["缓存一致性"],
  "strengths": ["能说明主链路设计和异常补偿思路。"],
  "issues": [
    {
      "type": "知识缺口",
      "evidence": "极端失败场景回答不够具体。",
      "impact": "下一轮可能继续验证异常路径和边界处理能力。"
    },
    {
      "type": "证据不足",
      "evidence": "没有给出稳定性优化后的结果指标。",
      "impact": "削弱了业务结果和个人贡献的可信度。"
    }
  ],
  "action_items": [
    {
      "priority": "P0",
      "target": "缓存与数据库双写一致性问题",
      "action": "补充异常路径、补偿机制、监控指标和一次真实故障复盘。",
      "better_approach": "按正常路径、异常路径、补偿机制和监控指标分层回答。"
    }
  ],
  "knowledge_corrections": [
    {
      "severity": "核心缺口",
      "topic": "缓存与数据库一致性",
      "observed_issue": "回答了缓存失效主流程，但没有说明并发写、失败补偿和一致性边界。",
      "correct_understanding": "这类问题通常不是追求绝对强一致，而是先判断业务能否接受短暂不一致，再通过更新数据库后删除缓存、失败重试、消息补偿、幂等处理和监控告警，把不一致窗口控制在可接受范围内。延迟双删可以降低部分并发读写造成脏缓存的概率，但不是银弹，仍要结合业务一致性要求和异常补偿设计。",
      "better_interview_answer": "先说明一致性目标，再拆正常路径、异常路径、补偿机制、监控指标和取舍边界。",
      "learning_entry": ["缓存失效策略", "最终一致性", "幂等重试", "消息可靠投递"]
    }
  ],
  "recommendation": "建议",
  "recommendation_reason": "基础扎实，但还需要更多结果证据。",
  "next_round_focus": "验证高并发写入场景下的边界处理。"
}
```

## 注意事项

- 只记录实际提出的问题和用户实际给出的回答。
- 非专业面通常没有开场自我介绍；没有就不要构造 `opening`。
- 未进行收尾问答时，不要构造 `closing`。
- 保留不确定性和“证据不足”标记，不得为了显得完整而改写报告内容。
- 最终 HTML 文件是自包含的，可以直接在浏览器中打开查看或打印。
