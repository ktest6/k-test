"""
service.py

본인 인증 서비스 모듈.

- 입력 이미지 데이터 검증
- Azure 기반 여권 판독 및 신청 정보 비교
- AWS Rekognition CompareFaces 호출
- 얼굴 유사도 및 최종 인증 결과 판단
"""

from datetime import date
from typing import Any

from app.core.config import settings
from app.schemas.identity import DocumentType
from modules.common.exceptions import UnsupportedDocumentError
from modules.common.image_validation import validate_image_bytes
from modules.identity_verification.applicant_matcher import (
    match_applicant_info,
)
from modules.identity_verification.document_reader import (
    read_identity_document,
)
from modules.identity_verification.face_compare import compare_faces


def verify_identity(
    source_image_bytes: bytes,
    target_image_bytes: bytes,
    last_name: str,
    first_name: str,
    birth_date: date,
    document_number: str,
    document_type: DocumentType = DocumentType.PASSPORT,
) -> dict[str, Any]:
    """여권 정보와 얼굴을 순서대로 검증해 본인 여부를 판단한다."""

    if document_type != DocumentType.PASSPORT:
        raise UnsupportedDocumentError(
            "지원하는 문서는 여권뿐입니다.",
            code="DOCUMENT_TYPE_UNSUPPORTED",
            params={
                "actualType": str(document_type),
                "supportedTypes": [DocumentType.PASSPORT.value],
            },
        )

    validate_image_bytes(source_image_bytes, "여권", "passportImage")
    validate_image_bytes(
        target_image_bytes,
        "얼굴 캡처",
        "faceCaptureImage",
    )

    # 여권 판독과 신청 정보 비교에 성공한 경우에만 얼굴 비교를 수행한다.
    document_fields = read_identity_document(source_image_bytes)
    applicant_result = match_applicant_info(
        applicant_info={
            "last_name": last_name,
            "first_name": first_name,
            "birth_date": birth_date,
            "document_number": document_number,
        },
        document_fields={
            "last_name": document_fields["last_name"],
            "first_name": document_fields["first_name"],
            "birth_date": document_fields["date_of_birth"],
            "document_number": document_fields["document_number"],
        },
    )

    threshold = settings.identity_similarity_threshold
    if not applicant_result["applicant_verified"]:
        return _build_applicant_mismatch_result(
            threshold=threshold,
            field_matches=applicant_result["field_matches"],
        )

    response = compare_faces(
        source_image_bytes=source_image_bytes,
        target_image_bytes=target_image_bytes,
        similarity_threshold=(
            settings.identity_similarity_retrieval_threshold
        ),
    )
    face_result = _analyze_face_response(response, threshold)

    return {
        **face_result,
        "verified": face_result["face_verified"],
        "applicant_verified": True,
        "document_type": DocumentType.PASSPORT.value,
        "field_matches": applicant_result["field_matches"],
        "message": (
            "본인 인증에 성공했습니다."
            if face_result["face_verified"]
            else "얼굴이 일치하지 않습니다."
        ),
    }


def _build_applicant_mismatch_result(
    threshold: float,
    field_matches: dict[str, bool],
) -> dict[str, Any]:
    # 얼굴 비교 미실행 상태에서도 기존 숫자형 API 계약을 유지한다.
    return {
        "verified": False,
        "face_verified": False,
        "similarity": 0.0,
        "threshold": threshold,
        "matched_face_count": 0,
        "unmatched_face_count": 0,
        "applicant_verified": False,
        "document_type": DocumentType.PASSPORT.value,
        "field_matches": field_matches,
        "message": "신분증 정보와 신청 정보가 일치하지 않습니다.",
    }


def _analyze_face_response(
    response: dict[str, Any],
    threshold: float,
) -> dict[str, Any]:
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

    return {
        "face_verified": face_verified,
        "similarity": round(similarity, 2),
        "threshold": threshold,
        "matched_face_count": matched_face_count,
        "unmatched_face_count": (
            len(candidate_matches)
            - matched_face_count
            + len(aws_unmatched_faces)
        ),
    }
