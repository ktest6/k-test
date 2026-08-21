"""
run_gaze_calibration.py

화면 중앙을 바라본 로컬 얼굴 이미지로 응시자별 시선 기준점을 생성한다.
"""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(PROJECT_ROOT))


from app.core.config import settings
from modules.cheating_detection.face_detection import detect_faces
from modules.cheating_detection.face_monitor import analyze_face_monitor
from modules.cheating_detection.gaze_calibration import (
    create_gaze_calibration,
)
from modules.cheating_detection.gaze_monitor import extract_eye_direction
from modules.common.exceptions import ProctoringError


CALIBRATION_IMAGE_DIRECTORY = (
    PROJECT_ROOT / "data" / "gaze_center"
)

EXAM_ID = "gaze_calibration_test_exam"
EXAMINEE_ID = "gaze_calibration_test_examinee"

SUPPORTED_IMAGE_SUFFIXES = {
    ".jpg",
    ".jpeg",
    ".png",
}

def natural_sort_key(
    path: Path,
) -> tuple[tuple[int, str | int], ...]:
    """파일명의 숫자를 수치 순서로 정렬할 키를 생성한다."""

    parts = re.split(
        r"(\d+)",
        path.name.lower(),
    )

    return tuple(
        (1, int(part))
        if part.isdigit()
        else (0, part)
        for part in parts
    )


def collect_image_paths(
    image_directory: Path,
) -> list[Path]:
    """Calibration 폴더에서 지원하는 이미지를 자연 정렬해 반환한다."""

    if not image_directory.exists():
        raise FileNotFoundError(
            f"Calibration 이미지 폴더가 없습니다: "
            f"{image_directory}"
        )

    if not image_directory.is_dir():
        raise ValueError(
            f"Calibration 이미지 경로가 디렉터리가 아닙니다: "
            f"{image_directory}"
        )

    image_paths = sorted(
        (
            path
            for path in image_directory.iterdir()
            if (
                path.is_file()
                and path.suffix.lower()
                in SUPPORTED_IMAGE_SUFFIXES
            )
        ),
        key=natural_sort_key,
    )

    if not image_paths:
        raise ValueError(
            "Calibration에 사용할 "
            "JPG, JPEG 또는 PNG 이미지가 없습니다."
        )

    return image_paths


def read_image_bytes(
    image_path: Path,
) -> bytes:
    """Calibration 이미지를 bytes로 읽는다."""

    try:
        return image_path.read_bytes()

    except OSError as error:
        raise OSError(
            f"Calibration 이미지를 읽을 수 없습니다: "
            f"{image_path}"
        ) from error


def parse_arguments() -> argparse.Namespace:
    """명령행에서 Calibration 이미지 폴더를 읽는다."""

    parser = argparse.ArgumentParser(
        description=(
            "화면 중앙을 바라본 이미지로 "
            "응시자별 시선 Calibration을 생성합니다."
        )
    )

    parser.add_argument(
        "image_directory",
        nargs="?",
        type=Path,
        default=CALIBRATION_IMAGE_DIRECTORY,
        help=(
            "Calibration 이미지 디렉터리. "
            "생략하면 CALIBRATION_IMAGE_DIRECTORY를 사용합니다."
        ),
    )

    return parser.parse_args()


def create_sample_result(
    image_path: Path,
    face_monitor_result: dict[str, Any],
) -> dict[str, Any]:
    """프레임의 EyeDirection 값을 테스트 결과용으로 추출한다."""

    face_count = face_monitor_result.get(
        "face_count",
        0,
    )

    face_details = face_monitor_result.get(
        "face_details",
        [],
    )

    sample_result = {
        "image": image_path.name,
        "face_count": face_count,
        "yaw": None,
        "pitch": None,
        "confidence": None,
        "used_for_calibration": False,
    }

    if (
        face_count != 1
        or not isinstance(face_details, list)
        or not face_details
        or not isinstance(face_details[0], dict)
    ):
        return sample_result

    eye_direction = extract_eye_direction(
        face_detail=face_details[0],
    )

    confidence = eye_direction["confidence"]

    sample_result.update(
        {
            "yaw": eye_direction["yaw"],
            "pitch": eye_direction["pitch"],
            "confidence": confidence,
            "used_for_calibration": (
                confidence
                >= settings.gaze_minimum_eye_confidence
            ),
        }
    )

    return sample_result


def create_sample_statistics(
    samples: list[dict[str, Any]],
    calibration_result: dict[str, Any],
) -> dict[str, Any]:
    """Calibration에 사용된 sample의 범위를 계산한다."""

    valid_samples = [
        sample
        for sample in samples
        if sample.get("used_for_calibration") is True
    ]

    yaw_values = [
        float(sample["yaw"])
        for sample in valid_samples
        if sample.get("yaw") is not None
    ]

    pitch_values = [
        float(sample["pitch"])
        for sample in valid_samples
        if sample.get("pitch") is not None
    ]

    return {
        "yaw": {
            "median": calibration_result.get(
                "eye_yaw_center"
            ),
            "min": min(yaw_values),
            "max": max(yaw_values),
        },
        "pitch": {
            "median": calibration_result.get(
                "eye_pitch_center"
            ),
            "min": min(pitch_values),
            "max": max(pitch_values),
        },
    }


def run_calibration(
    image_directory: Path,
) -> dict[str, Any]:
    """이미지를 분석해 Calibration을 생성하고 결과를 검증한다."""

    image_paths = collect_image_paths(
        image_directory,
    )

    face_monitor_results: list[dict[str, Any]] = []
    samples: list[dict[str, Any]] = []

    for image_path in image_paths:
        image_bytes = read_image_bytes(
            image_path,
        )

        # Calibration 이미지당 DetectFaces는 한 번만 호출한다.
        detection_response = detect_faces(
            image_bytes=image_bytes,
        )

        face_monitor_result = analyze_face_monitor(
            detection_response,
        )

        face_monitor_results.append(
            face_monitor_result
        )

        samples.append(
            create_sample_result(
                image_path=image_path,
                face_monitor_result=face_monitor_result,
            )
        )

    calibration_result = create_gaze_calibration(
        exam_id=EXAM_ID,
        examinee_id=EXAMINEE_ID,
        face_monitor_results=face_monitor_results,
        minimum_eye_confidence=(
            settings.gaze_minimum_eye_confidence
        ),
        minimum_sample_count=(
            settings.gaze_calibration_minimum_sample_count
        ),
    )

    statistics = create_sample_statistics(
        samples=samples,
        calibration_result=calibration_result,
    )

    return {
        "exam_id": EXAM_ID,
        "examinee_id": EXAMINEE_ID,
        "image_directory": str(
            image_directory.resolve()
        ),
        "input_image_count": len(
            image_paths
        ),
        "minimum_eye_confidence": (
            settings.gaze_minimum_eye_confidence
        ),
        "minimum_sample_count": (
            settings.gaze_calibration_minimum_sample_count
        ),
        "samples": samples,
        "statistics": statistics,
        "calibration": calibration_result,
    }


def main() -> int:
    """Calibration을 실행하고 최종 결과를 JSON으로 한 번 출력한다."""

    arguments = parse_arguments()

    try:
        result = run_calibration(
            arguments.image_directory
        )

        print(
            json.dumps(
                result,
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        )

    except (
        FileNotFoundError,
        OSError,
        ValueError,
    ) as error:
        print(
            f"[입력 오류] {error}"
        )
        return 2

    except ProctoringError as error:
        print(
            f"[Calibration 오류] {error}"
        )
        return 1

    except Exception as error:
        print(
            f"[예상하지 못한 오류] {error}"
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
