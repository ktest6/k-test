"""
identity.py

본인 인증 API의 요청 및 응답 데이터 구조를 정의하는 schema 모듈.

- 본인 인증 요청에 포함되는 시험 및 응시자 정보 정의
- 신청자의 이름과 생년월일 정보 정의
- 백엔드에서 전달받는 신분증 종류 정의
- 얼굴 비교 및 신청 정보 검증 결과 구조 정의
- 필드별 신청 정보 일치 여부 구조 정의
"""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


# 백엔드에서 전달받는 신분증 종류
class DocumentType(str, Enum):
    PASSPORT = "passport"
    ALIEN_REGISTRATION = "alien_registration_card"


# 신청 정보와 신분증 정보의 필드별 일치 여부
class FieldMatches(BaseModel):
    last_name: bool
    first_name: bool
    birth_date: bool


# 얼굴 비교 및 신청 정보 검증 결과
class IdentityVerificationResponse(BaseModel):
    """본인 인증 API 응답 스키마."""

    exam_id: str = Field(
        ...,
        description="시험 식별자",
    )

    examinee_id: str = Field(
        ...,
        description="응시자 식별자",
    )

    captured_at: datetime = Field(
        ...,
        description="웹캠 이미지 촬영 시각",
    )

    verified: bool = Field(
        ...,
        description="본인 인증 성공 여부",
    )

    # 얼굴 비교 결과
    face_verified: bool = Field(
        ...,
        description="얼굴 비교 성공 여부",
    )

    similarity: float | None = Field(
        ...,
        description="가장 높은 얼굴 유사도",
    )

    threshold: float = Field(
        ...,
        description="본인 인증 판단 기준값",
    )

    matched_face_count: int = Field(
        ...,
        description="기준 유사도 이상으로 일치한 얼굴 수",
    )

    unmatched_face_count: int = Field(
        ...,
        description="기준 유사도 미만으로 일치하지 않은 얼굴 수",
    )

    # 신청 정보 검증 결과
    applicant_verified: bool = Field(
        ...,
        description="신청 정보와 신분증 정보의 일치 여부",
    )

    document_type: DocumentType = Field(
        ...,
        description="신분증 종류",
    )

    field_matches: FieldMatches = Field(
        ...,
        description="필드별 신청 정보 일치 여부",
    )

    message: str = Field(
        ...,
        description="본인 인증 결과 메시지",
    )
