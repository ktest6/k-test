"""폴더의 각도별 이미지로 시험 전 이어폰 탐지를 일괄 분석한다.

운영 API와 달리 yaw 미충족 이미지도 DetectLabels를 호출한다. 이는 각도별
오탐·미탐과 confidence를 비교하기 위한 진단 스크립트이기 때문이다.
"""

from __future__ import annotations

import json
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any

import cv2
import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(PROJECT_ROOT))

from app.core.config import settings
from modules.cheating_detection.face_detection import detect_faces
from modules.common.image_validation import validate_image_bytes
from modules.earphone_detection.analyzer import (
    analyze_ear_visibility,
    analyze_earphone_detection,
)
from modules.earphone_detection.detector import detect_earphone


SUPPORTED_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
# 아래 경로를 분석할 이미지 폴더의 절대 경로로 수정한 뒤 실행한다.
INPUT_FOLDER_PATH = Path(
    "/Users/apple/dio_folder/python/ktest_git/k-test/anti-cheat/data/camera_recordings/camera_20260826_225619_417367_1_img"
)
TEXT_COLOR = (255, 255, 255)
BACKGROUND_COLOR = (0, 0, 0)


def find_image_paths(input_folder: Path) -> list[Path]:
    """입력 폴더 바로 아래에서 지원 이미지 파일을 이름순으로 찾는다."""

    if not input_folder.is_dir():
        raise NotADirectoryError(
            f"입력 이미지 폴더를 찾을 수 없습니다: {input_folder}"
        )

    image_paths = sorted(
        path
        for path in input_folder.iterdir()
        if path.is_file() and path.suffix.lower() in SUPPORTED_IMAGE_SUFFIXES
    )

    if not image_paths:
        raise RuntimeError(
            f"지원하는 이미지 파일이 없습니다: {input_folder}"
        )

    return image_paths


def find_best_raw_detection(
    detection_result: dict[str, Any],
) -> dict[str, Any]:
    """AWS가 반환한 이어폰 관련 라벨 중 confidence가 가장 높은 값을 찾는다."""

    matched_labels = detection_result.get("matched_labels", [])

    if not matched_labels:
        return {
            "aws_label_detected": False,
            "aws_label": None,
            "aws_confidence": 0.0,
        }

    best_detection = max(
        matched_labels,
        key=lambda item: float(item.get("confidence", 0.0) or 0.0),
    )
    return {
        "aws_label_detected": True,
        "aws_label": best_detection.get("label"),
        "aws_confidence": round(
            float(best_detection.get("confidence", 0.0) or 0.0),
            2,
        ),
    }


def analyze_image(image_path: Path) -> dict[str, Any]:
    """한 이미지의 얼굴 pose와 이어폰 라벨 결과를 분석한다."""

    image_bytes = image_path.read_bytes()
    validate_image_bytes(
        image_bytes=image_bytes,
        image_name=image_path.name,
        image_key="batchTestImage",
    )

    # 이미지당 DetectFaces와 DetectLabels는 각각 한 번만 호출한다.
    face_response = detect_faces(image_bytes=image_bytes)
    visibility_result = analyze_ear_visibility(face_response)
    label_response = detect_earphone(
        image_bytes=image_bytes,
        min_confidence=0.0,
    )
    raw_detection = find_best_raw_detection(label_response)
    thresholded_detection = analyze_earphone_detection(label_response)

    return {
        "file_name": image_path.name,
        "face_count": visibility_result["face_count"],
        "yaw": visibility_result["yaw"],
        "yaw_threshold": visibility_result["yaw_threshold"],
        "yaw_threshold_met": visibility_result["ear_visible"],
        "earphone_detected": thresholded_detection["earphone_detected"],
        "earphone_label": thresholded_detection["label"],
        "earphone_confidence": thresholded_detection["confidence"],
        "earphone_confidence_threshold": thresholded_detection["threshold"],
        **raw_detection,
    }


