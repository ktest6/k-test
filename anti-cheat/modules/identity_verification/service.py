"""
service.py

본인 인증 서비스 모듈.

- 입력 이미지 데이터 검증
- AWS Rekognition CompareFaces 호출
- 얼굴 유사도 분석
- 본인 인증 성공 여부 판단
"""

from typing import Any

from app.core.config import settings
from modules.common.image_validation import (
    validate_image_bytes,
)
from modules.identity_verification.face_compare import (
    compare_faces,
)



def verify_identity(
    source_image_bytes: bytes,
    target_image_bytes: bytes,
) -> dict[str, Any]:
    """신분증 얼굴과 캡처 얼굴을 비교하여 본인 여부를 판단한다."""

    validate_image_bytes(
        image_bytes=source_image_bytes,
        image_name="신분증",
    )

    validate_image_bytes(
        image_bytes=target_image_bytes,
        image_name="얼굴 캡처",
    )

    threshold = settings.identity_similarity_threshold

    response = compare_faces(
        source_image_bytes=source_image_bytes,
        target_image_bytes=target_image_bytes,
        similarity_threshold=threshold,
    )

    face_matches = response.get("FaceMatches", [])
    unmatched_faces = response.get("UnmatchedFaces", [])

    if not face_matches:
        return {
            "verified": False,
            "similarity": None,
            "threshold": threshold,
            "matched_face_count": 0,
            "unmatched_face_count": len(unmatched_faces),
            "message": "일치하는 얼굴을 찾지 못했습니다.",
        }

    best_match = max(
        face_matches,
        key=lambda match: match.get("Similarity", 0.0),
    )

    similarity = best_match.get("Similarity", 0.0)
    verified = similarity >= threshold

    return {
        "verified": verified,
        "similarity": round(similarity, 2),
        "threshold": threshold,
        "matched_face_count": len(face_matches),
        "unmatched_face_count": len(unmatched_faces),
        "message": (
            "본인 인증에 성공했습니다."
            if verified
            else "본인 인증에 실패했습니다."
        ),
    }