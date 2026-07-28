"""
rule_engine.py

시험 중 각 모니터링 결과를 규칙에 따라 평가하는 모듈.

- 얼굴 탐지 결과 평가
- 동일인 비교 결과 평가
- 객체 탐지 결과 평가
- 여러 탐지 결과의 조합 평가
- 발생한 규칙 중 최종 위험도와 Decision 결정

※ 이벤트 ID, 발생 시각, 클립 이름, 로그 저장은 event_engine.py에서 담당한다.
"""

from typing import Any

from modules.cheating_detection.face_monitor import (
    EVENT_FACE_NORMAL,
    EVENT_FACE_OUT_OF_FRAME,
    EVENT_MULTIPLE_FACES,
)
from modules.cheating_detection.identity_monitor import (
    EVENT_IDENTITY_MATCH,
    EVENT_IDENTITY_MISMATCH,
)


# 위험도
SEVERITY_NORMAL = "NORMAL"
SEVERITY_LOW = "LOW"
SEVERITY_MEDIUM = "MEDIUM"
SEVERITY_HIGH = "HIGH"


# 최종 처리 방식
DECISION_NONE = "NONE"
DECISION_RECORD_EVENT = "RECORD_EVENT"
DECISION_CREATE_CLIP = "CREATE_CLIP"


# 위험도 비교 우선순위
SEVERITY_PRIORITY = {
    SEVERITY_NORMAL: 0,
    SEVERITY_LOW: 1,
    SEVERITY_MEDIUM: 2,
    SEVERITY_HIGH: 3,
}

