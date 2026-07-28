"""
service.py

시험 중 모니터링 전체 흐름을 관리하는 서비스 모듈.

처리 과정
1. 현재 프레임 이미지 검증
2. AWS Rekognition DetectFaces 호출
3. 얼굴 수 및 화면 이탈 상태 분석
4. 필요한 경우 기준 얼굴과 현재 얼굴 비교
5. Rule Engine으로 위험도 및 Decision 결정
6. Event Engine으로 이벤트 생성 및 저장
7. 모니터링 최종 결과 반환
"""

from datetime import datetime
from typing import Any

from app.core.config import settings

from modules.common.exceptions import MonitoringError
from modules.common.image_validation import validate_image_bytes

from modules.cheating_detection.face_detection import detect_faces
from modules.cheating_detection.face_monitor import (
    EVENT_FACE_NORMAL,
    analyze_face_monitor,
)
from modules.cheating_detection.identity_monitor import (
    analyze_identity_monitor,
)
from modules.cheating_detection.rule_engine import evaluate_rules
from modules.cheating_detection.event_engine import process_event


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

    Returns:
        얼굴 분석, 동일인 분석, Rule Engine,
        Event Engine 결과를 포함한 딕셔너리.
    """

    try:
        validate_image_bytes(
            image_bytes=current_image_bytes,
            image_name="현재 프레임 이미지",
        )

        if reference_image_bytes is not None:
            validate_image_bytes(
                image_bytes=reference_image_bytes,
                image_name="기준 얼굴 이미지",
            )

        detect_faces_response = detect_faces(
            image_bytes=current_image_bytes,
        )

        face_monitor_result = analyze_face_monitor(
            detect_faces_response,
        )

        identity_monitor_result = None

        can_run_identity_check = should_run_identity_check(
            face_monitor_result=face_monitor_result,
            reference_image_bytes=reference_image_bytes,
        )

        if run_identity_check and can_run_identity_check:
            if reference_image_bytes is None:
                raise MonitoringError(
                    "중간 동일인 검사를 위한 기준 이미지가 없습니다."
                )

            identity_monitor_result = run_identity_monitoring(
                reference_image_bytes=reference_image_bytes,
                current_image_bytes=current_image_bytes,
            )

        monitoring_results = {
            "face_monitor": face_monitor_result,
            "identity_monitor": identity_monitor_result,
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

        return {
            "exam_id": exam_id,
            "examinee_id": examinee_id,
            "request_id": request_id,
            "captured_at": captured_at,
            "elapsed_ms": elapsed_ms,
            "capture_sequence": capture_sequence,
            "face_monitor": face_monitor_result,
            "identity_check_requested": run_identity_check,
            "identity_check_executed": (
                identity_monitor_result is not None
            ),
            "identity_monitor": identity_monitor_result,
            "rule_result": rule_result,
            "event_result": event_result,
        }

    except MonitoringError:
        raise

    except Exception as error:
        raise MonitoringError(
            "시험 모니터링 프레임 분석 중 오류가 발생했습니다."
        ) from error