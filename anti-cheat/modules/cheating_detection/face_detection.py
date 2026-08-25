"""
face_detection.py

AWS Rekognition DetectFaces API 호출 모듈.

- 시험 중 캡처 이미지의 얼굴 분석
- AWS API 호출 오류 처리
- DetectFaces 원본 응답 반환
"""

from typing import Any

from botocore.exceptions import BotoCoreError, ClientError

from modules.aws_rekognition.client import rekognition_client
from modules.common.exceptions import RekognitionAPIError
from modules.common.image_validation import validate_image_bytes


def detect_faces(
    image_bytes: bytes,
) -> dict[str, Any]:
    """이미지에서 얼굴을 탐지하고 AWS 응답을 반환한다."""

    validate_image_bytes(
        image_bytes=image_bytes,
        image_name="시험 모니터링 프레임",
        image_key="currentImage",
    )

    try:
        response = rekognition_client.detect_faces(
            Image={
                "Bytes": image_bytes,
            },
            Attributes=[
                "ALL",
            ],
        )

    except (BotoCoreError, ClientError) as error:
        raise RekognitionAPIError(
            "AWS Rekognition DetectFaces API 호출에 실패했습니다.",
            code="REKOGNITION_DETECT_FACES_FAILED",
        ) from error

    return response
