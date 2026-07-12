# 会话状态规范

在用户确认配置后、正式面试开始前读取本文件。它定义一次模拟面试的内部状态，是暂停恢复、证据追踪、矛盾处理、提前结束、评分和报告生成的唯一状态契约。

状态只在当前会话中静默维护，不代表永久记忆，也不授权写入文件。除非用户明确同意生成报告或另行保存，不得将状态持久化。

## Schema 版本

- 当前会话状态版本：`mock-interview-session/3.1`。本版本增加独立的开场和收尾问题类型、跳过替代预算及已完成会话重新授权报告的转换。
- `schema_version` 必填。字段语义发生不兼容变化时升级主版本；只增加可选字段时升级次版本。
- 会话状态版本与报告 payload 版本相互独立。报告版本由 `archive-format.md` 定义。

## 顶层结构

```json
{
  "schema_version": "mock-interview-session/3.1",
  "phase": "interviewing",
  "config": {},
  "score_blueprint": {},
  "topics": [],
  "current_topic_id": null,
  "question_history": [],
  "evidence_ledger": [],
  "contradictions": [],
  "coach_interventions": [],
  "control_history": [],
  "completion": null
}
```

## 阶段 `phase`

只允许以下状态：

| 状态 | 含义 |
|---|---|
| `preflight` | 正在取得简历、目标职位和必要配置 |
| `configuring` | 正在展示和确认本轮配置 |
| `ready` | 配置及评分蓝图已冻结，尚未输出开始条 |
| `interviewing` | 正式面试进行中 |
| `paused` | 用户暂停，暂时退出面试官角色 |
| `evaluating` | 已输出结束条，正在评价 |
| `report_pending` | 评价完成，等待报告授权 |
| `completed` | 用户拒绝报告或本轮无需继续操作 |
| `archived` | 用户授权且报告已经成功生成 |

合法转换：

```text
preflight -> configuring -> ready -> interviewing
interviewing <-> paused
interviewing -> evaluating -> report_pending
report_pending -> completed
report_pending -> archived
completed -> report_pending
```

不得从 `paused` 直接评分；用户要求结束时先恢复控制流并进入 `evaluating`。不得在 `report_pending` 前生成报告。用户先拒绝报告、后来明确反悔时，只有仍能可靠恢复本轮评价与证据账本，才可由 `completed` 回到 `report_pending`；否则要求重新提供必要数据，不得补写。

## 配置与评分蓝图

`config` 保存用户确认后的配置快照，至少包含候选人类型、目标职位和职级、面试阶段、面试官角色、面试形式、范围、压力值、语言和反馈模式。

`score_blueprint.dimensions` 保存冻结的维度及权重，面试开始后不得修改。中途的压力、重点、题目范围或覆盖数量调整只修改 `config` 和尚未开始的主题，并追加一条 `control_history` 记录旧值、新值和原因。目标职位或面试形式发生到足以使蓝图失效的变化时，不得在原会话中替换蓝图，应结束本轮并以新配置初始化新会话。

`config.scope` 同时保存 `confirmed_coverage_limit` 和 `replacement_budget`。确认数量是本轮覆盖上限；`replacement_budget` 默认等于确认数量，只用于替换主问题尚未取得证据便被跳过的主题，不增加覆盖上限。

## 主题状态

每个主题使用：

```json
{
  "id": "topic-1",
  "title": "缓存一致性",
  "status": "covered",
  "main_question_id": "q-1",
  "follow_up_count": 2,
  "depth_profile": "standard",
  "target_follow_up_range": {"min": 3, "max": 4},
  "depth_reasons": ["专业二面", "岗位核心主题"],
  "pressure_depth_bias": "none",
  "dimension_ids": ["professional_depth"],
  "evidence_slots": {
    "mechanism": "sufficient",
    "edge_cases": "weak",
    "validation": "missing"
  },
  "completion_reason": null
}
```

- `status` 只能是 `planned`、`started`、`covered`、`completed` 或 `skipped`。
- 首次提出主问题时由 `planned` 变为 `started`。
- 取得至少一条相关有效证据后变为 `covered`。
- 按 `interview-policy.md` 的深挖完成决策判断完成时机，变为 `completed` 并填写 `completion_reason`。
- 主问题被跳过且未取得证据时可以标记为 `skipped`；它不算已覆盖主题。
- `main_question_id` 记录当前主题唯一的主问题。主问题不计入 `follow_up_count`。
- `follow_up_count` 从主问题后的第一个正式问题开始单调递增。澄清、重新表述、矛盾核对和同主题其他正式问题都计为追问。
- `depth_profile` 只能是 `light`、`basic`、`standard`、`deep`、`strategic` 或 `critical`。
- `target_follow_up_range.min` 是建议深度，不是强制门槛；`max` 是当前主题预算，必须满足 `0 <= min <= max <= 6`。
- `depth_reasons` 至少记录基础映射理由；发生主题重要性、职级或压力调整时追加原因，不得只写“需要深挖”。
- `pressure_depth_bias` 只能是 `none` 或 `upper`。只有压力值 81～100、岗位核心主题且仍有高价值缺口时才可为 `upper`；它不能单独证明需要继续追问。
- 证据槽位只能是 `missing`、`weak`、`sufficient` 或 `contradicted`。
- `completion_reason` 使用稳定值：`evidence_sufficient`、`no_high_value_gap`、`candidate_unable`、`not_applicable`、`skipped`、`safety_stop`、`budget_exhausted` 或 `follow_up_limit`。需要补充说明时另行记录，不要把自由文本塞入状态枚举。

