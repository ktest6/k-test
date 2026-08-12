"""
gaze_monitor.py

시험 중 응시자의 시선 및 고개 방향 분석 모듈.

- AWS Rekognition DetectFaces 응답에서 Head Pose 추출
- Eye Direction 정보 추출
- 시선 방향과 고개 방향을 기준으로 화면 이탈 여부 판단
- Eye Direction 신뢰도가 낮은 경우 분석 불확실 상태 반환

※ 이 모듈은 단일 프레임의 시선 상태만 판단한다.
※ 연속 시선 이탈 횟수 및 지속 시간 판단은 별도 상태 관리 모듈에서 수행한다.
"""

from math import isfinite
from typing import Any


EVENT_GAZE_NORMAL = "GAZE_NORMAL"
EVENT_GAZE_AWAY = "GAZE_AWAY"
EVENT_GAZE_UNCERTAIN = "GAZE_UNCERTAIN"
EVENT_GAZE_NOT_ANALYZED = "GAZE_NOT_ANALYZED"

DIRECTION_CENTER = "CENTER"
DIRECTION_LEFT = "LEFT"
DIRECTION_RIGHT = "RIGHT"
DIRECTION_UP = "UP"
DIRECTION_DOWN = "DOWN"
DIRECTION_UP_LEFT = "UP_LEFT"
DIRECTION_UP_RIGHT = "UP_RIGHT"
DIRECTION_DOWN_LEFT = "DOWN_LEFT"
DIRECTION_DOWN_RIGHT = "DOWN_RIGHT"
DIRECTION_UNKNOWN = "UNKNOWN"


def to_float(
    value: Any,
    default: float = 0.0,
) -> float:
    """값을 float로 변환하고 실패하면 기본값을 반환한다."""

    try:
        return float(value)

    except (TypeError, ValueError):
        return default


def extract_eye_direction(
    face_detail: dict[str, Any],
) -> dict[str, float]:
    """얼굴 상세 정보에서 Eye Direction 값을 추출한다."""

    eye_direction = face_detail.get(
        "EyeDirection",
        {},
    )

    if not isinstance(eye_direction, dict):
        return {
            "yaw": 0.0,
            "pitch": 0.0,
            "confidence": 0.0,
        }

    return {
        "yaw": to_float(
            eye_direction.get(
                "Yaw",
                0.0,
            )
        ),
        "pitch": to_float(
            eye_direction.get(
                "Pitch",
                0.0,
            )
        ),
        "confidence": to_float(
            eye_direction.get(
                "Confidence",
                0.0,
            )
        ),
    }


def extract_head_pose(
    face_detail: dict[str, Any],
) -> dict[str, float]:
    """얼굴 상세 정보에서 Head Pose 값을 추출한다."""

    head_pose = face_detail.get(
        "Pose",
        {},
    )

    if not isinstance(head_pose, dict):
        return {
            "yaw": 0.0,
            "pitch": 0.0,
            "roll": 0.0,
        }

    return {
        "yaw": to_float(
            head_pose.get(
                "Yaw",
                0.0,
            )
        ),
        "pitch": to_float(
            head_pose.get(
                "Pitch",
                0.0,
            )
        ),
        "roll": to_float(
            head_pose.get(
                "Roll",
                0.0,
            )
        ),
    }


