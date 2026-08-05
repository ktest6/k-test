"""
run_monitoring.py

시험 중 모니터링 기능을 로컬 이미지로 테스트하는 실행 파일.

기능
- 현재 프레임 이미지 로드
- 선택적으로 기준 얼굴 이미지 로드
- 모니터링 서비스 실행
- 얼굴 탐지 및 동일인 검사 결과 출력
- Rule Engine 결과 출력
- Event Engine 이벤트 생성 및 JSON 저장 확인

※ 실제 프로젝트에서는 프론트엔드가 전달한 이미지 bytes를 사용한다.
※ 이 파일은 모니터링 모듈 단독 테스트용이다.
"""

import json
import sys
import traceback
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


# 프로젝트 루트 경로
PROJECT_ROOT = Path(__file__).resolve().parents[1]

# 프로젝트 모듈 import를 위한 경로 추가
sys.path.append(str(PROJECT_ROOT))


from modules.cheating_detection.service import analyze_monitoring_frame
from modules.common.exceptions import ProctoringError


# 테스트 환경 설정
EXAM_ID = "exam_001"
EXAMINEE_ID = "examinee_001"
REQUEST_ID = "request_monitoring_001"

# 시험 시작 후 경과 시간(ms)
ELAPSED_MS = 65000

# 캡처 이미지 순번
CAPTURE_SEQUENCE = 13

TEST_IMAGE = "multiple_faces.jpg"
REFERENCE_IMAGE = "target_true.jpg"

# 동일인 검사 실행 여부
RUN_IDENTITY_CHECK = False

# 현재 프레임 테스트 이미지
CURRENT_IMAGE_PATH = (
    PROJECT_ROOT / "data" / "monitoring" / TEST_IMAGE
)

# 본인 인증 시 저장한 기준 이미지
REFERENCE_IMAGE_PATH = (
    PROJECT_ROOT / "data" / "compare" / REFERENCE_IMAGE
)

# 시험 로그 저장 폴더
EXAM_LOG_DIR = (
    PROJECT_ROOT / "data" / "logs" / EXAM_ID
)

# 테스트 이미지 촬영 시각
TIMEZONE = ZoneInfo("Asia/Seoul")


def read_image_bytes(
    image_path: Path,
    image_name: str,
) -> bytes:
    """이미지 파일을 읽어 bytes로 반환한다."""

    if not image_path.exists():
        raise FileNotFoundError(
            f"{image_name} 파일이 존재하지 않습니다: {image_path}"
        )

    if not image_path.is_file():
        raise ValueError(
            f"{image_name} 경로가 파일이 아닙니다: {image_path}"
        )

    try:
        return image_path.read_bytes()

    except OSError as error:
        raise OSError(
            f"{image_name} 파일을 읽을 수 없습니다: {image_path}"
        ) from error


def prepare_exam_log_directory() -> None:
    """로컬 테스트를 위한 시험 로그 폴더를 준비한다."""

    EXAM_LOG_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )


def print_result(
    title: str,
    result: object,
) -> None:
    """결과를 JSON 형식으로 출력한다."""

    print()
    print(f"===== {title} =====")

    print(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    )


def main() -> None:
    """로컬 이미지로 모니터링 전체 흐름을 테스트한다."""

    try:
        prepare_exam_log_directory()

        current_image_bytes = read_image_bytes(
            image_path=CURRENT_IMAGE_PATH,
            image_name="현재 프레임 이미지",
        )

        reference_image_bytes = None

        if RUN_IDENTITY_CHECK:
            reference_image_bytes = read_image_bytes(
                image_path=REFERENCE_IMAGE_PATH,
                image_name="기준 얼굴 이미지",
            )

        captured_at = datetime.now(
            TIMEZONE,
        )

        monitoring_result = analyze_monitoring_frame(
            exam_id=EXAM_ID,
            examinee_id=EXAMINEE_ID,
            request_id=REQUEST_ID,
            captured_at=captured_at,
            elapsed_ms=ELAPSED_MS,
            capture_sequence=CAPTURE_SEQUENCE,
            current_image_bytes=current_image_bytes,
            reference_image_bytes=reference_image_bytes,
            run_identity_check=RUN_IDENTITY_CHECK,
        )

        print_result(
            title="요청 메타데이터",
            result={
                "exam_id": monitoring_result.get(
                    "exam_id"
                ),
                "examinee_id": monitoring_result.get(
                    "examinee_id"
                ),
                "request_id": monitoring_result.get(
                    "request_id"
                ),
                "captured_at": monitoring_result.get(
                    "captured_at"
                ),
                "elapsed_ms": monitoring_result.get(
                    "elapsed_ms"
                ),
                "capture_sequence": monitoring_result.get(
                    "capture_sequence"
                ),
            },
        )

        print_result(
            title="Face Monitor 결과",
            result=monitoring_result.get(
                "face_monitor",
            ),
        )

        print_result(
            title="Identity Monitor 결과",
            result={
                "identity_check_requested": (
                    monitoring_result.get(
                        "identity_check_requested"
                    )
                ),
                "identity_check_executed": (
                    monitoring_result.get(
                        "identity_check_executed"
                    )
                ),
                "identity_monitor": (
                    monitoring_result.get(
                        "identity_monitor"
                    )
                ),
            },
        )

        print_result(
            title="Rule Engine 결과",
            result=monitoring_result.get(
                "rule_result",
            ),
        )

        print_result(
            title="Event Engine 결과",
            result=monitoring_result.get(
                "event_result",
            ),
        )

        print()
        print("모니터링 테스트가 완료되었습니다.")

    except FileNotFoundError as error:
        print()
        print(f"파일 오류: {error}")

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