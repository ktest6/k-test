"""
face_compare.py

AWS Rekognition CompareFaces API 호출 모듈.

- 기준 이미지와 비교 이미지의 얼굴 비교
- AWS API 호출 오류 처리
- CompareFaces 원본 응답 반환
"""

from typing import Any

from botocore.exceptions import BotoCoreError, ClientError

from modules.aws_rekognition.client import rekognition_client
from modules.common.exceptions import RekognitionAPIError


def compare_faces(
    source_image_bytes: bytes,
    target_image_bytes: bytes,
    similarity_threshold: float,
) -> dict[str, Any]:
    """두 이미지의 얼굴을 비교하고 AWS 응답을 반환한다."""

    try:
        response = rekognition_client.compare_faces(
            SourceImage={
                "Bytes": source_image_bytes,
            },
            TargetImage={
                "Bytes": target_image_bytes,
            },
            SimilarityThreshold=similarity_threshold,
        )

    except (BotoCoreError, ClientError) as error:
        raise RekognitionAPIError(
            "AWS Rekognition CompareFaces API 호출에 실패했습니다.",
            code="REKOGNITION_COMPARE_FACES_FAILED",
        ) from error

    return response
