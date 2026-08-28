"""
gaze_state.py

시험 중 응시자의 연속 시선 이탈 상태를 순수 계산하는 모듈.

- 이전 시선 상태와 현재 프레임 결과로 새 상태 계산
- 연속 시선 이탈 횟수와 지속 시간 계산
- 정상 시선 복귀 및 프레임 연속성 단절 시 초기화

※ 시험별 상태를 서버 메모리에 저장하지 않는다.
※ 백엔드는 반환된 상태를 저장하고 다음 요청에 다시 전달한다.
"""

from typing import Any

from modules.cheating_detection.gaze_monitor import (
    EVENT_GAZE_AWAY,
    EVENT_GAZE_NORMAL,
    EVENT_GAZE_NOT_ANALYZED,
    EVENT_GAZE_UNCERTAIN,
)
from modules.common.exceptions import GazeStateError


def validate_gaze_state_input(
    gaze_monitor_result: dict[str, Any],
    elapsed_ms: int,
    capture_sequence: int,
    persistent_count_threshold: int,
    previous_state: dict[str, Any] | None = None,
) -> None:
    """시선 상태 계산에 필요한 입력값을 검증한다."""

    if not isinstance(gaze_monitor_result, dict):
        raise GazeStateError(
            "시선 분석 결과는 딕셔너리 형식이어야 합니다.",
            code="GAZE_RESULT_TYPE_INVALID",
            params={"expectedType": "object"},
        )

    if not isinstance(elapsed_ms, int) or isinstance(elapsed_ms, bool):
        raise GazeStateError(
            "시험 경과 시간은 정수여야 합니다.",
            code="GAZE_ELAPSED_MS_TYPE_INVALID",
            params={"actual": elapsed_ms, "expectedType": "integer"},
        )

    if elapsed_ms < 0:
        raise GazeStateError(
            "시험 경과 시간은 0 이상이어야 합니다.",
            code="GAZE_ELAPSED_MS_OUT_OF_RANGE",
            params={"actual": elapsed_ms, "min": 0},
        )

    if not isinstance(capture_sequence, int) or isinstance(
        capture_sequence,
        bool,
    ):
        raise GazeStateError(
            "캡처 이미지 순번은 정수여야 합니다.",
            code="GAZE_CAPTURE_SEQUENCE_TYPE_INVALID",
            params={"actual": capture_sequence, "expectedType": "integer"},
        )

    if capture_sequence < 1:
        raise GazeStateError(
            "캡처 이미지 순번은 1 이상이어야 합니다.",
            code="GAZE_CAPTURE_SEQUENCE_OUT_OF_RANGE",
            params={"actual": capture_sequence, "min": 1},
        )

    if not isinstance(persistent_count_threshold, int) or isinstance(
        persistent_count_threshold,
        bool,
    ):
        raise GazeStateError(
            "연속 시선 이탈 기준 횟수는 정수여야 합니다.",
            code="GAZE_PERSISTENT_THRESHOLD_TYPE_INVALID",
            params={
                "actual": persistent_count_threshold,
                "expectedType": "integer",
            },
        )

    if persistent_count_threshold < 1:
        raise GazeStateError(
            "연속 시선 이탈 기준 횟수는 1 이상이어야 합니다.",
            code="GAZE_PERSISTENT_THRESHOLD_OUT_OF_RANGE",
            params={"actual": persistent_count_threshold, "min": 1},
        )

    if previous_state is not None and not isinstance(previous_state, dict):
        raise GazeStateError(
            "이전 시선 상태는 딕셔너리 형식이어야 합니다.",
            code="PREVIOUS_GAZE_STATE_TYPE_INVALID",
            params={"expectedType": "object"},
        )


def create_initial_gaze_state(
    capture_sequence: int | None = None,
    elapsed_ms: int | None = None,
) -> dict[str, Any]:
    """초기 시선 상태를 생성한다."""

    return {
        "consecutive_away_count": 0,
        "consecutive_eye_away_count": 0,
        "consecutive_head_away_count": 0,
        "consecutive_head_slight_count": 0,
        "consecutive_head_large_count": 0,
        "consecutive_eye_only_count": 0,
        "consecutive_head_only_count": 0,
        "consecutive_eye_and_head_count": 0,
        "away_started_elapsed_ms": None,
        "away_duration_ms": 0,
        "last_direction": None,
        "last_capture_sequence": capture_sequence,
        "last_elapsed_ms": elapsed_ms,
        "persistent_gaze_away": False,
    }


def is_capture_sequence_continuous(
    previous_sequence: int | None,
    current_sequence: int,
) -> bool:
    """현재 프레임 순번이 이전 값에서 정확히 1 증가했는지 판단한다."""

    if previous_sequence is None:
        return True

    return current_sequence == previous_sequence + 1


def is_elapsed_time_valid(
    previous_elapsed_ms: int | None,
    current_elapsed_ms: int,
) -> bool:
    """현재 시험 경과 시간이 이전 값보다 증가했는지 판단한다."""

    if previous_elapsed_ms is None:
        return True

    return current_elapsed_ms > previous_elapsed_ms


