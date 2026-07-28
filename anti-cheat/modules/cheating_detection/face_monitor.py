"""
face_monitor.py

시험 중 얼굴 상태 판단 모듈.

- DetectFaces 응답에서 얼굴 정보 추출
- 검출된 얼굴 수 계산
- 화면 이탈 및 다중 인원 이벤트 판단
"""

from typing import Any


EVENT_FACE_NORMAL = "FACE_NORMAL"
EVENT_FACE_OUT_OF_FRAME = "FACE_OUT_OF_FRAME"
EVENT_MULTIPLE_FACES = "MULTIPLE_FACES"


def extract_face_details(
    detection_response: dict[str, Any],
) -> list[dict[str, Any]]:
    """DetectFaces 응답에서 얼굴 상세 정보를 추출한다."""

    face_details = detection_response.get("FaceDetails", [])

    if not isinstance(face_details, list):
        return []

    return face_details


def analyze_face_monitor(
    detection_response: dict[str, Any],
) -> dict[str, Any]:
    """DetectFaces 응답을 바탕으로 얼굴 상태를 판단한다."""

    face_details = extract_face_details(detection_response)
    face_count = len(face_details)

    if face_count == 0:
        event_type = EVENT_FACE_OUT_OF_FRAME
        message = "화면에서 얼굴을 찾지 못했습니다."

    elif face_count >= 2:
        event_type = EVENT_MULTIPLE_FACES
        message = "화면에서 여러 명의 얼굴이 감지되었습니다."

    else:
        event_type = EVENT_FACE_NORMAL
        message = "한 명의 얼굴이 정상적으로 감지되었습니다."

    return {
        "face_count": face_count,
        "face_details": face_details,
        "event_type": event_type,
        "message": message,
    }