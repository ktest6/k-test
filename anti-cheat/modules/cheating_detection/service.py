"""
service.py

시험 중 모니터링 전체 흐름을 관리하는 서비스 모듈.

처리 과정
1. 현재 프레임 이미지 검증
2. AWS Rekognition DetectFaces 호출
3. 얼굴 수 및 화면 이탈 상태 분석
4. 시선 및 고개 방향 분석
5. 연속 시선 이탈 상태 갱신
6. 필요한 경우 기준 얼굴과 현재 얼굴 비교
7. 객체 탐지 및 분석
8. Rule Engine으로 위험도 및 Decision 결정
9. Event Engine으로 이벤트 응답 구조 생성
10. 모니터링 최종 결과 반환
"""

from datetime import datetime
from typing import Any

from app.core.config import settings

from modules.common.exceptions import MonitoringError, ProctoringError
from modules.common.image_validation import validate_image_bytes

from modules.cheating_detection.face_detection import detect_faces
from modules.cheating_detection.face_monitor import (
    EVENT_FACE_NORMAL,
    analyze_face_monitor,
)
from modules.cheating_detection.gaze_calibration import (
    create_gaze_calibration,
)
from modules.cheating_detection.gaze_monitor import (
    analyze_gaze_monitor,
)
from modules.cheating_detection.gaze_state import (
    update_gaze_state,
)
from modules.cheating_detection.identity_monitor import (
    analyze_identity_monitor,
)
from modules.cheating_detection.rule_engine import evaluate_rules
from modules.cheating_detection.event_engine import process_event

from modules.object_detection.detector import detect_objects
from modules.object_detection.analyzer import (
    analyze_object_detection,
)


def should_run_identity_check(
    face_monitor_result: dict[str, Any],
    reference_image_bytes: bytes | None,
) -> bool:
    """
    시험 중 동일인 검사를 실행할 수 있는 상태인지 판단한다.

    동일인 검사는 다음 조건에서만 실행한다.
    - 기준 얼굴 이미지가 존재함
    - 현재 프레임에서 얼굴이 정확히 1명 확인됨
    """

    if reference_image_bytes is None:
        return False

    event_type = face_monitor_result.get(
        "event_type",
    )

    return event_type == EVENT_FACE_NORMAL


def validate_identity_check_request(
    run_identity_check: bool,
    reference_image_bytes: bytes | None,
) -> None:
    """동일인 검사 요청 시 기준 이미지가 함께 전달됐는지 검증한다."""

    if run_identity_check and reference_image_bytes is None:
        raise MonitoringError(
            "중간 동일인 검사를 위한 기준 이미지가 없습니다.",
            code="IDENTITY_REFERENCE_IMAGE_REQUIRED",
        )


def run_identity_monitoring(
    reference_image_bytes: bytes,
    current_image_bytes: bytes,
) -> dict[str, Any]:
    """
    기준 이미지와 현재 프레임을 비교해 동일인 여부를 분석한다.

    동일인 판정 임계값은 API 요청에서 받지 않고
    AI 서버 설정값을 사용한다.
    """

    identity_monitor_result = analyze_identity_monitor(
        reference_image_bytes=reference_image_bytes,
        current_image_bytes=current_image_bytes,
        similarity_threshold=settings.identity_similarity_threshold,
    )

    return identity_monitor_result


def create_gaze_calibration_from_images(
    exam_id: str,
    examinee_id: str,
    calibration_image_bytes_list: list[bytes],
) -> dict[str, Any]:
    """Calibration 이미지로 시선 중앙 기준값을 계산한다."""

    face_monitor_results: list[dict[str, Any]] = []

    for image_bytes in calibration_image_bytes_list:
        validate_image_bytes(
            image_bytes=image_bytes,
            image_name="시선 Calibration 이미지",
            image_key="calibrationImage",
        )
        detect_faces_response = detect_faces(
            image_bytes=image_bytes,
        )
        face_monitor_results.append(
            analyze_face_monitor(detect_faces_response)
        )

    return create_gaze_calibration(
        exam_id=exam_id,
        examinee_id=examinee_id,
        face_monitor_results=face_monitor_results,
        minimum_eye_confidence=settings.gaze_minimum_eye_confidence,
        minimum_sample_count=(
            settings.gaze_calibration_minimum_sample_count
        ),
    )