def determine_gaze_direction(
    eye_yaw: float,
    eye_pitch: float,
    eye_yaw_threshold: float,
    eye_pitch_threshold: float,
) -> str:
    """Eye Direction 값을 기준으로 시선 방향을 판단한다."""

    horizontal_direction = DIRECTION_CENTER
    vertical_direction = DIRECTION_CENTER

    if eye_yaw <= -eye_yaw_threshold:
        horizontal_direction = DIRECTION_LEFT

    elif eye_yaw >= eye_yaw_threshold:
        horizontal_direction = DIRECTION_RIGHT

    if eye_pitch <= -eye_pitch_threshold:
        vertical_direction = DIRECTION_DOWN

    elif eye_pitch >= eye_pitch_threshold:
        vertical_direction = DIRECTION_UP

    if (
        horizontal_direction == DIRECTION_CENTER
        and vertical_direction == DIRECTION_CENTER
    ):
        return DIRECTION_CENTER

    if (
        horizontal_direction == DIRECTION_LEFT
        and vertical_direction == DIRECTION_UP
    ):
        return DIRECTION_UP_LEFT

    if (
        horizontal_direction == DIRECTION_RIGHT
        and vertical_direction == DIRECTION_UP
    ):
        return DIRECTION_UP_RIGHT

    if (
        horizontal_direction == DIRECTION_LEFT
        and vertical_direction == DIRECTION_DOWN
    ):
        return DIRECTION_DOWN_LEFT

    if (
        horizontal_direction == DIRECTION_RIGHT
        and vertical_direction == DIRECTION_DOWN
    ):
        return DIRECTION_DOWN_RIGHT

    if horizontal_direction != DIRECTION_CENTER:
        return horizontal_direction

    if vertical_direction != DIRECTION_CENTER:
        return vertical_direction

    return DIRECTION_UNKNOWN


def is_head_pose_away(
    head_pose: dict[str, float],
    head_yaw_threshold: float,
    head_pitch_threshold: float,
) -> bool:
    """고개 방향이 정상 범위를 벗어났는지 판단한다."""

    head_yaw = head_pose.get(
        "yaw",
        0.0,
    )

    head_pitch = head_pose.get(
        "pitch",
        0.0,
    )

    return (
        abs(head_yaw) >= head_yaw_threshold
        or abs(head_pitch) >= head_pitch_threshold
    )


def is_valid_gaze_calibration(
    gaze_calibration: dict[str, Any] | None,
) -> bool:
    """Eye Direction 보정에 필요한 Calibration 값을 검증한다."""

    if not isinstance(gaze_calibration, dict):
        return False

    eye_yaw_center = gaze_calibration.get("eye_yaw_center")
    eye_pitch_center = gaze_calibration.get("eye_pitch_center")

    for center_value in (eye_yaw_center, eye_pitch_center):
        if (
            not isinstance(center_value, (int, float))
            or isinstance(center_value, bool)
            or not isfinite(center_value)
        ):
            return False

    return True


def calculate_relative_eye_direction(
    eye_direction: dict[str, float],
    gaze_calibration: dict[str, Any] | None,
) -> dict[str, float]:
    """화면 중앙 기준의 Eye Direction을 계산한다.

    유효한 Calibration이 없으면 기존 절대 Eye Direction 값을
    그대로 반환해 동일한 판정 흐름에서 사용한다.
    """

    eye_yaw = eye_direction["yaw"]
    eye_pitch = eye_direction["pitch"]

    if not is_valid_gaze_calibration(gaze_calibration):
        return {
            "yaw": eye_yaw,
            "pitch": eye_pitch,
        }

    return {
        "yaw": eye_yaw - gaze_calibration["eye_yaw_center"],
        "pitch": eye_pitch - gaze_calibration["eye_pitch_center"],
    }


def create_not_analyzed_result(
    message: str,
) -> dict[str, Any]:
    """시선 분석을 수행할 수 없는 경우의 결과를 생성한다."""

    return {
        "event_type": EVENT_GAZE_NOT_ANALYZED,
        "direction": DIRECTION_UNKNOWN,
        "eye_direction_reliable": False,
        "eye_direction": {
            "yaw": None,
            "pitch": None,
            "confidence": None,
        },
        "calibration_applied": False,
        "relative_eye_direction": {
            "yaw": None,
            "pitch": None,
        },
        "head_pose": {
            "yaw": None,
            "pitch": None,
            "roll": None,
        },
        "eye_gaze_away": False,
        "head_pose_away": False,
        "message": message,
    }


