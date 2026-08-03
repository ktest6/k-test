"""
gaze_state.py

시험 중 응시자의 연속 시선 이탈 상태 관리 모듈.

- 시험 및 응시자별 시선 상태 관리
- 연속 시선 이탈 횟수 계산
- 시선 이탈 지속 시간 계산
- 정상 시선 복귀 시 상태 초기화
- 프레임 순번이 연속되지 않을 경우 기존 상태 초기화

※ 현재 구현은 서버 메모리에 상태를 저장한다.
※ 서버 재시작 시 상태가 초기화되며, 다중 서버 환경에서는
   Redis 또는 Database 기반 상태 저장 방식으로 변경해야 한다.
"""

from typing import Any

from modules.cheating_detection.gaze_monitor import (
    EVENT_GAZE_AWAY,
    EVENT_GAZE_NORMAL,
)
from modules.common.exceptions import GazeStateError


# 시험 및 응시자별 시선 상태 저장
_GAZE_STATE_STORE: dict[str, dict[str, Any]] = {}


def validate_gaze_state_input(
    exam_id: str,
    examinee_id: str,
    gaze_monitor_result: dict[str, Any],
    elapsed_ms: int,
    capture_sequence: int,
    persistent_count_threshold: int,
) -> None:
    """시선 상태 갱신에 필요한 입력값을 검증한다."""

    if not isinstance(exam_id, str) or not exam_id.strip():
        raise GazeStateError(
            "시험 식별자는 비어 있을 수 없습니다."
        )

    if not isinstance(examinee_id, str) or not examinee_id.strip():
        raise GazeStateError(
            "응시자 식별자는 비어 있을 수 없습니다."
        )

    if not isinstance(gaze_monitor_result, dict):
        raise GazeStateError(
            "시선 분석 결과는 딕셔너리 형식이어야 합니다."
        )

    if not isinstance(elapsed_ms, int) or isinstance(elapsed_ms, bool):
        raise GazeStateError(
            "시험 경과 시간은 정수여야 합니다."
        )

    if elapsed_ms < 0:
        raise GazeStateError(
            "시험 경과 시간은 0 이상이어야 합니다."
        )

    if (
        not isinstance(capture_sequence, int)
        or isinstance(capture_sequence, bool)
    ):
        raise GazeStateError(
            "캡처 이미지 순번은 정수여야 합니다."
        )

    if capture_sequence < 1:
        raise GazeStateError(
            "캡처 이미지 순번은 1 이상이어야 합니다."
        )

    if (
        not isinstance(persistent_count_threshold, int)
        or isinstance(persistent_count_threshold, bool)
    ):
        raise GazeStateError(
            "연속 시선 이탈 기준 횟수는 정수여야 합니다."
        )

    if persistent_count_threshold < 1:
        raise GazeStateError(
            "연속 시선 이탈 기준 횟수는 1 이상이어야 합니다."
        )


def create_state_key(
    exam_id: str,
    examinee_id: str,
) -> str:
    """시험과 응시자 식별자를 조합해 상태 저장 키를 생성한다."""

    return f"{exam_id}:{examinee_id}"


def create_initial_gaze_state() -> dict[str, Any]:
    """초기 시선 상태를 생성한다."""

    return {
        "consecutive_away_count": 0,
        "consecutive_eye_only_count": 0,
        "consecutive_head_only_count": 0,
        "consecutive_eye_and_head_count": 0,
        "away_started_elapsed_ms": None,
        "away_duration_ms": 0,
        "last_direction": None,
        "last_capture_sequence": None,
        "last_elapsed_ms": None,
        "persistent_gaze_away": False,
    }


def get_gaze_state(
    exam_id: str,
    examinee_id: str,
) -> dict[str, Any]:
    """시험 및 응시자별 현재 시선 상태를 반환한다."""

    state_key = create_state_key(
        exam_id=exam_id,
        examinee_id=examinee_id,
    )

    if state_key not in _GAZE_STATE_STORE:
        _GAZE_STATE_STORE[state_key] = create_initial_gaze_state()

    return _GAZE_STATE_STORE[state_key]