def update_gaze_state(
    gaze_monitor_result: dict[str, Any],
    elapsed_ms: int,
    capture_sequence: int,
    persistent_count_threshold: int,
    previous_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """이전 상태와 현재 시선 분석 결과로 새 연속 상태를 계산한다."""

    validate_gaze_state_input(
        gaze_monitor_result=gaze_monitor_result,
        elapsed_ms=elapsed_ms,
        capture_sequence=capture_sequence,
        persistent_count_threshold=persistent_count_threshold,
        previous_state=previous_state,
    )

    gaze_state = (
        dict(previous_state)
        if previous_state is not None
        else create_initial_gaze_state()
    )

    previous_sequence = gaze_state.get("last_capture_sequence")
    previous_elapsed_ms = gaze_state.get("last_elapsed_ms")

    sequence_continuous = is_capture_sequence_continuous(
        previous_sequence=previous_sequence,
        current_sequence=capture_sequence,
    )
    elapsed_time_valid = is_elapsed_time_valid(
        previous_elapsed_ms=previous_elapsed_ms,
        current_elapsed_ms=elapsed_ms,
    )
    state_continuous = sequence_continuous and elapsed_time_valid

    if not state_continuous:
        gaze_state = create_initial_gaze_state()

    event_type = gaze_monitor_result.get("event_type")
    direction = gaze_monitor_result.get("direction")

    if event_type == EVENT_GAZE_AWAY:
        eye_gaze_away = gaze_monitor_result.get("eye_gaze_away") is True
        head_pose_away = gaze_monitor_result.get("head_pose_away") is True
        head_pose_level = gaze_monitor_result.get(
            "head_pose_level",
            "NORMAL",
        )

        away_started_elapsed_ms = gaze_state.get("away_started_elapsed_ms")
        if away_started_elapsed_ms is None:
            away_started_elapsed_ms = elapsed_ms

        consecutive_away_count = (
            gaze_state.get("consecutive_away_count", 0) + 1
        )
        consecutive_eye_away_count = (
            max(
                gaze_state.get("consecutive_eye_away_count", 0),
                gaze_state.get("consecutive_eye_only_count", 0),
            )
            + 1
            if eye_gaze_away
            else 0
        )
        consecutive_head_away_count = (
            max(
                gaze_state.get("consecutive_head_away_count", 0),
                gaze_state.get("consecutive_head_only_count", 0),
            )
            + 1
            if head_pose_away
            else 0
        )
        consecutive_eye_and_head_count = (
            gaze_state.get("consecutive_eye_and_head_count", 0) + 1
            if eye_gaze_away and head_pose_away
            else 0
        )
        consecutive_head_slight_count = (
            gaze_state.get("consecutive_head_slight_count", 0) + 1
            if head_pose_away and head_pose_level == "SLIGHT"
            else 0
        )
        consecutive_head_large_count = (
            gaze_state.get("consecutive_head_large_count", 0) + 1
            if head_pose_away and head_pose_level == "LARGE"
            else 0
        )

        # 기존 응답 필드는 백엔드 호환성을 위해 유지한다.
        consecutive_eye_only_count = (
            consecutive_eye_away_count
            if eye_gaze_away and not head_pose_away
            else 0
        )
        consecutive_head_only_count = (
            consecutive_head_away_count
            if head_pose_away and not eye_gaze_away
            else 0
        )

        gaze_state.update(
            {
                "consecutive_away_count": consecutive_away_count,
                "consecutive_eye_away_count": (
                    consecutive_eye_away_count
                ),
                "consecutive_head_away_count": (
                    consecutive_head_away_count
                ),
                "consecutive_head_slight_count": (
                    consecutive_head_slight_count
                ),
                "consecutive_head_large_count": (
                    consecutive_head_large_count
                ),
                "consecutive_eye_only_count": consecutive_eye_only_count,
                "consecutive_head_only_count": consecutive_head_only_count,
                "consecutive_eye_and_head_count": (
                    consecutive_eye_and_head_count
                ),
                "away_started_elapsed_ms": away_started_elapsed_ms,
                "away_duration_ms": max(
                    elapsed_ms - away_started_elapsed_ms,
                    0,
                ),
                "last_direction": direction,
                "persistent_gaze_away": (
                    consecutive_away_count >= persistent_count_threshold
                ),
            }
        )
    elif event_type in {
        EVENT_GAZE_NORMAL,
        EVENT_GAZE_UNCERTAIN,
        EVENT_GAZE_NOT_ANALYZED,
    }:
        gaze_state = create_initial_gaze_state()

    gaze_state.update(
        {
            "last_capture_sequence": capture_sequence,
            "last_elapsed_ms": elapsed_ms,
            "sequence_continuous": sequence_continuous,
            "elapsed_time_valid": elapsed_time_valid,
            "state_continuous": state_continuous,
        }
    )

    return gaze_state
