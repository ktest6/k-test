"""
text_detection.py

AWS Rekognition DetectText 호출 모듈.

- 이미지에서 텍스트 검출
- DetectText API 호출
- OCR 결과 반환
"""

from typing import Any

from botocore.exceptions import BotoCoreError, ClientError

from modules.aws_rekognition.client import rekognition_client
from modules.common.exceptions import RekognitionAPIError


# Rekognition DetectText를 호출하고 OCR 결과를 반환한다.
def detect_text(image_bytes: bytes) -> list[dict[str, Any]]:
    try:
        response = rekognition_client.detect_text(
            Image={"Bytes": image_bytes},
        )
    except (BotoCoreError, ClientError) as error:
        raise RekognitionAPIError(
            "AWS Rekognition DetectText 호출에 실패했습니다."
        ) from error

    # DetectText 결과를 parser에서 사용할 공통 형식으로 변환한다.
    return [
        {
            "text": detection.get("DetectedText", ""),
            "type": detection.get("Type", ""),
            "confidence": detection.get("Confidence", 0.0),
            "geometry": detection.get("Geometry", {}),
        }
        for detection in response.get("TextDetections", [])
    ]