# 규칙 결과 형식 동일
def create_rule_result(
    rule_id: str,
    event_type: str,
    severity: str,
    decision: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """규칙 평가 결과를 공통 형식으로 생성한다."""

    return {
        "rule_id": rule_id,
        "event_type": event_type,
        "severity": severity,
        "decision": decision,
        "message": message,
        "details": details or {},
    }

# 화면 이탈, 다중 인원 평가
def evaluate_face_rules(
    face_result: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """얼굴 탐지 결과에 해당하는 규칙을 평가한다."""

    applied_rules: list[dict[str, Any]] = []

    if face_result is None:
        return applied_rules

    event_type = face_result.get(
        "event_type",
        EVENT_FACE_NORMAL,
    )

    if event_type == EVENT_FACE_OUT_OF_FRAME:
        applied_rules.append(
            create_rule_result(
                rule_id="RULE_FACE_OUT_OF_FRAME",
                event_type=EVENT_FACE_OUT_OF_FRAME,
                severity=SEVERITY_MEDIUM,
                decision=DECISION_RECORD_EVENT,
                message="응시자의 얼굴이 화면에서 확인되지 않았습니다.",
                details={
                    "face_count": face_result.get("face_count", 0),
                },
            )
        )

    elif event_type == EVENT_MULTIPLE_FACES:
        applied_rules.append(
            create_rule_result(
                rule_id="RULE_MULTIPLE_FACES",
                event_type=EVENT_MULTIPLE_FACES,
                severity=SEVERITY_HIGH,
                decision=DECISION_CREATE_CLIP,
                message="시험 화면에서 여러 명의 얼굴이 확인되었습니다.",
                details={
                    "face_count": face_result.get("face_count", 0),
                },
            )
        )

    return applied_rules


# 동일인 불일치 평가
def evaluate_identity_rules(
    identity_result: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """동일인 비교 결과에 해당하는 규칙을 평가한다."""

    applied_rules: list[dict[str, Any]] = []

    if identity_result is None:
        return applied_rules

    event_type = identity_result.get(
        "event_type",
        EVENT_IDENTITY_MATCH,
    )

    if event_type == EVENT_IDENTITY_MISMATCH:
        applied_rules.append(
            create_rule_result(
                rule_id="RULE_IDENTITY_MISMATCH",
                event_type=EVENT_IDENTITY_MISMATCH,
                severity=SEVERITY_HIGH,
                decision=DECISION_CREATE_CLIP,
                message=(
                    "시험 시작 시 등록한 사용자와 "
                    "현재 사용자가 일치하지 않습니다."
                ),
                details={
                    "verified": identity_result.get(
                        "verified",
                        False,
                    ),
                    "similarity": identity_result.get(
                        "similarity",
                        0.0,
                    ),
                    "similarity_threshold": identity_result.get(
                        "similarity_threshold",
                        0.0,
                    ),
                    "matched_face_count": identity_result.get(
                        "matched_face_count",
                        0,
                    ),
                },
            )
        )

    return applied_rules


# 휴대폰, 이어폰 등의 객체 평가
def evaluate_object_rules(
    object_result: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """객체 탐지 결과에 해당하는 규칙을 평가한다."""

    applied_rules: list[dict[str, Any]] = []

    if object_result is None:
        return applied_rules

    detected_objects = object_result.get(
        "detected_objects",
        [],
    )

    for detected_object in detected_objects:
        label = detected_object.get("label")
        confidence = detected_object.get("confidence", 0.0)

        if label == "Cell Phone":
            applied_rules.append(
                create_rule_result(
                    rule_id="RULE_PHONE_DETECTED",
                    event_type="PHONE_DETECTED",
                    severity=SEVERITY_HIGH,
                    decision=DECISION_CREATE_CLIP,
                    message="시험 화면에서 휴대폰이 탐지되었습니다.",
                    details={
                        "label": label,
                        "confidence": confidence,
                    },
                )
            )

        elif label == "Earphones":
            applied_rules.append(
                create_rule_result(
                    rule_id="RULE_EARPHONE_DETECTED",
                    event_type="EARPHONE_DETECTED",
                    severity=SEVERITY_MEDIUM,
                    decision=DECISION_RECORD_EVENT,
                    message="시험 화면에서 이어폰이 탐지되었습니다.",
                    details={
                        "label": label,
                        "confidence": confidence,
                    },
                )
            )

    return applied_rules


# 여러 탐지 결과가 함께 발생한 경우 평가
def evaluate_combination_rules(
    monitoring_results: dict[str, Any],
) -> list[dict[str, Any]]:
    """여러 탐지 결과를 조합한 규칙을 평가한다."""

    applied_rules: list[dict[str, Any]] = []

    head_pose_result = monitoring_results.get(
        "head_pose",
    )

    object_result = monitoring_results.get(
        "object_monitor",
    )

    head_event_type = None

    if head_pose_result is not None:
        head_event_type = head_pose_result.get(
            "event_type",
        )

    detected_labels: set[str] = set()

    if object_result is not None:
        detected_objects = object_result.get(
            "detected_objects",
            [],
        )

        detected_labels = {
            detected_object.get("label")
            for detected_object in detected_objects
            if detected_object.get("label") is not None
        }

    if (
        head_event_type == "HEAD_DOWN"
        and "Cell Phone" in detected_labels
    ):
        applied_rules.append(
            create_rule_result(
                rule_id="RULE_SUSPICIOUS_PHONE_USAGE",
                event_type="SUSPICIOUS_PHONE_USAGE",
                severity=SEVERITY_HIGH,
                decision=DECISION_CREATE_CLIP,
                message=(
                    "응시자가 고개를 아래로 향한 상태에서 "
                    "휴대폰이 탐지되었습니다."
                ),
                details={
                    "head_event_type": head_event_type,
                    "detected_label": "Cell Phone",
                },
            )
        )

    return applied_rules


# 적용된 규칙 중 가장 최고 위험도 선택
def get_highest_severity(
    applied_rules: list[dict[str, Any]],
) -> str:
    """적용된 규칙 중 가장 높은 위험도를 반환한다."""

    if not applied_rules:
        return SEVERITY_NORMAL

    return max(
        (
            rule["severity"]
            for rule in applied_rules
        ),
        key=lambda severity: SEVERITY_PRIORITY.get(
            severity,
            0,
        ),
    )


# 적용된 규칙 중 가장 높은 수준의 Decision 선택
def get_final_decision(
    applied_rules: list[dict[str, Any]],
) -> str:
    """적용된 규칙 중 가장 높은 수준의 Decision을 반환한다."""

    decisions = {
        rule["decision"]
        for rule in applied_rules
    }

    if DECISION_CREATE_CLIP in decisions:
        return DECISION_CREATE_CLIP

    if DECISION_RECORD_EVENT in decisions:
        return DECISION_RECORD_EVENT

    return DECISION_NONE


# 위 함수를 모두 호출하는 진입점
def evaluate_rules(
    monitoring_results: dict[str, Any],
) -> dict[str, Any]:
    """전체 모니터링 결과를 평가하여 최종 규칙 결과를 반환한다."""

    applied_rules: list[dict[str, Any]] = []

    face_result = monitoring_results.get(
        "face_monitor",
    )

    identity_result = monitoring_results.get(
        "identity_monitor",
    )

    object_result = monitoring_results.get(
        "object_monitor",
    )

    applied_rules.extend(
        evaluate_face_rules(
            face_result,
        )
    )

    applied_rules.extend(
        evaluate_identity_rules(
            identity_result,
        )
    )

    applied_rules.extend(
        evaluate_object_rules(
            object_result,
        )
    )

    applied_rules.extend(
        evaluate_combination_rules(
            monitoring_results,
        )
    )

    final_severity = get_highest_severity(
        applied_rules,
    )

    final_decision = get_final_decision(
        applied_rules,
    )

    return {
        "applied_rules": applied_rules,
        "rule_count": len(applied_rules),
        "severity": final_severity,
        "decision": final_decision,
        "create_clip": (
            final_decision == DECISION_CREATE_CLIP
        ),
    }