def reset_gaze_state(
    exam_id: str,
    examinee_id: str,
    capture_sequence: int | None = None,
    elapsed_ms: int | None = None,
) -> dict[str, Any]:
    """시험 및 응시자별 시선 상태를 초기화한다."""

    state_key = create_state_key(
        exam_id=exam_id,
        examinee_id=examinee_id,
    )

    gaze_state = create_initial_gaze_state()

    gaze_state["last_capture_sequence"] = capture_sequence
    gaze_state["last_elapsed_ms"] = elapsed_ms

    _GAZE_STATE_STORE[state_key] = gaze_state

    return gaze_state


def is_capture_sequence_continuous(
    previous_sequence: int | None,
    current_sequence: int,
) -> bool:
    """현재 프레임 순번이 이전 프레임과 연속되는지 판단한다."""

    if previous_sequence is None:
        return True

    return current_sequence == previous_sequence + 1


def is_elapsed_time_valid(
    previous_elapsed_ms: int | None,
    current_elapsed_ms: int,
) -> bool:
    """현재 시험 경과 시간이 이전 프레임보다 증가했는지 판단한다."""

    if previous_elapsed_ms is None:
        return True

    return current_elapsed_ms > previous_elapsed_ms


def update_gaze_state(
    exam_id: str,
    examinee_id: str,
    gaze_monitor_result: dict[str, Any],
    elapsed_ms: int,
    capture_sequence: int,
    persistent_count_threshold: int,
) -> dict[str, Any]:
    """
    현재 프레임의 시선 분석 결과를 반영해 연속 상태를 갱신한다.

    처리 기준:
    - GAZE_AWAY:
      연속 이탈 횟수와 지속 시간을 증가시킨다.
    - GAZE_NORMAL:
      기존 시선 이탈 상태를 초기화한다.
    - 그 외 상태:
      기존 이탈 상태는 유지하되 횟수와 지속 시간은 증가시키지 않는다.
    - 캡처 순번 또는 경과 시간이 연속적이지 않으면 상태를 초기화한다.
    """

    validate_gaze_state_input(
        exam_id=exam_id,
        examinee_id=examinee_id,
        gaze_monitor_result=gaze_monitor_result,
        elapsed_ms=elapsed_ms,
        capture_sequence=capture_sequence,
        persistent_count_threshold=persistent_count_threshold,
    )

    gaze_state = get_gaze_state(
        exam_id=exam_id,
        examinee_id=examinee_id,
    )

    previous_sequence = gaze_state.get(
        "last_capture_sequence",
    )

    previous_elapsed_ms = gaze_state.get(
        "last_elapsed_ms",
    )

    sequence_continuous = is_capture_sequence_continuous(
        previous_sequence=previous_sequence,
        current_sequence=capture_sequence,
    )

    elapsed_time_valid = is_elapsed_time_valid(
        previous_elapsed_ms=previous_elapsed_ms,
        current_elapsed_ms=elapsed_ms,
    )

    state_continuous = (
        sequence_continuous
        and elapsed_time_valid
    )

    if not state_continuous:
        gaze_state = reset_gaze_state(
            exam_id=exam_id,
            examinee_id=examinee_id,
        )

    event_type = gaze_monitor_result.get(
        "event_type",
    )

    direction = gaze_monitor_result.get(
        "direction",
    )

    if event_type == EVENT_GAZE_AWAY:
        eye_gaze_away = (
            gaze_monitor_result.get("eye_gaze_away") is True
        )

        head_pose_away = (
            gaze_monitor_result.get("head_pose_away") is True
        )

        away_started_elapsed_ms = gaze_state.get(
            "away_started_elapsed_ms",
        )

        if away_started_elapsed_ms is None:
            away_started_elapsed_ms = elapsed_ms

        consecutive_away_count = (
            gaze_state.get(
                "consecutive_away_count",
                0,
            )
            + 1
        )

        consecutive_eye_only_count = 0
        consecutive_head_only_count = 0
        consecutive_eye_and_head_count = 0

        if eye_gaze_away and not head_pose_away:
            consecutive_eye_only_count = (
                gaze_state.get(
                    "consecutive_eye_only_count",
                    0,
                )
                + 1
            )

        elif not eye_gaze_away and head_pose_away:
            consecutive_head_only_count = (
                gaze_state.get(
                    "consecutive_head_only_count",
                    0,
                )
                + 1
            )

        elif eye_gaze_away and head_pose_away:
            consecutive_eye_and_head_count = (
                gaze_state.get(
                    "consecutive_eye_and_head_count",
                    0,
                )
                + 1
            )

        away_duration_ms = max(
            elapsed_ms - away_started_elapsed_ms,
            0,
        )

        persistent_gaze_away = (
            consecutive_away_count
            >= persistent_count_threshold
        )

        gaze_state.update(
            {
                "consecutive_away_count": consecutive_away_count,
                "consecutive_eye_only_count": (
                    consecutive_eye_only_count
                ),
                "consecutive_head_only_count": (
                    consecutive_head_only_count
                ),
                "consecutive_eye_and_head_count": (
                    consecutive_eye_and_head_count
                ),
                "away_started_elapsed_ms": away_started_elapsed_ms,
                "away_duration_ms": away_duration_ms,
                "last_direction": direction,
                "last_capture_sequence": capture_sequence,
                "last_elapsed_ms": elapsed_ms,
                "persistent_gaze_away": persistent_gaze_away,
            }
        )

    elif event_type == EVENT_GAZE_NORMAL:
        gaze_state = reset_gaze_state(
            exam_id=exam_id,
            examinee_id=examinee_id,
            capture_sequence=capture_sequence,
            elapsed_ms=elapsed_ms,
        )

    else:
        gaze_state.update(
            {
                "last_capture_sequence": capture_sequence,
                "last_elapsed_ms": elapsed_ms,
            }
        )

    return {
        "consecutive_away_count": gaze_state.get(
            "consecutive_away_count",
            0,
        ),
        "consecutive_eye_only_count": gaze_state.get(
            "consecutive_eye_only_count",
            0,
        ),
        "consecutive_head_only_count": gaze_state.get(
            "consecutive_head_only_count",
            0,
        ),
        "consecutive_eye_and_head_count": gaze_state.get(
            "consecutive_eye_and_head_count",
            0,
        ),
        "away_duration_ms": gaze_state.get(
            "away_duration_ms",
            0,
        ),
        "last_direction": gaze_state.get(
            "last_direction",
        ),
        "persistent_gaze_away": gaze_state.get(
            "persistent_gaze_away",
            False,
        ),
        "sequence_continuous": sequence_continuous,
        "elapsed_time_valid": elapsed_time_valid,
        "state_continuous": state_continuous,
    }


def clear_gaze_state(
    exam_id: str,
    examinee_id: str,
) -> None:
    """시험 종료 후 해당 응시자의 시선 상태를 삭제한다."""

    if not isinstance(exam_id, str) or not exam_id.strip():
        raise GazeStateError(
            "시험 식별자는 비어 있을 수 없습니다."
        )

    if not isinstance(examinee_id, str) or not examinee_id.strip():
        raise GazeStateError(
            "응시자 식별자는 비어 있을 수 없습니다."
        )

    state_key = create_state_key(
        exam_id=exam_id,
        examinee_id=examinee_id,
    )

    _GAZE_STATE_STORE.pop(
        state_key,
        None,
    )


def clear_all_gaze_states() -> None:
    """로컬 테스트를 위해 모든 시선 상태를 삭제한다."""

    _GAZE_STATE_STORE.clear()
