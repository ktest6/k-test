"""
gaze_calibration.py

시험 시작 전 응시자별 화면 중앙 시선 기준점 관리 모듈.

- 여러 얼굴 모니터링 결과에서 유효한 Eye Direction 표본 선별
- Yaw와 Pitch의 중앙값을 응시자별 화면 중앙 기준점으로 생성
- Calibration 결과를 저장하지 않고 호출자에게 반환

※ AWS Rekognition API를 직접 호출하지 않는다.
※ Calibration 결과의 저장과 전달은 백엔드가 담당한다.
"""

from statistics import median
from typing import Any

from modules.cheating_detection.gaze_monitor import extract_eye_direction
from modules.common.exceptions import GazeCalibrationError


def validate_gaze_calibration_input(
    exam_id: str,
    examinee_id: str,
    face_monitor_results: list[dict[str, Any]],
    minimum_eye_confidence: float,
    minimum_sample_count: int,
) -> None:
    """Calibration 생성에 필요한 입력값을 검증한다."""

    if not isinstance(exam_id, str) or not exam_id.strip():
        raise GazeCalibrationError(
            "시험 식별자는 비어 있을 수 없습니다.",
            code="CALIBRATION_EXAM_ID_EMPTY",
        )

    if not isinstance(examinee_id, str) or not examinee_id.strip():
        raise GazeCalibrationError(
            "응시자 식별자는 비어 있을 수 없습니다.",
            code="CALIBRATION_EXAMINEE_ID_EMPTY",
        )

    if not isinstance(face_monitor_results, list) or not face_monitor_results:
        raise GazeCalibrationError(
            "얼굴 모니터링 결과는 비어 있지 않은 리스트여야 합니다.",
            code="CALIBRATION_FACE_RESULTS_INVALID",
        )

    if (
        not isinstance(minimum_eye_confidence, (int, float))
        or isinstance(minimum_eye_confidence, bool)
        or not 0 <= minimum_eye_confidence <= 100
    ):
        raise GazeCalibrationError(
            "Eye Direction 최소 신뢰도는 0 이상 100 이하의 숫자여야 합니다.",
            code="CALIBRATION_EYE_CONFIDENCE_OUT_OF_RANGE",
            params={
                "actual": minimum_eye_confidence,
                "min": 0,
                "max": 100,
            },
        )

    if (
        not isinstance(minimum_sample_count, int)
        or isinstance(minimum_sample_count, bool)
        or minimum_sample_count < 1
    ):
        raise GazeCalibrationError(
            "Calibration 최소 표본 수는 1 이상의 정수여야 합니다.",
            code="CALIBRATION_MIN_SAMPLE_COUNT_INVALID",
            params={"actual": minimum_sample_count, "min": 1},
        )


def create_gaze_calibration(
    exam_id: str,
    examinee_id: str,
    face_monitor_results: list[dict[str, Any]],
    minimum_eye_confidence: float,
    minimum_sample_count: int,
) -> dict[str, Any]:
    """유효한 시선 표본의 중앙값으로 Calibration을 생성한다."""

    validate_gaze_calibration_input(
        exam_id=exam_id,
        examinee_id=examinee_id,
        face_monitor_results=face_monitor_results,
        minimum_eye_confidence=minimum_eye_confidence,
        minimum_sample_count=minimum_sample_count,
    )

    eye_yaw_samples: list[float] = []
    eye_pitch_samples: list[float] = []

    for face_monitor_result in face_monitor_results:
        if not isinstance(face_monitor_result, dict):
            continue

        if face_monitor_result.get("face_count") != 1:
            continue

        face_details = face_monitor_result.get("face_details")

        if not isinstance(face_details, list) or not face_details:
            continue

        face_detail = face_details[0]

        if not isinstance(face_detail, dict):
            continue

        eye_direction = extract_eye_direction(face_detail)

        if eye_direction["confidence"] < minimum_eye_confidence:
            continue

        eye_yaw_samples.append(eye_direction["yaw"])
        eye_pitch_samples.append(eye_direction["pitch"])

    sample_count = len(eye_yaw_samples)

    if sample_count < minimum_sample_count:
        raise GazeCalibrationError(
            "Calibration에 필요한 유효 시선 표본이 부족합니다.",
            code="CALIBRATION_SAMPLES_INSUFFICIENT",
            params={
                "actualCount": sample_count,
                "requiredCount": minimum_sample_count,
            },
        )

    return {
        "eye_yaw_center": float(median(eye_yaw_samples)),
        "eye_pitch_center": float(median(eye_pitch_samples)),
        "sample_count": sample_count,
    }
