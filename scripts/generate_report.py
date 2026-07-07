#!/usr/bin/env python3

import argparse
import html
import json
import re
from datetime import datetime
from pathlib import Path


TEMPLATE_PATH = Path(__file__).with_name("report-template.html")

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
        "badge_class": "badge-strong",
        "recommendation_class": "rec-strong",
    },
    "建议": {
        "badge_class": "badge-yes",
        "recommendation_class": "rec-yes",
    },
    "待定": {
        "badge_class": "badge-pending",
        "recommendation_class": "rec-pending",
    },
    "不建议": {
        "badge_class": "badge-no",
        "recommendation_class": "rec-no",
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


def sanitize_filename_part(value):
    sanitized = re.sub(r'[\\/:*?"<>|]+', "-", stringify(value))
    sanitized = re.sub(r"\s+", "-", sanitized).strip("-")
    return sanitized or "untitled"


def resolve_output_path(args, payload):
    if args.output:
        return Path(args.output)

    output_dir = Path(args.output_dir)
    filename = "{date}-{position}-{round}.html".format(
        date=sanitize_filename_part(payload["interview_date"]),
        position=sanitize_filename_part(payload["target_position"]),
        round=sanitize_filename_part(payload["interview_round"]),
    )
    return output_dir / filename


def build_base_context(payload):
    recommendation = payload["recommendation"]
    if recommendation not in RECOMMENDATION_STYLES:
        raise ValueError(f"Unsupported recommendation: {recommendation}")

    total_score = int(payload["total_score"])
    total_style = get_score_style(total_score)
    recommendation_style = RECOMMENDATION_STYLES[recommendation]
    covered_topics = payload.get("covered_topics") or [
        topic.get("title", "未命名主题") for topic in payload.get("topics", [])
    ]

    generated_at = payload.get("generated_at")
    if not generated_at:
        generated_at = datetime.now().astimezone().isoformat(sep=" ", timespec="seconds")

    return {
        "TARGET_POSITION": payload["target_position"],
        "INTERVIEW_ROUND": payload["interview_round"],
        "INTERVIEW_DATE": payload["interview_date"],
        "CANDIDATE_TYPE": payload["candidate_type"],
        "INTERVIEW_LANGUAGE": payload["interview_language"],
        "RECOMMENDATION": recommendation,
        "RECOMMENDATION_BADGE_CLASS": recommendation_style["badge_class"],
        "GENERATION_TIMESTAMP": generated_at,
        "INTERVIEWER_STYLE": payload["interviewer_style"],
        "PRESSURE_VALUE": payload["pressure_value"],
        "SCOPE_CONTROL": payload["scope_control"],
        "FOCUS_AREAS": payload.get("focus_areas", "未提供"),
        "SPECIAL_SECTIONS": payload.get("special_sections", "无"),
        "FEEDBACK_MODE": payload["feedback_mode"],
        "QUESTION_BANK": payload.get("question_bank", "未使用"),
        "AVOIDED_TOPICS": payload.get("avoided_topics", "无"),
        "RESUME_SUMMARY": payload["resume_summary"],
        "JD_SUMMARY": payload.get("jd_summary", "未提供"),
        "MATERIALS_NOTE": payload.get("materials_note", "未使用"),
        "TOTAL_SCORE": total_score,
        "SCORE_GRADE": total_style["grade"],
        "SCORE_BG_CLASS": total_style["bg_class"],
        "SCORE_COVERAGE": payload["score_coverage"],
        "COVERED_TOPICS": covered_topics,
        "RECOMMENDATION_CLASS": recommendation_style["recommendation_class"],
        "RECOMMENDATION_REASON": payload["recommendation_reason"],
        "NEXT_ROUND_FOCUS": payload["next_round_focus"],
    }


def render_report(template, payload):
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
            "feedback_mode",
            "resume_summary",
            "total_score",
            "score_coverage",
            "dimensions",
            "recommendation",
            "recommendation_reason",
            "next_round_focus",
        ],
    )

    topics = payload.get("topics") or []
    if not topics:
        raise ValueError("At least one topic is required.")

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
        "risk",
        payload.get("risks") or ["未记录"],
        lambda block, item, index: render_simple_list_block(block, item, index, "RISK_ITEM"),
    )
    report = replace_repeat_block(
        report,
        "gap",
        payload.get("gaps") or ["未记录"],
        lambda block, item, index: render_simple_list_block(
            block, item, index, "CONTRADICTION_ITEM"
        ),
    )
    report = replace_repeat_block(
        report,
        "improvement",
        payload.get("improvements") or ["未记录"],
        lambda block, item, index: render_simple_list_block(
            block, item, index, "IMPROVEMENT_ITEM"
        ),
    )
    report = replace_repeat_block(
        report,
        "better_answer",
        payload.get("better_answers") or [{"question": "未记录", "approach": "未记录"}],
        lambda block, item, _index: render_placeholders(
            block,
            {
                "ORIGINAL_QUESTION": item["question"],
                "BETTER_APPROACH": item["approach"],
            },
        ),
    )

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