def analyze_monitoring_frame(
    exam_id: str,
    examinee_id: str,
    request_id: str,
    captured_at: datetime,
    elapsed_ms: int,
    capture_sequence: int,
    current_image_bytes: bytes,
    reference_image_bytes: bytes | None = None,
    run_identity_check: bool = False,
    eye_yaw_center: float | None = None,
    eye_pitch_center: float | None = None,
    head_yaw_center: float | None = None,
    head_pitch_center: float | None = None,
    previous_gaze_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    시험 중 전달받은 프레임 한 장을 분석한다.

    Args:
        exam_id:
            현재 시험 식별자.

        examinee_id:
            현재 응시자 식별자.

        request_id:
            모니터링 요청 고유 식별자.

        captured_at:
            현재 프레임이 실제로 촬영된 시각.

        elapsed_ms:
            시험 시작 후 현재 프레임 촬영까지 경과한 시간.

        capture_sequence:
            시험 시작 후 전송된 캡처 이미지 순번.

        current_image_bytes:
            웹에서 전달받은 현재 프레임 이미지 bytes.

        reference_image_bytes:
            최초 본인 인증 시 사용한 기준 얼굴 이미지 bytes.
            동일인 검사를 하지 않는 요청에서는 None을 전달할 수 있다.

        run_identity_check:
            이번 요청에서 중간 동일인 검사를 실행할지 여부.

        eye_yaw_center:
            백엔드가 저장한 응시자의 화면 중앙 Eye Yaw 기준값.

        eye_pitch_center:
            백엔드가 저장한 응시자의 화면 중앙 Eye Pitch 기준값.

        previous_gaze_state:
            백엔드가 직전 응답에서 저장한 시선 상태.

    Returns:
        얼굴, 시선, 동일인 분석 결과와
        이벤트 요약 및 이벤트 목록을 포함한 딕셔너리.
    """

    try:
        validate_image_bytes(
            image_bytes=current_image_bytes,
            image_name="현재 프레임 이미지",
            image_key="currentImage",
        )

        validate_identity_check_request(
            run_identity_check=run_identity_check,
            reference_image_bytes=reference_image_bytes,
        )

        if reference_image_bytes is not None:
            validate_image_bytes(
                image_bytes=reference_image_bytes,
                image_name="기준 얼굴 이미지",
                image_key="referenceImage",
            )

        detect_faces_response = detect_faces(
            image_bytes=current_image_bytes,
        )

        face_monitor_result = analyze_face_monitor(
            detect_faces_response,
        )

        gaze_calibration = None

        if eye_yaw_center is not None and eye_pitch_center is not None:
            gaze_calibration = {
                "eye_yaw_center": eye_yaw_center,
                "eye_pitch_center": eye_pitch_center,
            }

            if head_yaw_center is not None and head_pitch_center is not None:
                gaze_calibration.update(
                    {
                        "head_yaw_center": head_yaw_center,
                        "head_pitch_center": head_pitch_center,
                    }
                )

        gaze_monitor_result = analyze_gaze_monitor(
            face_monitor_result=face_monitor_result,
            eye_yaw_threshold=(
                settings.gaze_eye_yaw_threshold
            ),
            eye_pitch_threshold=(
                settings.gaze_eye_pitch_threshold
            ),
            head_yaw_threshold=(
                settings.gaze_head_yaw_threshold
            ),
            head_pitch_threshold=(
                settings.gaze_head_pitch_threshold
            ),
            minimum_eye_confidence=(
                settings.gaze_minimum_eye_confidence
            ),
            gaze_calibration=gaze_calibration,
            head_yaw_slight_threshold=(
                settings.gaze_head_yaw_slight_threshold
            ),
            head_yaw_large_threshold=(
                settings.gaze_head_yaw_large_threshold
            ),
            head_pitch_down_slight_threshold=(
                settings.gaze_head_pitch_down_medium_threshold
            ),
            head_pitch_down_large_threshold=(
                settings.gaze_head_pitch_down_high_threshold
            ),
            head_pitch_up_slight_threshold=(
                settings.gaze_head_pitch_up_slight_threshold
            ),
            head_pitch_up_large_threshold=(
                settings.gaze_head_pitch_up_large_threshold
            ),
        )

        gaze_state_result = update_gaze_state(
            gaze_monitor_result=gaze_monitor_result,
            elapsed_ms=elapsed_ms,
            capture_sequence=capture_sequence,
            persistent_count_threshold=(
                settings.gaze_persistent_count_threshold
            ),
            previous_state=previous_gaze_state,
        )

        gaze_monitor_result["state"] = gaze_state_result

        identity_monitor_result = None

        can_run_identity_check = should_run_identity_check(
            face_monitor_result=face_monitor_result,
            reference_image_bytes=reference_image_bytes,
        )

        if run_identity_check and can_run_identity_check:
            identity_monitor_result = run_identity_monitoring(
                reference_image_bytes=reference_image_bytes,
                current_image_bytes=current_image_bytes,
            )


        # 시험 중 객체 탐지
        object_detection_result = detect_objects(
            image_bytes=current_image_bytes,
        )

        object_monitor_result = analyze_object_detection(
            detection_result=object_detection_result,
            head_pose=gaze_monitor_result.get(
                "head_pose",
                {},
            ),
        )

        monitoring_results = {
            "face_monitor": face_monitor_result,
            "gaze_monitor": gaze_monitor_result,
            "identity_monitor": identity_monitor_result,
            "object_monitor": object_monitor_result,
        }

        rule_result = evaluate_rules(
            monitoring_results,
        )

        event_result = process_event(
            exam_id=exam_id,
            examinee_id=examinee_id,
            request_id=request_id,
            captured_at=captured_at,
            elapsed_ms=elapsed_ms,
            capture_sequence=capture_sequence,
            rule_result=rule_result,
        )

        face_monitor_response = {
            "face_count": face_monitor_result.get(
                "face_count",
                0,
            ),
            "event_type": face_monitor_result.get(
                "event_type",
            ),
            "message": face_monitor_result.get(
                "message",
            ),
        }

        return {
            "exam_id": exam_id,
            "examinee_id": examinee_id,
            "request_id": request_id,
            "captured_at": captured_at,
            "elapsed_ms": elapsed_ms,
            "capture_sequence": capture_sequence,
            "face_monitor": face_monitor_response,
            "gaze_monitor": gaze_monitor_result,
            "object_monitor": object_monitor_result,
            "identity_check_requested": run_identity_check,
            "identity_check_executed": (
                identity_monitor_result is not None
            ),
            "identity_monitor": identity_monitor_result,
            "event_summary": event_result.get(
                "event_summary",
                {
                    "event_detected": False,
                    "event_count": 0,
                    "severity": "NORMAL",
                    "decision": "NONE",
                    "create_clip": False,
                },
            ),
            "events": event_result.get(
                "events",
                [],
            ),
        }

    except ProctoringError:
        raise

    except Exception as error:
        raise MonitoringError(
            "시험 모니터링 프레임 분석 중 오류가 발생했습니다.",
            code="MONITORING_FRAME_ANALYSIS_FAILED",
        ) from error
