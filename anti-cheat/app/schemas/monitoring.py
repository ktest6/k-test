"""
monitoring.py

모니터링 API 응답 데이터 구조를 정의한다.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class IdentityMonitorResult(BaseModel):
    """중간 동일인 검사 결과."""

    verified: bool
    similarity: float
    similarity_threshold: float
    matched_face_count: int
    event_type: str
    message: str


class FaceMonitorResult(BaseModel):
    """얼굴 감지 및 인원 판정 결과."""

    face_count: int
    face_details: list[dict[str, Any]]
    event_type: str
    message: str


class AppliedRule(BaseModel):
    """Rule Engine에서 적용된 개별 규칙."""

    rule_id: str
    event_type: str
    severity: str
    decision: str
    message: str
    details: dict[str, Any]


class RuleResult(BaseModel):
    """Rule Engine의 최종 판단 결과."""

    applied_rules: list[AppliedRule]
    rule_count: int
    severity: str
    decision: str
    create_clip: bool


class MonitoringEvent(BaseModel):
    """Event Engine에서 생성한 이벤트."""

    event_id: str
    exam_id: str
    examinee_id: str
    request_id: str

    occurred_at: datetime
    elapsed_ms: int
    capture_sequence: int

    severity: str
    decision: str
    create_clip: bool

    clip_start_ms: int | None = None
    clip_end_ms: int | None = None

    rule_count: int
    applied_rules: list[AppliedRule]


class EventResult(BaseModel):
    """이벤트 생성 여부와 생성 결과."""

    event_created: bool
    event: MonitoringEvent | None = None

    # 현재 개발 단계의 로컬 JSON 저장 경로
    event_file_path: str | None = None


class MonitoringResponse(BaseModel):
    """모니터링 API의 최종 응답."""

    exam_id: str
    examinee_id: str
    request_id: str

    captured_at: datetime
    elapsed_ms: int
    capture_sequence: int

    face_monitor: FaceMonitorResult

    identity_check_requested: bool
    identity_check_executed: bool
    identity_monitor: IdentityMonitorResult | None = None

    rule_result: RuleResult
    event_result: EventResult