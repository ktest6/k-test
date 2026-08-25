"""
detector.py

AWS Rekognition DetectLabels를 이용해
시험 중 프레임에서 금지 객체 관련 label을 탐지하는 모듈.

처리 과정

1. 현재 프레임 이미지 bytes 입력
2. AWS Rekognition DetectLabels 호출
3. Mobile Phone, Earbuds, Headphones label 추출
4. confidence 추출
5. 탐지 원본 결과 반환

※ 이미지 검증은 cheating_detection/service.py에서 수행한다.
※ 최종 객체 탐지 여부 판단은 analyzer.py에서 수행한다.
"""

from typing import Any

from botocore.exceptions import BotoCoreError, ClientError

from modules.aws_rekognition.client import rekognition_client
from modules.common.exceptions import RekognitionAPIError


OBJECT_LABEL_NAMES = {
    "Mobile Phone",
    "Earbuds",
    "Headphones",
}


def detect_objects(
    image_bytes: bytes,
    max_labels: int = 100,
    min_confidence: float = 20.0,
) -> dict[str, Any]:
    """현재 프레임에서 모니터링 대상 객체 label을 탐지한다."""

    try:
        response = rekognition_client.detect_labels(
            Image={"Bytes": image_bytes},
            MaxLabels=max_labels,
            MinConfidence=min_confidence,
        )

    except (BotoCoreError, ClientError) as error:
        raise RekognitionAPIError(
            "AWS Rekognition 객체 탐지에 실패했습니다.",
            code="REKOGNITION_OBJECT_DETECTION_FAILED",
        ) from error

    labels = response.get("Labels", [])

    matched_labels = _extract_object_labels(
        labels,
    )

    return {
        "detected": len(matched_labels) > 0,
        "matched_labels": matched_labels,
    }


def _extract_object_labels(
    labels: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """전체 label에서 현재 모니터링 대상 객체만 추출한다."""

    matched_labels = []

    for label in labels:
        label_name = label.get("Name")

        if label_name not in OBJECT_LABEL_NAMES:
            continue

        matched_labels.append(
            {
                "label": label_name,
                "confidence": round(
                    float(label.get("Confidence", 0.0)),
                    2,
                ),
            }
        )

    return matched_labels
