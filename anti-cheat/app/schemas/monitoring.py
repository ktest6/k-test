"""
monitoring.py

모니터링 API 응답 데이터 구조를 정의한다.
"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


FaceEventType = Literal[
    "FACE_NORMAL",
    "FACE_OUT_OF_FRAME",
    "MULTIPLE_FACES",
]

GazeEventType = Literal[
    "GAZE_NORMAL",
    "GAZE_AWAY",
    "GAZE_UNCERTAIN",
    "GAZE_NOT_ANALYZED",
]

GazeDirection = Literal[
    "CENTER",
    "LEFT",
    "RIGHT",
    "UP",
    "DOWN",
    "UP_LEFT",
    "UP_RIGHT",
    "DOWN_LEFT",
    "DOWN_RIGHT",
    "UNKNOWN",
]

HeadPoseLevel = Literal["NORMAL", "SLIGHT", "LARGE"]

EventSeverity = Literal[
    "NORMAL",
    "LOW",
    "MEDIUM",
    "HIGH",
]

EventDecision = Literal[
    "NONE",
    "RECORD_EVENT",
    "CREATE_CLIP",
]


class IdentityMonitorResult(BaseModel):
    """중간 동일인 검사 결과."""

    verified: bool
    similarity: float
    similarity_threshold: float
    matched_face_count: int
    event_type: str
    message: str


class FaceMonitorResponse(BaseModel):
    """외부 응답용 얼굴 감지 및 인원 판정 결과."""

    face_count: int = Field(ge=0)
    event_type: FaceEventType
    message: str


class EyeDirectionResponse(BaseModel):
    """눈 시선 방향 분석 결과."""

    yaw: float | None
    pitch: float | None
    confidence: float | None


class RelativeEyeDirectionResponse(BaseModel):
    """Calibration 기준 상대 시선 방향 값."""

    yaw: float | None
    pitch: float | None


class HeadPoseResponse(BaseModel):
    """고개 방향 분석 결과."""

    yaw: float | None
    pitch: float | None
    roll: float | None


class GazeStateResponse(BaseModel):
    """다음 프레임 계산에 다시 사용할 연속 시선 상태."""

    consecutive_away_count: int = Field(ge=0)
    consecutive_eye_away_count: int = Field(default=0, ge=0)
    consecutive_head_away_count: int = Field(default=0, ge=0)
    consecutive_head_slight_count: int = Field(default=0, ge=0)
    consecutive_head_large_count: int = Field(default=0, ge=0)
    consecutive_eye_only_count: int = Field(ge=0)
    consecutive_head_only_count: int = Field(ge=0)
    consecutive_eye_and_head_count: int = Field(ge=0)
    away_started_elapsed_ms: int | None = Field(default=None, ge=0)
    away_duration_ms: int = Field(ge=0)
    last_direction: GazeDirection | None
    last_capture_sequence: int | None = Field(default=None, ge=1)
    last_elapsed_ms: int | None = Field(default=None, ge=0)
    persistent_gaze_away: bool
    sequence_continuous: bool
    elapsed_time_valid: bool
    state_continuous: bool


class PreviousGazeState(GazeStateResponse):
    """백엔드가 저장했다가 다음 분석 요청에 전달하는 시선 상태."""


class GazeMonitorResponse(BaseModel):
    """시선 및 고개 방향 모니터링 결과."""

    event_type: GazeEventType
    direction: GazeDirection
    eye_direction_reliable: bool
    eye_direction: EyeDirectionResponse
    calibration_applied: bool
    relative_eye_direction: RelativeEyeDirectionResponse
    head_pose: HeadPoseResponse
    relative_head_pose: HeadPoseResponse
    head_pose_level: HeadPoseLevel
    eye_gaze_away: bool
    head_pose_away: bool
    message: str
    state: GazeStateResponse


class GazeCalibrationResponse(BaseModel):
    """응시자별 시선 Calibration 생성 결과."""

    exam_id: str
    examinee_id: str
    calibrated: bool
    sample_count: int = Field(ge=1)
    eye_yaw_center: float
    eye_pitch_center: float
    head_yaw_center: float
    head_pitch_center: float


class EventSummaryResponse(BaseModel):
    """현재 프레임에서 탐지된 이벤트 요약."""

    event_detected: bool
    event_count: int = Field(ge=0)
    severity: EventSeverity
    decision: EventDecision
    create_clip: bool


class MonitoringEventResponse(BaseModel):
    """외부 응답용 개별 모니터링 이벤트."""

    rule_id: str
    event_type: str
    severity: EventSeverity
    decision: EventDecision
    message: str
    details: dict[str, Any] = Field(
        default_factory=dict,
    )


class DetectedObjectResponse(BaseModel):
    """시험 중 탐지된 금지 객체."""

    object_type: Literal[
        "PHONE",
        "EARPHONE",
    ]
    label: str
    confidence: float


class ObjectMonitorResponse(BaseModel):
    """시험 중 금지 객체 탐지 결과."""

    detected_objects: list[DetectedObjectResponse]


class MonitoringResponse(BaseModel):
    """모니터링 API의 최종 응답."""

    exam_id: str
    examinee_id: str
    request_id: str

    captured_at: datetime
    elapsed_ms: int = Field(ge=0)
    capture_sequence: int = Field(ge=1)

    face_monitor: FaceMonitorResponse
    gaze_monitor: GazeMonitorResponse
    object_monitor: ObjectMonitorResponse

    identity_check_requested: bool
    identity_check_executed: bool
    identity_monitor: IdentityMonitorResult | None = None

    event_summary: EventSummaryResponse
    events: list[MonitoringEventResponse] = Field(
        default_factory=list,
    )
