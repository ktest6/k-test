"""
event_engine.py

Rule Engine의 판단 결과를 시험 이벤트로 생성하고 저장하는 모듈.

- 이벤트 ID 생성
- 실제 웹캠 이미지 촬영 시각을 이벤트 발생 시각으로 사용
- 시험 경과 시간을 이벤트에 포함
- 영상 클립 생성이 필요한 경우 클립 시간 범위 계산
- Rule Engine 결과를 이벤트 형식으로 변환
- 시험별 로그 폴더에 이벤트 JSON 저장

※ 시험 로그 폴더는 본인 인증 성공 시 미리 생성되어 있다고 가정한다.
※ AI 서버는 실제 영상 클립을 생성하지 않는다.
※ clip_start_ms와 clip_end_ms만 계산하여 반환한다.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from modules.common.exceptions import MonitoringError
from modules.cheating_detection.rule_engine import (
    DECISION_CREATE_CLIP,
    DECISION_NONE,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]

LOG_ROOT_DIR = PROJECT_ROOT / "data" / "logs"

CLIP_BEFORE_MS = 5000
CLIP_AFTER_MS = 5000


def generate_event_id() -> str:
    """고유한 이벤트 ID를 생성한다."""

    unique_id = uuid4().hex[:8]

    return f"event_{unique_id}"


def calculate_clip_range(
    elapsed_ms: int,
) -> tuple[int, int]:
    """
    이벤트 발생 시점을 기준으로 전후 5초의 클립 범위를 계산한다.

    시험 시작 후 5초 이내에 이벤트가 발생한 경우
    clip_start_ms는 0으로 보정한다.
    """

    clip_start_ms = max(
        0,
        elapsed_ms - CLIP_BEFORE_MS,
    )

    clip_end_ms = elapsed_ms + CLIP_AFTER_MS

    return clip_start_ms, clip_end_ms


def create_event(
    exam_id: str,
    examinee_id: str,
    request_id: str,
    captured_at: datetime,
    elapsed_ms: int,
    capture_sequence: int,
    rule_result: dict[str, Any],
) -> dict[str, Any] | None:
    """Rule Engine 결과를 이벤트 데이터로 변환한다."""

    decision = rule_result.get(
        "decision",
        DECISION_NONE,
    )

    applied_rules = rule_result.get(
        "applied_rules",
        [],
    )

    if decision == DECISION_NONE:
        return None

    event_id = generate_event_id()

    create_clip = decision == DECISION_CREATE_CLIP

    clip_start_ms = None
    clip_end_ms = None

    if create_clip:
        clip_start_ms, clip_end_ms = calculate_clip_range(
            elapsed_ms=elapsed_ms,
        )

    return {
        "event_id": event_id,
        "exam_id": exam_id,
        "examinee_id": examinee_id,
        "request_id": request_id,
        "occurred_at": captured_at.isoformat(),
        "elapsed_ms": elapsed_ms,
        "capture_sequence": capture_sequence,
        "severity": rule_result.get(
            "severity",
            "NORMAL",
        ),
        "decision": decision,
        "create_clip": create_clip,
        "clip_start_ms": clip_start_ms,
        "clip_end_ms": clip_end_ms,
        "rule_count": len(applied_rules),
        "applied_rules": applied_rules,
    }


def save_event(
    event: dict[str, Any],
) -> Path:
    """생성된 이벤트를 시험 로그 폴더에 JSON 파일로 저장한다."""

    exam_id = event.get("exam_id")
    event_id = event.get("event_id")

    if not exam_id:
        raise MonitoringError(
            "이벤트에 exam_id가 없습니다."
        )

    if not event_id:
        raise MonitoringError(
            "이벤트에 event_id가 없습니다."
        )

    exam_log_dir = LOG_ROOT_DIR / exam_id

    if not exam_log_dir.exists():
        raise MonitoringError(
            (
                f"시험 로그 폴더가 존재하지 않습니다: "
                f"{exam_log_dir}"
            )
        )

    event_file_path = exam_log_dir / f"{event_id}.json"

    try:
        with event_file_path.open(
            mode="w",
            encoding="utf-8",
        ) as file:
            json.dump(
                event,
                file,
                ensure_ascii=False,
                indent=2,
            )

    except OSError as error:
        raise MonitoringError(
            "이벤트 로그 저장에 실패했습니다."
        ) from error

    return event_file_path


def process_event(
    exam_id: str,
    examinee_id: str,
    request_id: str,
    captured_at: datetime,
    elapsed_ms: int,
    capture_sequence: int,
    rule_result: dict[str, Any],
) -> dict[str, Any]:
    """Rule Engine 결과를 이벤트로 생성하고 저장한다."""

    event = create_event(
        exam_id=exam_id,
        examinee_id=examinee_id,
        request_id=request_id,
        captured_at=captured_at,
        elapsed_ms=elapsed_ms,
        capture_sequence=capture_sequence,
        rule_result=rule_result,
    )

    if event is None:
        return {
            "event_created": False,
            "event": None,
            "event_file_path": None,
        }

    event_file_path = save_event(
        event,
    )

    return {
        "event_created": True,
        "event": event,
        "event_file_path": str(event_file_path),
    }