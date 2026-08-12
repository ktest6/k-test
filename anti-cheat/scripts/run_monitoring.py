"""
run_monitoring.py

시험 중 모니터링 기능을 로컬 이미지로 테스트하는 실행 파일.

기능
- 현재 프레임 이미지 폴더 로드
- 선택적으로 기준 얼굴 이미지 로드
- 이미지 순서대로 모니터링 서비스 실행
- 전체 모니터링 결과 JSON 저장 및 출력

※ 실제 프로젝트에서는 프론트엔드가 전달한 이미지 bytes를 사용한다.
※ 이 파일은 모니터링 모듈 단독 테스트용이다.
"""

import json
import re
import sys
import traceback
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo


# 프로젝트 루트 경로
PROJECT_ROOT = Path(__file__).resolve().parents[1]

# 프로젝트 모듈 import를 위한 경로 추가
sys.path.append(str(PROJECT_ROOT))


from modules.cheating_detection.service import analyze_monitoring_frame
from modules.common.exceptions import ProctoringError


# 테스트 환경 설정
EXAM_ID = "exam_002"
EXAMINEE_ID = "examinee_002"
REQUEST_ID = "request_monitoring_002"

# 프레임 간 시험 경과 시간(ms)
FRAME_INTERVAL_MS = 5000

TEST_IMAGE_DIRECTORY = "cheat_vid_5_img"

# 현재 프레임 테스트 이미지 폴더
CURRENT_IMAGE_DIRECTORY = (
    PROJECT_ROOT / "data" / "gaze" / TEST_IMAGE_DIRECTORY
)

REFERENCE_IMAGE = "target_true.jpg"

# 동일인 검사 실행 여부
RUN_IDENTITY_CHECK = False

# 백엔드가 저장했다가 모니터링 요청에 전달할 Calibration 값.
EYE_YAW_CENTER = None
EYE_PITCH_CENTER = None

# 본인 인증 시 저장한 기준 이미지
REFERENCE_IMAGE_PATH = (
    PROJECT_ROOT / "data" / "compare" / REFERENCE_IMAGE
)

# 시험 로그 저장 폴더
EXAM_LOG_DIR = (
    PROJECT_ROOT / "data" / "logs" / EXAM_ID
)

RESULT_FILE_PATH = (
    EXAM_LOG_DIR
    / f"monitoring_test_result_{REQUEST_ID}.json"
)

# 테스트 이미지 촬영 시각
TIMEZONE = ZoneInfo("Asia/Seoul")

SUPPORTED_IMAGE_SUFFIXES = {
    ".jpg",
    ".jpeg",
    ".png",
}


def natural_sort_key(
    path: Path,
) -> tuple[tuple[int, str | int], ...]:
    """파일명에 포함된 숫자를 기준으로 자연 정렬한다."""

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
    """이미지 폴더에서 테스트할 이미지 목록을 반환한다."""

    if not image_directory.exists():
        raise FileNotFoundError(
            f"이미지 폴더가 존재하지 않습니다: "
            f"{image_directory}"
        )

    if not image_directory.is_dir():
        raise ValueError(
            f"이미지 경로가 폴더가 아닙니다: "
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
            "분석할 JPG, JPEG 또는 PNG 이미지가 없습니다."
        )

    return image_paths


def read_image_bytes(
    image_path: Path,
    image_name: str,
) -> bytes:
    """이미지 파일을 읽어 bytes로 반환한다."""

    if not image_path.exists():
        raise FileNotFoundError(
            f"{image_name} 파일이 존재하지 않습니다: "
            f"{image_path}"
        )

    if not image_path.is_file():
        raise ValueError(
            f"{image_name} 경로가 파일이 아닙니다: "
            f"{image_path}"
        )

    try:
        return image_path.read_bytes()

    except OSError as error:
        raise OSError(
            f"{image_name} 파일을 읽을 수 없습니다: "
            f"{image_path}"
        ) from error


def prepare_exam_log_directory() -> None:
    """로컬 테스트를 위한 시험 로그 폴더를 준비한다."""

    EXAM_LOG_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )


def save_monitoring_result(
    result: dict[str, object],
    output_path: Path,
) -> None:
    """전체 모니터링 결과를 로컬 JSON 파일로 저장한다."""

    output_path.write_text(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )


def main() -> None:
    """로컬 이미지 폴더로 모니터링 전체 흐름을 테스트한다."""

    try:
        prepare_exam_log_directory()

        image_paths = collect_image_paths(
            image_directory=CURRENT_IMAGE_DIRECTORY,
        )

        reference_image_bytes = None

        if RUN_IDENTITY_CHECK:
            reference_image_bytes = read_image_bytes(
                image_path=REFERENCE_IMAGE_PATH,
                image_name="기준 얼굴 이미지",
            )

        started_at = datetime.now(
            TIMEZONE,
        )

        monitoring_results = []
        previous_gaze_state = None

        for capture_sequence, image_path in enumerate(
            image_paths,
            start=1,
        ):
            current_image_bytes = read_image_bytes(
                image_path=image_path,
                image_name="현재 프레임 이미지",
            )

            elapsed_ms = (
                (capture_sequence - 1)
                * FRAME_INTERVAL_MS
            )

            captured_at = (
                started_at
                + timedelta(
                    milliseconds=elapsed_ms,
                )
            )

            request_id = (
                f"{REQUEST_ID}_{capture_sequence:03d}"
            )

            monitoring_result = analyze_monitoring_frame(
                exam_id=EXAM_ID,
                examinee_id=EXAMINEE_ID,
                request_id=request_id,
                captured_at=captured_at,
                elapsed_ms=elapsed_ms,
                capture_sequence=capture_sequence,
                current_image_bytes=current_image_bytes,
                reference_image_bytes=reference_image_bytes,
                run_identity_check=RUN_IDENTITY_CHECK,
                eye_yaw_center=EYE_YAW_CENTER,
                eye_pitch_center=EYE_PITCH_CENTER,
                previous_gaze_state=previous_gaze_state,
            )

            previous_gaze_state = monitoring_result[
                "gaze_monitor"
            ]["state"]

            monitoring_results.append(
                {
                    "image_path": str(image_path),
                    **monitoring_result,
                }
            )

        final_result = {
            "exam_id": EXAM_ID,
            "examinee_id": EXAMINEE_ID,
            "request_id_prefix": REQUEST_ID,
            "image_directory": str(
                CURRENT_IMAGE_DIRECTORY
            ),
            "image_count": len(image_paths),
            "frame_interval_ms": FRAME_INTERVAL_MS,
            "run_identity_check": RUN_IDENTITY_CHECK,
            "results": monitoring_results,
        }

        save_monitoring_result(
            result=final_result,
            output_path=RESULT_FILE_PATH,
        )

        print(
            json.dumps(
                final_result,
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        )

    except (FileNotFoundError, OSError, ValueError) as error:
        print()
        print(f"입력 오류: {error}")

    except ProctoringError as error:
        print()
        print(f"모니터링 오류: {error}")
        traceback.print_exc()

    except Exception as error:
        print()
        print(
            f"예상하지 못한 오류가 발생했습니다: "
            f"{type(error).__name__}: {error}"
        )
        traceback.print_exc()


if __name__ == "__main__":
    main()
