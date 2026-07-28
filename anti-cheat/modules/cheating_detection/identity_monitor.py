"""
identity_monitor.py

시험 중 기준 얼굴과 현재 얼굴을 비교하는 모듈.

- 시험 시작 시 등록한 기준 얼굴과 현재 프레임 비교
- CompareFaces 응답에서 동일인 여부 판단
- 본인 일치 또는 불일치 이벤트 반환
"""

from typing import Any

from modules.identity_verification.face_compare import compare_faces


EVENT_IDENTITY_MATCH = "IDENTITY_MATCH"
EVENT_IDENTITY_MISMATCH = "IDENTITY_MISMATCH"


def analyze_identity_monitor(
    reference_image_bytes: bytes,
    current_image_bytes: bytes,
    similarity_threshold: float,
) -> dict[str, Any]:
    """시험 시작 기준 얼굴과 현재 프레임의 얼굴을 비교한다."""

    response = compare_faces(
        source_image_bytes=reference_image_bytes,
        target_image_bytes=current_image_bytes,
        similarity_threshold=similarity_threshold,
    )

    face_matches = response.get("FaceMatches", [])
    matched_face_count = len(face_matches)

    if matched_face_count > 0:
        similarity = face_matches[0].get("Similarity", 0.0)
        verified = True
        event_type = EVENT_IDENTITY_MATCH
        message = "시험 시작 시 등록한 사용자와 동일인입니다."

    else:
        similarity = 0.0
        verified = False
        event_type = EVENT_IDENTITY_MISMATCH
        message = "시험 시작 시 등록한 사용자와 동일인이 아닙니다."

    return {
        "verified": verified,
        "similarity": similarity,
        "similarity_threshold": similarity_threshold,
        "matched_face_count": matched_face_count,
        "event_type": event_type,
        "message": message,
    }