def draw_result_overlay(
    image_path: Path,
    result: dict[str, Any],
) -> cv2.typing.MatLike:
    """원본 이미지 좌측 상단에 각도와 이어폰 분석 결과를 표시한다."""

    image_bytes = image_path.read_bytes()
    image_array = np.frombuffer(image_bytes, dtype=np.uint8)
    image = cv2.imdecode(image_array, cv2.IMREAD_COLOR)

    if image is None:
        raise RuntimeError(f"결과 이미지를 읽지 못했습니다: {image_path}")

    lines = [
        f"Pose.Yaw: {result['yaw']}",
        (
            f"Yaw threshold / met: {result['yaw_threshold']} / "
            f"{result['yaw_threshold_met']}"
        ),
        f"Earphone detected: {result['earphone_detected']}",
        (
            "Confidence threshold: "
            f"{result['earphone_confidence_threshold']}"
        ),
        f"AWS label: {result['aws_label']}",
        f"AWS confidence: {result['aws_confidence']:.2f}",
    ]
    font = cv2.FONT_HERSHEY_SIMPLEX
    font_scale = max(0.45, min(image.shape[:2]) / 900.0)
    thickness = 1 if font_scale < 0.7 else 2
    line_height = int(30 * max(font_scale, 0.6))
    padding = 12
    text_width = max(
        cv2.getTextSize(line, font, font_scale, thickness)[0][0]
        for line in lines
    )
    box_height = padding * 2 + line_height * len(lines)
    overlay = image.copy()
    cv2.rectangle(
        overlay,
        (0, 0),
        (min(image.shape[1], text_width + padding * 2), box_height),
        BACKGROUND_COLOR,
        thickness=-1,
    )
    cv2.addWeighted(overlay, 0.7, image, 0.3, 0, image)

    for index, line in enumerate(lines):
        cv2.putText(
            image,
            line,
            (padding, padding + line_height * (index + 1) - 6),
            font,
            font_scale,
            TEXT_COLOR,
            thickness,
            cv2.LINE_AA,
        )

    return image


def create_output_directory(input_folder: Path) -> Path:
    """입력 이미지 폴더 안에 result 폴더를 만든다."""

    output_directory = input_folder / "result"
    output_directory.mkdir(parents=True, exist_ok=True)
    return output_directory


def save_annotated_image(
    image_path: Path,
    result: dict[str, Any],
    output_directory: Path,
) -> Path:
    """분석 결과가 표시된 이미지를 결과 폴더에 JPEG로 저장한다."""

    annotated_image = draw_result_overlay(image_path, result)
    output_path = output_directory / f"{image_path.name}_analyzed.jpg"

    if not cv2.imwrite(str(output_path), annotated_image):
        raise RuntimeError(f"결과 이미지를 저장하지 못했습니다: {output_path}")

    return output_path


def build_summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    """폴더 전체 분석 결과의 요약 수치를 생성한다."""

    return {
        "total_images": len(results),
        "yaw_threshold_met_count": sum(
            bool(result["yaw_threshold_met"]) for result in results
        ),
        "earphone_detected_count": sum(
            bool(result["earphone_detected"]) for result in results
        ),
        "aws_label_detected_count": sum(
            bool(result["aws_label_detected"]) for result in results
        ),
    }


def run_batch(input_folder: Path) -> Path:
    """입력 폴더 전체를 분석하고 결과 폴더 경로를 반환한다."""

    resolved_input = input_folder.expanduser().resolve()
    image_paths = find_image_paths(resolved_input)
    output_directory = create_output_directory(resolved_input)
    results: list[dict[str, Any]] = []

    for index, image_path in enumerate(image_paths, start=1):
        print(f"[{index}/{len(image_paths)}] 분석 중: {image_path.name}")

        try:
            result = analyze_image(image_path)
            annotated_path = save_annotated_image(
                image_path,
                result,
                output_directory,
            )
            result["status"] = "success"
            result["annotated_image"] = str(annotated_path)

        except Exception as error:
            result = {
                "file_name": image_path.name,
                "status": "failed",
                "error_type": type(error).__name__,
                "error": str(error),
            }

        results.append(result)

    successful_results = [
        result for result in results if result["status"] == "success"
    ]
    payload = {
        "input_folder": str(resolved_input),
        "output_folder": str(output_directory),
        "analyzed_at": datetime.now().astimezone().isoformat(),
        "thresholds": {
            "pre_exam_yaw": (
                settings.pre_exam_earphone_head_yaw_threshold
            ),
            "earphone_confidence": settings.earphone_confidence_threshold,
        },
        "summary": {
            **build_summary(successful_results),
            "failed_count": len(results) - len(successful_results),
        },
        "results": results,
    }
    json_path = output_directory / "results.json"

    with json_path.open("w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=4)

    print(json.dumps(payload["summary"], ensure_ascii=False, indent=4))
    print(f"결과 JSON: {json_path}")
    print(f"결과 이미지 폴더: {output_directory}")
    return output_directory


def main() -> int:
    """폴더 일괄 분석 CLI를 실행한다."""

    try:
        run_batch(INPUT_FOLDER_PATH)
        return 0

    except Exception:
        print("이어폰 폴더 일괄 분석에 실패했습니다.")
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
