#!/usr/bin/env python3

import argparse
import html
import json
import re
from datetime import datetime
from pathlib import Path


TEMPLATE_PATH = Path(__file__).with_name("report-template.html")
REPORT_SCHEMA_VERSION = "mock-interview-report/3.0"
SUPPORTED_REPORT_SCHEMA_VERSIONS = {
    "mock-interview-report/1.0",
    "mock-interview-report/2.0",
    REPORT_SCHEMA_VERSION,
}

SCORE_LEVELS = [
    {
        "min": 90,
        "max": 100,
        "grade": "卓越",
        "bg_class": "bg-excellent",
        "fill_class": "fill-excellent",
        "color": "#059669",
    },
    {
        "min": 75,
        "max": 89,
        "grade": "良好",
        "bg_class": "bg-good",
        "fill_class": "fill-good",
        "color": "#2563eb",
    },
    {
        "min": 60,
        "max": 74,
        "grade": "合格",
        "bg_class": "bg-adequate",
        "fill_class": "fill-adequate",
        "color": "#d97706",
    },
    {
        "min": 40,
        "max": 59,
        "grade": "待提升",
        "bg_class": "bg-needs-improve",
        "fill_class": "fill-needs-improve",
        "color": "#ea580c",
    },
    {
        "min": 0,
        "max": 39,
        "grade": "不通过",
        "bg_class": "bg-fail",
        "fill_class": "fill-fail",
        "color": "#dc2626",
    },
]

NA_SCORE_STYLE = {
    "grade": "N/A",
    "bg_class": "bg-na",
    "fill_class": "fill-na",
    "color": "#94a3b8",
}

RECOMMENDATION_STYLES = {
    "强烈建议": {
        "recommendation_class": "rec-strong",
        "recommendation_label": "强烈建议进行下一轮面试",
    },
    "建议": {
        "recommendation_class": "rec-yes",
        "recommendation_label": "建议进行下一轮面试",
    },
    "待定": {
        "recommendation_class": "rec-pending",
        "recommendation_label": "待定：是否进行下一轮面试",
    },
    "不建议": {
        "recommendation_class": "rec-no",
        "recommendation_label": "不建议进行下一轮面试",
    },
}


def parse_args():
    parser = argparse.ArgumentParser(
        description="Generate a Mock-Interview HTML report from a JSON payload."
    )
    parser.add_argument("--input", required=True, help="Path to the input JSON payload.")
    parser.add_argument(
        "--output",
        help="Exact output HTML path. Use this or --output-dir.",
    )
    parser.add_argument(
        "--output-dir",
        help="Directory for auto-generated filename. Use this or --output.",
    )
    parser.add_argument(
        "--template",
        default=str(TEMPLATE_PATH),
        help="Path to the HTML template file.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite an existing output file instead of appending a numeric suffix.",
    )
    args = parser.parse_args()

    if bool(args.output) == bool(args.output_dir):
        parser.error("Specify exactly one of --output or --output-dir.")

    return args


