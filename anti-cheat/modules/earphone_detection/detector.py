"""
detector.py

AWS Rekognition DetectLabels를 이용해
귀 이미지에서 이어폰 또는 헤드폰 관련 label을 탐지하는 모듈.

처리 과정
1. 귀 이미지 bytes 입력
2. AWS Rekognition DetectLabels 호출
3. Earbuds, Headphones label 추출
4. confidence와 bounding box 추출
5. 탐지 원본 결과 반환

※ 이미지 검증은 service.py에서 수행한다.
※ 최종 착용 여부 판단은 analyzer.py에서 수행한다.
"""

from typing import Any

from botocore.exceptions import BotoCoreError, ClientError

from modules.aws_rekognition.client import rekognition_client
from modules.common.exceptions import RekognitionAPIError


# 실제 테스트에서 확인된 이어폰 관련 label
EARPHONE_LABEL_NAMES = {
    "Earbuds",
    "Headphones",
}


def detect_earphone(
    image_bytes: bytes,
    # 이어폰 테스트를 위해 설정
    max_labels: int = 100,
    min_confidence: float = 20.0,
    # 기존 사용하던 값
    # max_labels: int = 50,
    # min_confidence: float = 50.0,
) -> dict[str, Any]:
    """
    귀 이미지에서 이어폰 관련 label을 탐지한다.

    Args:
        image_bytes (bytes):
            분석할 귀 이미지 bytes.

        min_confidence (float):
            AWS Rekognition이 반환할 최소 confidence.

    Returns:
        dict[str, Any]:
            이어폰 관련 label 탐지 결과.

    Raises:
        EarphoneDetectionError:
            AWS Rekognition 호출에 실패한 경우.
    """

    try:
        response = rekognition_client.detect_labels(
            Image={"Bytes": image_bytes},
            MaxLabels=max_labels,
            MinConfidence=min_confidence,
        )

    except (BotoCoreError, ClientError) as error:
        raise RekognitionAPIError(
            "AWS Rekognition 이어폰 탐지에 실패했습니다."
        ) from error

    labels = response.get("Labels", [])
    matched_labels = _extract_earphone_labels(labels)

    return {
        "detected": len(matched_labels) > 0,
        "matched_labels": matched_labels,
    }


def _extract_earphone_labels(
    labels: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """전체 label에서 이어폰 관련 label만 추출한다."""

    matched_labels = []

    for label in labels:
        label_name = label.get("Name")

        if label_name not in EARPHONE_LABEL_NAMES:
            continue

        matched_labels.append(
            {
                "label": label_name,
                "confidence": round(
                    float(label.get("Confidence", 0.0)),
                    2,
                ),
                "instances": _extract_instances(
                    label.get("Instances", [])
                ),
            }
        )

    return matched_labels


def _extract_instances(
    instances: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """탐지된 객체의 confidence와 bounding box를 추출한다."""

    extracted_instances = []

    for instance in instances:
        bounding_box = instance.get("BoundingBox", {})

        extracted_instances.append(
            {
                "confidence": round(
                    float(instance.get("Confidence", 0.0)),
                    2,
                ),
                "bounding_box": {
                    "width": bounding_box.get("Width", 0.0),
                    "height": bounding_box.get("Height", 0.0),
                    "left": bounding_box.get("Left", 0.0),
                    "top": bounding_box.get("Top", 0.0),
                },
            }
        )

    return extracted_instances