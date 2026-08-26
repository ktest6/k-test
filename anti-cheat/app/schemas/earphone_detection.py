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

    inspection_complete: bool = Field(
        ...,
        description="양쪽 귀가 보이는 자세에서 검사가 완료되었는지 여부",
    )

    left_ear_visible: bool = Field(
        ...,
        description="왼쪽 귀 이미지의 자세 조건 충족 여부",
    )

    right_ear_visible: bool = Field(
        ...,
        description="오른쪽 귀 이미지의 자세 조건 충족 여부",
    )

    left_yaw: float | None = Field(
        ...,
        description="왼쪽 귀 이미지에서 측정한 얼굴 yaw",
    )

    right_yaw: float | None = Field(
        ...,
        description="오른쪽 귀 이미지에서 측정한 얼굴 yaw",
    )

    yaw_threshold: float = Field(
        ...,
        description="귀 노출 여부를 판단하는 yaw 절댓값 기준",
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
