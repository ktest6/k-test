"""
service.py

시험 전 이어폰 탐지 전체 흐름을 관리하는 서비스 모듈.

처리 과정
1. 귀 이미지 bytes 검증
2. AWS Rekognition 이어폰 label 탐지
3. 탐지 결과 분석
4. 최종 이어폰 착용 여부 반환

※ 왼쪽·오른쪽 귀 이미지를 한 번에 받을지,
   각각 받을지는 추후 API 계층에서 결정한다.
"""

from typing import Any

from app.core.config import settings
from modules.cheating_detection.face_detection import detect_faces
from modules.common.image_validation import validate_image_bytes
from modules.earphone_detection.analyzer import (
    analyze_earphone_detection,
    analyze_ear_visibility,
)
from modules.earphone_detection.detector import (
    detect_earphone,
)


def analyze_earphone_image(
    image_bytes: bytes,
    image_name: str = "귀",
    image_key: str = "earImage",
) -> dict[str, Any]:
    """귀 이미지 한 장을 분석하여 이어폰 착용 여부를 반환한다."""

    validate_image_bytes(
        image_bytes=image_bytes,
        image_name=image_name,
        image_key=image_key,
    )

    face_detection_result = detect_faces(image_bytes=image_bytes)
    visibility_result = analyze_ear_visibility(
        detection_response=face_detection_result,
    )

    if not visibility_result["ear_visible"]:
        return {
            **visibility_result,
            "earphone_detected": False,
            "label": None,
            "confidence": 0.0,
            "threshold": settings.pre_exam_earphone_confidence_threshold,
            "message": "얼굴을 옆으로 돌려 귀를 보여 주세요.",
        }

    detection_result = detect_earphone(
        image_bytes=image_bytes,
    )

    analysis_result = analyze_earphone_detection(
        detection_result=detection_result,
    )

    return {**visibility_result, **analysis_result}
