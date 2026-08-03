"""
run_gaze_monitor.py

로컬 얼굴 이미지로 시선 탐지와 연속 이탈 상태를 확인한다.
"""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(PROJECT_ROOT))

from app.core.config import settings
from modules.cheating_detection.face_detection import detect_faces
from modules.cheating_detection.face_monitor import analyze_face_monitor
from modules.cheating_detection.gaze_monitor import analyze_gaze_monitor
from modules.cheating_detection.gaze_state import (
    clear_gaze_state,
    update_gaze_state,
)
from modules.common.exceptions import ProctoringError


SUPPORTED_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}

# 분석할 이미지 파일 또는 이미지 디렉터리 경로를 입력한다.
INPUT_IMAGE_PATHS = [
    PROJECT_ROOT / "data" / "gaze" / "gaze_test_3_img",
]


def natural_sort_key(path: Path) -> tuple[tuple[int, str | int], ...]:
    """파일명에 포함된 숫자를 수치 순서로 정렬할 키를 만든다."""

    parts = re.split(r"(\d+)", path.name.lower())
    return tuple(
        (1, int(part)) if part.isdigit() else (0, part)
        for part in parts
    )


def parse_arguments() -> argparse.Namespace:
    """명령행에서 이미지와 상태 식별 정보를 읽는다."""

    parser = argparse.ArgumentParser(
        description=(
            "얼굴 이미지 또는 이미지 디렉터리를 입력받아 "
            "시선 탐지 결과를 출력합니다."
        )
    )
    parser.add_argument(
        "image_paths",
        nargs="*",
        type=Path,
        help=(
            "분석할 이미지 파일 또는 이미지 디렉터리. "
            "생략하면 INPUT_IMAGE_PATHS를 사용합니다."
        ),
    )
    parser.add_argument("--exam-id", default="gaze_test_exam")
    parser.add_argument("--examinee-id", default="gaze_test_examinee")
    parser.add_argument(
        "--frame-interval-ms",
        type=int,
        default=1000,
        help="이미지 사이의 시험 경과 시간 간격(ms)",
    )
    return parser.parse_args()


def collect_image_paths(input_paths: Sequence[Path]) -> list[Path]:
    """입력 파일과 디렉터리에서 분석할 이미지 목록을 만든다."""

    image_paths: list[Path] = []

    for input_path in input_paths:
        if not input_path.exists():
            raise FileNotFoundError(f"입력 경로가 없습니다: {input_path}")

        if input_path.is_file():
            candidates = [input_path]
        elif input_path.is_dir():
            candidates = sorted(
                (path for path in input_path.iterdir() if path.is_file()),
                key=natural_sort_key,
            )
        else:
            candidates = []

        image_paths.extend(
            path
            for path in candidates
            if path.suffix.lower() in SUPPORTED_IMAGE_SUFFIXES
        )

    if not image_paths:
        raise ValueError("분석할 JPG, JPEG 또는 PNG 이미지가 없습니다.")

    return image_paths


def analyze_image(
    image_path: Path,
    exam_id: str,
    examinee_id: str,
    capture_sequence: int,
    elapsed_ms: int,
) -> dict[str, object]:
    """이미지 한 장을 분석하고 시선 상태를 갱신한다."""

    image_bytes = image_path.read_bytes()

    # 프레임당 DetectFaces는 한 번만 호출한다.
    detection_response = detect_faces(image_bytes=image_bytes)
    face_monitor_result = analyze_face_monitor(detection_response)

    gaze_monitor_result = analyze_gaze_monitor(
        face_monitor_result=face_monitor_result,
        eye_yaw_threshold=settings.gaze_eye_yaw_threshold,
        eye_pitch_threshold=settings.gaze_eye_pitch_threshold,
        head_yaw_threshold=settings.gaze_head_yaw_threshold,
        head_pitch_threshold=settings.gaze_head_pitch_threshold,
        minimum_eye_confidence=settings.gaze_minimum_eye_confidence,
    )
    gaze_state_result = update_gaze_state(
        exam_id=exam_id,
        examinee_id=examinee_id,
        gaze_monitor_result=gaze_monitor_result,
        elapsed_ms=elapsed_ms,
        capture_sequence=capture_sequence,
        persistent_count_threshold=(
            settings.gaze_persistent_count_threshold
        ),
    )

    return {
        "image_path": str(image_path),
        "capture_sequence": capture_sequence,
        "elapsed_ms": elapsed_ms,
        "face_monitor": {
            "face_count": face_monitor_result["face_count"],
            "event_type": face_monitor_result["event_type"],
        },
        "gaze_monitor": gaze_monitor_result,
        "gaze_state": gaze_state_result,
    }


def main() -> int:
    """입력 이미지를 순서대로 분석하고 결과를 터미널에 출력한다."""

    arguments = parse_arguments()

    if arguments.frame_interval_ms < 1:
        print("[입력 오류] --frame-interval-ms는 1 이상이어야 합니다.")
        return 2

    try:
        input_paths = arguments.image_paths or INPUT_IMAGE_PATHS
        image_paths = collect_image_paths(input_paths)
        clear_gaze_state(arguments.exam_id, arguments.examinee_id)

        print(
            json.dumps(
                {
                    "exam_id": arguments.exam_id,
                    "examinee_id": arguments.examinee_id,
                    "image_count": len(image_paths),
                    "thresholds": {
                        "eye_yaw": settings.gaze_eye_yaw_threshold,
                        "eye_pitch": settings.gaze_eye_pitch_threshold,
                        "head_yaw": settings.gaze_head_yaw_threshold,
                        "head_pitch": settings.gaze_head_pitch_threshold,
                        "minimum_eye_confidence": (
                            settings.gaze_minimum_eye_confidence
                        ),
                        "persistent_count": (
                            settings.gaze_persistent_count_threshold
                        ),
                    },
                },
                ensure_ascii=False,
                indent=2,
            )
        )

        for capture_sequence, image_path in enumerate(
            image_paths,
            start=1,
        ):
            result = analyze_image(
                image_path=image_path,
                exam_id=arguments.exam_id,
                examinee_id=arguments.examinee_id,
                capture_sequence=capture_sequence,
                elapsed_ms=(
                    (capture_sequence - 1) * arguments.frame_interval_ms
                ),
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))

    except (FileNotFoundError, OSError, ValueError) as error:
        print(f"[입력 오류] {error}")
        return 2
    except ProctoringError as error:
        print(f"[시선 탐지 오류] {error}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
