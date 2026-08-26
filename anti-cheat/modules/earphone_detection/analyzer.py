"""
analyzer.py

이어폰 탐지 결과를 분석하여
최종 이어폰 착용 여부를 판단하는 모듈.

처리 과정
1. detector.py의 탐지 결과 입력
2. 이어폰 탐지 신뢰도 임계값 적용
3. 이어폰 착용 여부 판단
4. 최종 분석 결과 생성

※ AWS Rekognition 호출은 detector.py에서 수행한다.
※ 이미지 검증과 전체 흐름 관리는 service.py에서 수행한다.
"""

from typing import Any

from app.core.config import settings


def analyze_ear_visibility(
    detection_response: dict[str, Any],
) -> dict[str, Any]:
    """얼굴 yaw를 기준으로 귀가 충분히 보이는 자세인지 판단한다."""

    face_details = detection_response.get("FaceDetails", [])

    if len(face_details) != 1:
        return {
            "ear_visible": False,
            "face_count": len(face_details),
            "yaw": None,
            "yaw_threshold": (
                settings.pre_exam_earphone_head_yaw_threshold
            ),
        }

    pose = face_details[0].get("Pose", {})
    yaw = float(pose.get("Yaw", 0.0) or 0.0)

    return {
        "ear_visible": (
            abs(yaw)
            >= settings.pre_exam_earphone_head_yaw_threshold
        ),
        "face_count": 1,
        "yaw": round(yaw, 2),
        "yaw_threshold": settings.pre_exam_earphone_head_yaw_threshold,
    }


def analyze_earphone_detection(
    detection_result: dict[str, Any],
) -> dict[str, Any]:
    """이어폰 label 탐지 결과를 분석한다."""

    matched_labels = detection_result.get(
        "matched_labels",
        [],
    )

    valid_detections = _find_valid_detections(
        matched_labels=matched_labels,
        threshold=settings.pre_exam_earphone_confidence_threshold,
    )

    if not valid_detections:
        return {
            "earphone_detected": False,
            "label": None,
            "confidence": 0.0,
            "threshold": settings.pre_exam_earphone_confidence_threshold,
            "retry_required": False,
            "message": "이어폰이 탐지되지 않았습니다.",
        }

    best_detection = max(
        valid_detections,
        key=lambda result: result["confidence"],
    )

    return {
        "earphone_detected": True,
        "label": best_detection["label"],
        "confidence": best_detection["confidence"],
        "threshold": settings.pre_exam_earphone_confidence_threshold,
        "retry_required": False,
        "message": "이어폰이 탐지되었습니다.",
    }


def _find_valid_detections(
    matched_labels: list[dict[str, Any]],
    threshold: float,
) -> list[dict[str, Any]]:
    """임계값을 충족하는 이어폰 탐지 결과를 반환한다."""

    valid_detections = []

    for label_result in matched_labels:
        label_name = label_result.get("label")
        confidence = float(
            label_result.get("confidence", 0.0)
        )

        if confidence < threshold:
            continue

        valid_detections.append(
            {
                "label": label_name,
                "confidence": round(confidence, 2),
                "instances": label_result.get(
                    "instances",
                    [],
                ),
            }
        )

    return valid_detections
