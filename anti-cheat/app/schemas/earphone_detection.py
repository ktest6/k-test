"""
earphone_detection.py

이어폰 탐지 API 응답 스키마.
"""

from pydantic import BaseModel, Field


class EarphoneDetectionResponse(BaseModel):
    """이어폰 탐지 API 응답 스키마."""

    exam_id: str = Field(
        ...,
        description="시험 식별자",
    )

    examinee_id: str = Field(
        ...,
        description="응시자 식별자",
    )

    earphone_detected: bool = Field(
        ...,
        description="최종 이어폰 탐지 여부",
    )

    left_ear_detected: bool = Field(
        ...,
        description="왼쪽 귀 이어폰 탐지 여부",
    )

    right_ear_detected: bool = Field(
        ...,
        description="오른쪽 귀 이어폰 탐지 여부",
    )

    left_label: str | None = Field(
        ...,
        description="왼쪽 귀에서 탐지된 label",
    )

    right_label: str | None = Field(
        ...,
        description="오른쪽 귀에서 탐지된 label",
    )

    left_confidence: float = Field(
        ...,
        description="왼쪽 귀 이어폰 탐지 신뢰도",
    )

    right_confidence: float = Field(
        ...,
        description="오른쪽 귀 이어폰 탐지 신뢰도",
    )

    threshold: float = Field(
        ...,
        description="이어폰 탐지 판단 기준값",
    )

    message: str = Field(
        ...,
        description="이어폰 탐지 결과 메시지",
    )