## 问题历史

`question_history` 中每项至少包含：

```json
{
  "id": "q-3",
  "topic_id": "topic-1",
  "kind": "follow_up",
  "follow_up_index": 2,
  "target_slots": ["edge_cases"],
  "text": "如果删除缓存失败，你会怎样处理？",
  "quality_gate": "passed",
  "answer_status": "answered"
}
```

`kind` 只能是 `opening`、`main`、`follow_up` 或 `closing`。`opening` 和 `closing` 的 `topic_id`、`follow_up_index` 均为 `null`；每轮最多各一个。每个主题只能有一个 `main`；主问题的 `follow_up_index` 为 `null`。追问的 `follow_up_index` 从 1 连续递增，并且必须等于该问题提出后主题的 `follow_up_count`。`quality_gate` 必须为 `passed`；未通过质量门的问题不得输出。`answer_status` 可以是 `answered`、`short`、`off_topic`、`skipped` 或 `unanswered`。

专业面自我介绍使用 `opening`。它不计入主题数量，但回答可以在确有评分价值时生成证据。基于职位描述的候选人提问环节使用 `closing`，只记录真实问答，不生成评分证据。

## 证据账本

证据只能追加，不得为了让评价更完整而改写旧证据：

```json
{
  "id": "ev-4",
  "question_id": "q-3",
  "topic_id": "topic-1",
  "dimension_ids": ["professional_depth"],
  "slot": "edge_cases",
  "origin": "independent",
  "representation": "paraphrase",
  "content": "候选人提出失败重试和告警，但没有说明幂等边界。",
  "signal": "partial",
  "confidence": "medium"
}
```

- `origin`：`independent` 或 `coached`；
- `representation`：`exact_quote` 或 `paraphrase`；无法可靠还原原话时只能使用 `paraphrase`；
- `signal`：`positive`、`partial`、`negative` 或 `insufficient`；
- `confidence`：`high`、`medium` 或 `low`；
- 同一回答可以产生多条证据，但每条必须对应明确槽位和维度；开场证据允许 `topic_id: null`，其他评分证据必须关联主题；收尾问答不得产生评分证据；
- 暂停期间的流程讨论不得进入证据账本。

## 矛盾记录

```json
{
  "id": "conflict-1",
  "evidence_ids": ["ev-2", "ev-7"],
  "classification": "missing_context",
  "status": "open",
  "clarification_question_id": null,
  "resolution": null
}
```

`classification` 只能是 `wording_difference`、`missing_context` 或 `substantive_conflict`；`status` 只能是 `open`、`resolved` 或 `unresolved`。只有 `substantive_conflict + unresolved` 可以作为未解决矛盾进入评价。

## 控制指令与完成状态

- 跳过、暂停、继续、压力调整、范围调整和结束面试都追加到 `control_history`。
- 暂停不会清空当前主题；继续时恢复 `current_topic_id`、主问题和原追问次数。
- 调小范围不删除已有主题和证据；调大范围只增加尚未开始的新主题，且两者都不修改评分蓝图。
- 主问题在取得证据前被跳过时，将主题标记为 `skipped`，消耗一次 `replacement_budget` 并创建替代主题；替代主题不增加确认的覆盖上限。预算耗尽后提前结束并记录原因。
- `completion` 在进入 `evaluating` 时写入，至少包含 `status`、`reason`、`covered_topic_ids` 和 `scored_weight`。
- 没有任何可评分证据时，`completion.status` 为 `insufficient_evidence`，数字总分为空。

## 不变量

在每回合结束后静默检查：

1. `current_topic_id` 非空时只能有一个，且它指向 `started` 或 `covered` 的主题；开场、收尾、主题切换完成后的瞬间可以为 `null`；
2. 每个主题只有一个主问题，主问题不计入追问次数；`target_follow_up_range` 合法且 `follow_up_count` 不超过其 `max` 和全局上限 6；已经完成或跳过的主题不能继续追加问题；
3. 每条证据关联已存在的问题和冻结维度；除 `opening` 证据允许主题为空外，其他证据还必须关联已存在主题；`closing` 不得关联评分证据；
4. `coached` 证据之前必须存在对应的 `coach_interventions`；
5. 已解决矛盾不得继续作为负面评分依据；
6. 暂停期间不新增正式问题和评分证据；
7. 输出结束条后不得再新增面试问题；
8. 未获授权时不得从会话状态生成或写入报告文件。
