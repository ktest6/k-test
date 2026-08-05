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

from modules.common.image_validation import validate_image_bytes
from modules.earphone_detection.analyzer import (
    analyze_earphone_detection,
)
from modules.earphone_detection.detector import (
    detect_earphone,
)


def analyze_earphone_image(
    image_bytes: bytes,
    image_name: str = "귀",
) -> dict[str, Any]:
    """귀 이미지 한 장을 분석하여 이어폰 착용 여부를 반환한다."""

    validate_image_bytes(
        image_bytes=image_bytes,
        image_name=image_name,
    )

    detection_result = detect_earphone(
        image_bytes=image_bytes,
    )

    analysis_result = analyze_earphone_detection(
        detection_result=detection_result,
    )

    return analysis_result