def analyze_gaze_monitor(
    face_monitor_result: dict[str, Any],
    eye_yaw_threshold: float,
    eye_pitch_threshold: float,
    head_yaw_threshold: float,
    head_pitch_threshold: float,
    minimum_eye_confidence: float,
    gaze_calibration: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    얼굴 분석 결과를 바탕으로 시선 및 고개 방향을 판단한다.

    시선 분석은 현재 프레임에서 얼굴이 정확히 한 명일 때만 수행한다.

    Eye Direction의 Confidence가 기준값보다 낮으면
    시선 이탈 여부를 판단하지 않고 GAZE_UNCERTAIN을 반환한다.
    """

    face_count = face_monitor_result.get(
        "face_count",
        0,
    )

    face_details = face_monitor_result.get(
        "face_details",
        [],
    )

    if face_count != 1:
        return create_not_analyzed_result(
            message=(
                "얼굴이 정확히 한 명 감지되지 않아 "
                "시선 분석을 수행하지 않았습니다."
            ),
        )

    if not isinstance(face_details, list) or not face_details:
        return create_not_analyzed_result(
            message=(
                "얼굴 상세 정보가 없어 "
                "시선 분석을 수행하지 않았습니다."
            ),
        )

    face_detail = face_details[0]

    if not isinstance(face_detail, dict):
        return create_not_analyzed_result(
            message="얼굴 상세 정보 형식이 올바르지 않습니다.",
        )

    eye_direction = extract_eye_direction(
        face_detail=face_detail,
    )

    head_pose = extract_head_pose(
        face_detail=face_detail,
    )

    eye_confidence = eye_direction.get(
        "confidence",
        0.0,
    )

    if eye_confidence < minimum_eye_confidence:
        return {
            "event_type": EVENT_GAZE_UNCERTAIN,
            "direction": DIRECTION_UNKNOWN,
            "eye_direction_reliable": False,
            "eye_direction": eye_direction,
            "calibration_applied": False,
            "relative_eye_direction": {
                "yaw": None,
                "pitch": None,
            },
            "head_pose": head_pose,
            "eye_gaze_away": False,
            "head_pose_away": is_head_pose_away(
                head_pose=head_pose,
                head_yaw_threshold=head_yaw_threshold,
                head_pitch_threshold=head_pitch_threshold,
            ),
            "message": (
                "Eye Direction 신뢰도가 낮아 "
                "시선 방향을 판단할 수 없습니다."
            ),
        }

    calibration_applied = is_valid_gaze_calibration(
        gaze_calibration=gaze_calibration,
    )

    relative_eye_direction = calculate_relative_eye_direction(
        eye_direction=eye_direction,
        gaze_calibration=gaze_calibration,
    )

    direction = determine_gaze_direction(
        eye_yaw=relative_eye_direction["yaw"],
        eye_pitch=relative_eye_direction["pitch"],
        eye_yaw_threshold=eye_yaw_threshold,
        eye_pitch_threshold=eye_pitch_threshold,
    )

    eye_gaze_away = (
        direction != DIRECTION_CENTER
    )

    head_pose_away = is_head_pose_away(
        head_pose=head_pose,
        head_yaw_threshold=head_yaw_threshold,
        head_pitch_threshold=head_pitch_threshold,
    )

    gaze_away = (
        eye_gaze_away
        or head_pose_away
    )

    if gaze_away:
        event_type = EVENT_GAZE_AWAY
        message = (
            "응시자의 시선 또는 고개 방향이 "
            f"정상 범위를 벗어났습니다: {direction}"
        )

    else:
        event_type = EVENT_GAZE_NORMAL
        message = "응시자가 정상 범위를 바라보고 있습니다."

    return {
        "event_type": event_type,
        "direction": direction,
        "eye_direction_reliable": True,
        "eye_direction": eye_direction,
        "calibration_applied": calibration_applied,
        "relative_eye_direction": relative_eye_direction,
        "head_pose": head_pose,
        "eye_gaze_away": eye_gaze_away,
        "head_pose_away": head_pose_away,
        "message": message,
    }
