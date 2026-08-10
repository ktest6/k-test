"""
analyzer.py

시험 중 객체 탐지 결과를 분석하여
휴대폰 및 이어폰 탐지 여부를 판단하는 모듈.

처리 과정

1. detector.py의 객체 탐지 결과 입력
2. 휴대폰 탐지 신뢰도 임계값 적용
3. 고개 방향 조건을 만족하는 경우 이어폰 탐지 결과 평가
4. 최종 객체 탐지 결과 생성

※ AWS Rekognition 호출은 detector.py에서 수행한다.
"""

from typing import Any

from app.core.config import settings


PHONE_LABEL = "Mobile Phone"

EARPHONE_LABELS = {
    "Earbuds",
    "Headphones",
}


def analyze_object_detection(
    detection_result: dict[str, Any],
    head_pose: dict[str, Any],
) -> dict[str, Any]:
    """객체 label 탐지 결과를 분석한다."""

    matched_labels = detection_result.get(
        "matched_labels",
        [],
    )

    detected_objects: list[dict[str, Any]] = []

    head_yaw = float(
        head_pose.get("yaw", 0.0) or 0.0
    )

    for label_result in matched_labels:
        label = label_result.get("label")
        confidence = float(
            label_result.get("confidence", 0.0)
        )

        # 휴대폰은 고개 방향과 관계없이 검사
        if (
            label == PHONE_LABEL
            and confidence >= settings.phone_confidence_threshold
        ):
            detected_objects.append(
                {
                    "object_type": "PHONE",
                    "label": label,
                    "confidence": round(confidence, 2),
                }
            )

        # 이어폰은 귀가 충분히 노출될 수 있는 자세에서만 검사
        elif (
            label in EARPHONE_LABELS
            and abs(head_yaw)
            >= settings.earphone_head_yaw_threshold
            and confidence
            >= settings.earphone_confidence_threshold
        ):
            detected_objects.append(
                {
                    "object_type": "EARPHONE",
                    "label": label,
                    "confidence": round(confidence, 2),
                }
            )

    return {
        "detected_objects": detected_objects,
    }