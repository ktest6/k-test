"""
identity.py

본인 인증 API 응답 스키마.
"""

from datetime import datetime

from pydantic import BaseModel, Field


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

    message: str = Field(
        ...,
        description="본인 인증 결과 메시지",
    )