def load_json(path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def stringify(value, default=""):
    if value is None:
        return default
    if isinstance(value, list):
        parts = [stringify(item).strip() for item in value if stringify(item).strip()]
        return "、".join(parts) if parts else default
    return str(value)


def escape_value(value, default=""):
    return html.escape(stringify(value, default=default), quote=True)


def require_fields(payload, fields):
    missing = [field for field in fields if payload.get(field) in (None, "", [])]
    if missing:
        raise ValueError(f"Missing required fields: {', '.join(missing)}")


def require_object_fields(item, fields, label):
    if not isinstance(item, dict):
        raise ValueError(f"{label} must be an object.")
    missing = [field for field in fields if item.get(field) in (None, "", [])]
    if missing:
        raise ValueError(f"{label} missing required fields: {', '.join(missing)}")


def require_int_in_range(value, label, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{label} must be an integer.")
    if value < minimum or value > maximum:
        raise ValueError(f"{label} must be between {minimum} and {maximum}.")
    return value


def format_percentage(value):
    return f"{value:g}%"


def parse_weight(value, label):
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a percentage string such as 20%.")
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)%\s*", value)
    if not match:
        raise ValueError(f"{label} must be a percentage string such as 20%.")
    weight = float(match.group(1))
    if weight <= 0 or weight > 100:
        raise ValueError(f"{label} must be greater than 0% and at most 100%.")
    return weight


def validate_payload(payload):
    if not isinstance(payload, dict):
        raise ValueError("Payload must be a JSON object.")

    schema_version = payload.get("schema_version")
    if schema_version is None:
        payload["schema_version"] = "mock-interview-report/1.0"
    elif schema_version not in SUPPORTED_REPORT_SCHEMA_VERSIONS:
        raise ValueError(
            "Unsupported schema_version. Supported versions: "
            + ", ".join(sorted(SUPPORTED_REPORT_SCHEMA_VERSIONS))
            + "."
        )

    require_fields(
        payload,
        [
            "interview_date",
            "target_position",
            "interview_round",
            "candidate_type",
            "interview_language",
            "interviewer_style",
            "pressure_value",
            "scope_control",
            "resume_summary",
            "dimensions",
            "recommendation",
            "recommendation_reason",
            "next_round_focus",
        ],
    )

    if "total_score" not in payload:
        raise ValueError("Missing required fields: total_score")
    if "topics" not in payload:
        raise ValueError("Missing required fields: topics")

    coverage_note = payload.get("score_coverage_note") or payload.get("score_coverage")
    if not coverage_note:
        raise ValueError("Missing required fields: score_coverage_note")
    payload["score_coverage_note"] = coverage_note

    try:
        parsed_date = datetime.strptime(payload["interview_date"], "%Y-%m-%d")
    except (TypeError, ValueError) as exc:
        raise ValueError("interview_date must use YYYY-MM-DD format.") from exc
    if parsed_date.strftime("%Y-%m-%d") != payload["interview_date"]:
        raise ValueError("interview_date must use YYYY-MM-DD format.")

    if payload["candidate_type"] not in {"实习生", "应届生", "社招候选人"}:
        raise ValueError("candidate_type must be 实习生、应届生 or 社招候选人.")
    if payload["recommendation"] not in RECOMMENDATION_STYLES:
        raise ValueError("recommendation must be 强烈建议、建议、待定 or 不建议.")

    completion_status = payload.get("completion_status")
    if completion_status is not None and completion_status not in {
        "completed",
        "ended_early",
        "insufficient_evidence",
    }:
        raise ValueError(
            "completion_status must be completed、ended_early or insufficient_evidence."
        )

    require_int_in_range(payload["pressure_value"], "pressure_value", 1, 100)

    topics = payload["topics"]
    if not isinstance(topics, list):
        raise ValueError("topics must be an array.")
    for topic_index, topic in enumerate(topics, start=1):
        label = f"topics[{topic_index}]"
        require_object_fields(topic, ["title", "qa_pairs", "observation"], label)
        if not isinstance(topic["qa_pairs"], list):
            raise ValueError(f"{label}.qa_pairs must be an array.")
        for qa_index, qa_pair in enumerate(topic["qa_pairs"], start=1):
            require_object_fields(
                qa_pair,
                ["question", "answer"],
                f"{label}.qa_pairs[{qa_index}]",
            )
    for optional_name, fields in {
        "opening": ["question", "answer"],
        "closing": ["question", "answer"],
    }.items():
        optional_item = payload.get(optional_name)
        if optional_item is not None:
            require_object_fields(optional_item, fields, optional_name)

    dimensions = payload["dimensions"]
    if not isinstance(dimensions, list):
        raise ValueError("dimensions must be an array.")
    total_weight = 0.0
    scored_weight = 0.0
    weighted_score = 0.0
    for index, dimension in enumerate(dimensions, start=1):
        label = f"dimensions[{index}]"
        require_object_fields(dimension, ["name", "weight", "evidence"], label)
        weight = parse_weight(dimension["weight"], f"{label}.weight")
        total_weight += weight
        score = dimension.get("score")
        if score is not None:
            score = require_int_in_range(score, f"{label}.score", 0, 100)
            scored_weight += weight
            weighted_score += score * weight

    if abs(total_weight - 100.0) > 0.001:
        raise ValueError(f"Dimension weights must total 100%, got {total_weight:g}%.")

    declared_scored_weight = payload.get("scored_weight")
    if declared_scored_weight is not None:
        declared_scored_weight = require_int_in_range(
            declared_scored_weight, "scored_weight", 0, 100
        )
        if abs(declared_scored_weight - scored_weight) > 0.001:
            raise ValueError(
                "scored_weight must equal the sum of weights for dimensions with numeric "
                f"scores: expected {format_percentage(scored_weight)}."
            )
    elif abs(scored_weight - round(scored_weight)) > 0.001:
        raise ValueError(
            "scored_weight is required when scored dimension weights are not whole percentages."
        )
    else:
        payload["scored_weight"] = int(round(scored_weight))

    total_score = payload["total_score"]
    if scored_weight == 0:
        if total_score is not None:
            raise ValueError("total_score must be null when scored_weight is 0%.")
        if payload["recommendation"] not in {"待定", "不建议"}:
            raise ValueError(
                "recommendation must be 待定 or 不建议 when there is no numeric score."
            )
        if topics:
            raise ValueError("topics must be empty when no dimension has scorable evidence.")
        if completion_status not in {None, "insufficient_evidence"}:
            raise ValueError(
                "completion_status must be insufficient_evidence when scored_weight is 0%."
            )
        payload["completion_status"] = "insufficient_evidence"
    else:
        total_score = require_int_in_range(total_score, "total_score", 0, 100)
        expected_total = int(weighted_score / scored_weight + 0.5)
        if total_score != expected_total:
            raise ValueError(
                "total_score must equal the weighted average of scored dimensions "
                f"after excluding evidence-insufficient dimensions: expected {expected_total}."
            )
        if completion_status == "insufficient_evidence":
            raise ValueError(
                "completion_status cannot be insufficient_evidence when numeric scores exist."
            )
        payload["completion_status"] = completion_status or "completed"

        recommendation = payload["recommendation"]
        if total_score < 60 and recommendation != "不建议":
            raise ValueError("recommendation must be 不建议 when total_score is below 60.")
        if 60 <= total_score < 75 and recommendation in {"强烈建议", "建议"}:
            raise ValueError(
                "recommendation must be 待定 or 不建议 when total_score is below 75."
            )
        if 75 <= total_score < 90 and recommendation == "强烈建议":
            raise ValueError("recommendation cannot be 强烈建议 when total_score is below 90.")
        if scored_weight < 60 and recommendation in {"强烈建议", "建议"}:
            raise ValueError(
                "recommendation must be 待定 or 不建议 when scored dimension coverage is below 60%."
            )
        if scored_weight < 80 and recommendation == "强烈建议":
            raise ValueError(
                "recommendation cannot be 强烈建议 when scored dimension coverage is below 80%."
            )

    for list_name, required_fields in {
        "issues": ["type", "evidence", "impact"],
        "action_items": ["priority", "target", "action", "better_approach"],
        "knowledge_corrections": [
            "severity",
            "topic",
            "observed_issue",
            "correct_understanding",
            "better_interview_answer",
            "learning_entry",
        ],
    }.items():
        items = payload.get(list_name)
        if items is None:
            continue
        if not isinstance(items, list):
            raise ValueError(f"{list_name} must be an array.")
        for index, item in enumerate(items, start=1):
            require_object_fields(item, required_fields, f"{list_name}[{index}]")


def get_score_style(score):
    numeric_score = int(score)
    if numeric_score < 0 or numeric_score > 100:
        raise ValueError(f"Score out of range: {numeric_score}")

    for level in SCORE_LEVELS:
        if level["min"] <= numeric_score <= level["max"]:
            return level

    raise ValueError(f"Unable to map score: {numeric_score}")


def get_dimension_context(item):
    score = item.get("score")
    if score is None:
        style = NA_SCORE_STYLE
        score_text = "N/A"
        score_percent = 0
    else:
        style = get_score_style(score)
        score_text = int(score)
        score_percent = int(score)

    return {
        "DIMENSION_NAME": item["name"],
        "WEIGHT": item["weight"],
        "DIMENSION_SCORE": score_text,
        "SCORE_COLOR": style["color"],
        "FILL_CLASS": style["fill_class"],
        "SCORE_PERCENT": score_percent,
        "EVIDENCE": item["evidence"],
    }


def render_placeholders(template, context):
    def replace(match):
        key = match.group(1)
        if key not in context:
            raise ValueError(f"Unresolved placeholder: {key}")
        return escape_value(context[key])

    return re.sub(r"\{\{([A-Z0-9_]+)\}\}", replace, template)


def replace_optional_block(template, name, context=None):
    pattern = re.compile(
        rf"<!-- BEGIN OPTIONAL {name} -->(.*?)<!-- END OPTIONAL {name} -->",
        re.DOTALL,
    )
    match = pattern.search(template)
    if not match:
        raise ValueError(f"Missing optional block marker: {name}")

    replacement = ""
    if context is not None:
        replacement = render_placeholders(match.group(1), context)

    return template[: match.start()] + replacement + template[match.end() :]


def replace_repeat_block(template, name, items, renderer):
    pattern = re.compile(
        rf"<!-- BEGIN REPEAT {name} -->(.*?)<!-- END REPEAT {name} -->",
        re.DOTALL,
    )
    match = pattern.search(template)
    if not match:
        raise ValueError(f"Missing repeat block marker: {name}")

    block = match.group(1)
    rendered = "".join(renderer(block, item, index) for index, item in enumerate(items, start=1))
    return template[: match.start()] + rendered + template[match.end() :]


def render_topic_block(block, topic, index):
    qa_pairs = topic.get("qa_pairs") or []
    if not qa_pairs:
        raise ValueError(f"Topic {index} must contain at least one qa_pairs item.")

    block = replace_repeat_block(
        block,
        "qa",
        qa_pairs,
        lambda qa_block, qa_item, _index: render_placeholders(
            qa_block,
            {
                "QUESTION": qa_item["question"],
                "ANSWER": qa_item["answer"],
            },
        ),
    )
    return render_placeholders(
        block,
        {
            "TOPIC_INDEX": index,
            "TOPIC_TITLE": topic["title"],
            "OBSERVATION": topic["observation"],
        },
    )


def render_topic_nav_block(block, topic, index):
    return render_placeholders(
        block,
        {
            "TOPIC_INDEX": index,
            "TOPIC_TITLE": topic["title"],
        },
    )


def render_simple_list_block(block, item, _index, placeholder):
    return render_placeholders(block, {placeholder: item})


def normalize_issues(payload):
    if payload.get("issues"):
        return payload["issues"]

    if payload.get("completion_status") == "insufficient_evidence":
        return [
            {
                "type": "证据不足",
                "evidence": "本轮在取得可评分回答前结束。",
                "impact": "无法形成可靠的能力得分或招聘建议。",
            }
        ]

    issues = []
    for risk in payload.get("risks") or []:
        issues.append(
            {
                "type": "风险或不足",
                "evidence": risk,
                "impact": "可能影响岗位匹配度或下一轮判断。",
            }
        )
    for gap in payload.get("gaps") or []:
        issues.append(
            {
                "type": "矛盾、模糊点或知识缺口",
                "evidence": gap,
                "impact": "需要在后续追问中继续验证。",
            }
        )
    return issues or [
        {
            "type": "无单独记录",
            "evidence": "本轮未记录需要单独列出的主要问题。",
            "impact": "仍应结合评分覆盖范围理解本轮结论。",
        }
    ]


def normalize_action_items(payload):
    if payload.get("action_items"):
        return payload["action_items"]

    if payload.get("completion_status") == "insufficient_evidence":
        return [
            {
                "priority": "P0",
                "target": "完成一次可评分的模拟面试",
                "action": "重新开始面试，并至少完成一个与目标岗位相关的核心主题。",
                "better_approach": "先直接回答主问题；不确定时说明已知边界和分析思路。",
            }
        ]

    actions = []
    better_answers = payload.get("better_answers") or []
    max_len = max(len(payload.get("improvements") or []), len(better_answers))
    for index in range(max_len):
        improvement = (
            payload.get("improvements", [])[index]
            if index < len(payload.get("improvements") or [])
            else "围绕对应问题补充证据并进行针对性练习。"
        )
        better_answer = better_answers[index] if index < len(better_answers) else {}
        actions.append(
            {
                "priority": f"P{index}",
                "target": better_answer.get("question", f"改进项 {index + 1}"),
                "action": improvement,
                "better_approach": better_answer.get(
                    "approach", "按问题背景、个人行动、关键证据和结果复盘组织回答。"
                ),
            }
        )
    return actions or [
        {
            "priority": "P0",
            "target": "本轮主要改进方向",
            "action": "结合主要问题补充具体证据并进行针对性练习。",
            "better_approach": "按问题背景、个人行动、关键证据和结果复盘组织回答。",
        }
    ]


def render_issue_block(block, item, _index):
    return render_placeholders(
        block,
        {
            "ISSUE_TYPE": item.get("type", "未记录"),
            "ISSUE_EVIDENCE": item.get("evidence", "未记录"),
            "ISSUE_IMPACT": item.get("impact", "未记录"),
        },
    )


def render_action_item_block(block, item, _index):
    return render_placeholders(
        block,
        {
            "ACTION_PRIORITY": item.get("priority", "未记录"),
            "ACTION_TARGET": item.get("target", "未记录"),
            "ACTION_DETAIL": item.get("action", "未记录"),
            "BETTER_APPROACH": item.get("better_approach", "未记录"),
        },
    )


def get_knowledge_corrections(payload):
    return payload.get("knowledge_corrections") or []


def should_open_knowledge_item(item):
    severity = stringify(item.get("severity")).lower()
    return (
        "核心" in severity
        or "p0" in severity
        or "严重" in severity
        or "critical" in severity
    )


def get_knowledge_summary(items):
    total = len(items)
    core_count = sum(1 for item in items if should_open_knowledge_item(item))
    general_count = total - core_count
    parts = [f"本轮发现 {total} 个需要补齐的知识点"]
    if core_count:
        parts.append(f"{core_count} 个核心缺口")
    if general_count:
        parts.append(f"{general_count} 个一般缺口")
    return "：{}。".format("，".join(parts))


def render_knowledge_correction_block(block, item, _index):
    learning_entries = item.get("learning_entry")
    if not isinstance(learning_entries, list):
        learning_entries = [learning_entries]
    block = replace_repeat_block(
        block,
        "learning_entry",
        learning_entries,
        lambda entry_block, entry, _entry_index: render_placeholders(
            entry_block, {"KC_LEARNING_ENTRY": entry}
        ),
    )
    return render_placeholders(
        block,
        {
            "DETAILS_OPEN": "open" if should_open_knowledge_item(item) else "",
            "KC_SEVERITY": item.get("severity", "一般缺口"),
            "KC_TOPIC": item.get("topic", "未记录"),
            "KC_OBSERVED_ISSUE": item.get("observed_issue", "未记录"),
            "KC_CORRECT_UNDERSTANDING": item.get("correct_understanding", "未记录"),
            "KC_BETTER_INTERVIEW_ANSWER": item.get(
                "better_interview_answer", "未记录"
            ),
        },
    )


def sanitize_filename_part(value):
    sanitized = re.sub(r'[\\/:*?"<>|]+', "-", stringify(value))
    sanitized = re.sub(r"\s+", "-", sanitized).strip("-")
    return sanitized or "untitled"


def append_available_suffix(path):
    if not path.exists():
        return path
    for index in range(2, 10000):
        candidate = path.with_name(f"{path.stem}-{index}{path.suffix}")
        if not candidate.exists():
            return candidate
    raise ValueError(f"Unable to find an available filename for: {path}")


def resolve_output_path(args, payload):
    if args.output:
        output_path = Path(args.output)
        return output_path if args.overwrite else append_available_suffix(output_path)

    output_dir = Path(args.output_dir)
    filename = "{date}-{position}-{round}.html".format(
        date=sanitize_filename_part(payload["interview_date"]),
        position=sanitize_filename_part(payload["target_position"]),
        round=sanitize_filename_part(payload["interview_round"]),
    )
    output_path = output_dir / filename
    return output_path if args.overwrite else append_available_suffix(output_path)


def build_base_context(payload):
    recommendation = payload["recommendation"]
    if recommendation not in RECOMMENDATION_STYLES:
        raise ValueError(f"Unsupported recommendation: {recommendation}")

    total_score = payload["total_score"]
    if total_score is None:
        total_score_text = "N/A"
        total_style = {
            **NA_SCORE_STYLE,
            "grade": "证据不足",
        }
    else:
        total_score_text = int(total_score)
        total_style = get_score_style(total_score)
    recommendation_style = RECOMMENDATION_STYLES[recommendation]
    covered_topics = payload.get("covered_topics") or [
        topic.get("title", "未命名主题") for topic in payload.get("topics", [])
    ]
    if not covered_topics:
        covered_topics = "未取得有效回答"

    status_labels = {
        "completed": "正常完成",
        "ended_early": "提前结束",
        "insufficient_evidence": "证据不足",
    }
    generated_at = payload.get("generated_at")
    if not generated_at:
        generated_at = datetime.now().astimezone().isoformat(sep=" ", timespec="seconds")

    return {
        "TARGET_POSITION": payload["target_position"],
        "INTERVIEW_ROUND": payload["interview_round"],
        "INTERVIEW_DATE": payload["interview_date"],
        "CANDIDATE_TYPE": payload["candidate_type"],
        "TARGET_SENIORITY": payload.get("target_seniority", "未单独记录"),
        "INTERVIEW_STAGE": payload.get("interview_stage", "未单独记录"),
        "INTERVIEWER_ROLE": payload.get("interviewer_role", "未单独记录"),
        "INTERVIEW_FORMAT": payload.get("interview_format", payload["interview_round"]),
        "STYLE_MODIFIER": payload.get("style_modifier", "常规"),
        "INTERVIEW_LANGUAGE": payload["interview_language"],
        "RECOMMENDATION": recommendation,
        "GENERATION_TIMESTAMP": generated_at,
        "INTERVIEWER_STYLE": payload["interviewer_style"],
        "PRESSURE_VALUE": payload["pressure_value"],
        "SCOPE_CONTROL": payload["scope_control"],
        "FOCUS_AREAS": payload.get("focus_areas", "未提供"),
        "SPECIAL_SECTIONS": payload.get("special_sections", "无"),
        "QUESTION_BANK": payload.get("question_bank", "未使用"),
        "AVOIDED_TOPICS": payload.get("avoided_topics", "无"),
        "RESUME_SUMMARY": payload["resume_summary"],
        "JD_SUMMARY": payload.get("jd_summary", "未提供"),
        "MATERIALS_NOTE": payload.get("materials_note", "未使用"),
        "COMPLETION_STATUS": status_labels[payload["completion_status"]],
        "TOTAL_SCORE": total_score_text,
        "SCORE_GRADE": total_style["grade"],
        "SCORE_BG_CLASS": total_style["bg_class"],
        "SCORED_WEIGHT": format_percentage(payload["scored_weight"]),
        "SCORE_COVERAGE": payload["score_coverage_note"],
        "COVERED_TOPICS": covered_topics,
        "RECOMMENDATION_CLASS": recommendation_style["recommendation_class"],
        "RECOMMENDATION_LABEL": recommendation_style["recommendation_label"],
        "RECOMMENDATION_REASON": payload["recommendation_reason"],
        "NEXT_ROUND_FOCUS": payload["next_round_focus"],
    }


def render_report(template, payload):
    validate_payload(payload)
    topics = payload["topics"]

    base_context = build_base_context(payload)
    report = template

    opening = payload.get("opening")
    report = replace_optional_block(
        report,
        "opening",
        None
        if not opening
        else {
            "OPENING_TITLE": opening.get("title", "自我介绍"),
            "OPENING_QUESTION": opening["question"],
            "OPENING_ANSWER": opening["answer"],
        },
    )

    report = replace_repeat_block(report, "topic_nav", topics, render_topic_nav_block)
    report = replace_repeat_block(report, "topic", topics, render_topic_block)
    report = replace_optional_block(
        report,
        "empty_process",
        {"EMPTY_PROCESS_MESSAGE": "本轮在取得有效回答前结束，没有可展示的正式问答。"}
        if not topics and not opening
        else None,
    )

    closing = payload.get("closing")
    report = replace_optional_block(
        report,
        "closing",
        None
        if not closing
        else {
            "CLOSING_TITLE": closing.get("title", "候选人提问"),
            "CLOSING_QUESTION": closing["question"],
            "CLOSING_ANSWER": closing["answer"],
        },
    )

    report = replace_repeat_block(
        report,
        "dimension",
        payload["dimensions"],
        lambda block, item, _index: render_placeholders(block, get_dimension_context(item)),
    )
    report = replace_repeat_block(
        report,
        "strength",
        payload.get("strengths") or ["未记录"],
        lambda block, item, index: render_simple_list_block(
            block, item, index, "STRENGTH_ITEM"
        ),
    )
    report = replace_repeat_block(
        report,
        "issue",
        normalize_issues(payload),
        render_issue_block,
    )
    report = replace_repeat_block(
        report,
        "action_item",
        normalize_action_items(payload),
        render_action_item_block,
    )
    knowledge_corrections = get_knowledge_corrections(payload)
    report = replace_repeat_block(
        report,
        "knowledge_correction",
        knowledge_corrections,
        render_knowledge_correction_block,
    )
    knowledge_context = (
        {"KNOWLEDGE_SUMMARY": get_knowledge_summary(knowledge_corrections)}
        if knowledge_corrections
        else None
    )
    report = replace_optional_block(report, "knowledge_nav", knowledge_context)
    report = replace_optional_block(report, "knowledge_section", knowledge_context)

    report = render_placeholders(report, base_context)
    if "{{" in report or "}}" in report:
        raise ValueError("Report still contains unresolved placeholders.")

    return report


def main():
    args = parse_args()
    payload = load_json(args.input)
    template = Path(args.template).read_text(encoding="utf-8")
    report = render_report(template, payload)

    output_path = resolve_output_path(args, payload)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report, encoding="utf-8")
    print(str(output_path))


if __name__ == "__main__":
    main()
