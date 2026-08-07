"""
service.py

본인 인증 서비스 모듈.

- 입력 이미지 데이터 검증
- AWS Rekognition CompareFaces 호출
- 얼굴 유사도 분석
- OCR 미사용 기간의 신청 정보 임시 통과 처리
- 얼굴 인증 기반 최종 성공 여부 판단
"""

from typing import Any

from app.core.config import settings
from app.schemas.identity import DocumentType
from modules.common.image_validation import (
    validate_image_bytes,
)
from modules.identity_verification.face_compare import (
    compare_faces,
)


def verify_identity(
    source_image_bytes: bytes,
    target_image_bytes: bytes,
    document_type: DocumentType = DocumentType.PASSPORT,
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
    retrieval_threshold = (
        settings.identity_similarity_retrieval_threshold
    )

    # 낮은 조회 기준으로 후보 유사도를 확보한 뒤 운영 기준으로 판정한다.
    response = compare_faces(
        source_image_bytes=source_image_bytes,
        target_image_bytes=target_image_bytes,
        similarity_threshold=retrieval_threshold,
    )

    candidate_matches = response.get("FaceMatches", [])
    aws_unmatched_faces = response.get("UnmatchedFaces", [])
    best_match = max(
        candidate_matches,
        key=lambda match: match.get("Similarity", 0.0),
        default=None,
    )

    similarity = (
        float(best_match.get("Similarity", 0.0))
        if best_match is not None
        else 0.0
    )
    face_verified = similarity >= threshold
    matched_face_count = sum(
        float(match.get("Similarity", 0.0)) >= threshold
        for match in candidate_matches
    )
    unmatched_face_count = (
        len(candidate_matches)
        - matched_face_count
        + len(aws_unmatched_faces)
    )

    # OCR 미사용 기간에는 신청 정보 검증을 얼굴 인증과 분리해 통과시킨다.
    applicant_verified = True
    field_matches = {
        "last_name": True,
        "first_name": True,
        "birth_date": True,
    }

    return {
        "verified": face_verified,
        "face_verified": face_verified,
        "similarity": round(similarity, 2),
        "threshold": threshold,
        "matched_face_count": matched_face_count,
        "unmatched_face_count": unmatched_face_count,
        "applicant_verified": applicant_verified,
        "document_type": document_type.value,
        "field_matches": field_matches,
        "message": (
            "본인 인증에 성공했습니다."
            if face_verified
            else "얼굴이 일치하지 않습니다."
        ),
    }
