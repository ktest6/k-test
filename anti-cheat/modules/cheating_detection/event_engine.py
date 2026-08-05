"""
event_engine.py

Rule Engine의 판단 결과를 외부 응답용 이벤트로 변환하는 모듈.

- 현재 프레임의 이벤트 요약 생성
- 적용된 Rule을 외부 이벤트 배열로 변환
- Rule Engine의 최종 위험도와 Decision 유지
"""

from datetime import datetime
from typing import Any

from modules.cheating_detection.rule_engine import (
    DECISION_CREATE_CLIP,
    DECISION_NONE,
    SEVERITY_NORMAL,
)


def create_events(
    applied_rules: list[Any],
) -> list[dict[str, Any]]:
    """적용된 Rule을 외부 응답용 이벤트 배열로 변환한다."""

    events: list[dict[str, Any]] = []

    for applied_rule in applied_rules:
        if not isinstance(applied_rule, dict):
            continue

        event_type = applied_rule.get("event_type")

        if not isinstance(event_type, str) or not event_type.strip():
            continue

        details = applied_rule.get("details", {})

        if not isinstance(details, dict):
            details = {}

        events.append(
            {
                "event_type": event_type,
                "details": details,
            }
        )

    return events


def transform_rule_result(
    rule_result: dict[str, Any] | None,
) -> dict[str, Any]:
    """Rule Engine 결과를 이벤트 요약과 이벤트 배열로 변환한다."""

    if not isinstance(rule_result, dict):
        rule_result = {}

    applied_rules = rule_result.get("applied_rules", [])

    if not isinstance(applied_rules, list):
        applied_rules = []

    events = create_events(applied_rules)

    severity = rule_result.get(
        "severity",
        SEVERITY_NORMAL,
    )
    decision = rule_result.get(
        "decision",
        DECISION_NONE,
    )

    if not isinstance(severity, str):
        severity = SEVERITY_NORMAL

    if not isinstance(decision, str):
        decision = DECISION_NONE

    return {
        "event_summary": {
            "event_detected": len(events) > 0,
            "event_count": len(events),
            "severity": severity,
            "decision": decision,
            "create_clip": decision == DECISION_CREATE_CLIP,
        },
        "events": events,
    }


def process_event(
    exam_id: str,
    examinee_id: str,
    request_id: str,
    captured_at: datetime,
    elapsed_ms: int,
    capture_sequence: int,
    rule_result: dict[str, Any],
) -> dict[str, Any]:
    """기존 호출 형식을 유지하며 Rule 결과를 외부 이벤트로 변환한다."""

    return transform_rule_result(
        rule_result=rule_result,
    )
