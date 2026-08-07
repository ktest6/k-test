"""
run_earphone_detection.py

시험 전 이어폰 탐지 기능을 로컬 이미지로 테스트하는 실행 파일.

기능
- 왼쪽 귀 이미지 로드
- 오른쪽 귀 이미지 로드
- 이어폰 탐지 서비스 실행
- 양쪽 귀 검사 결과 출력
- 시험 진행 가능 여부 출력

※ 실제 프로젝트에서는 프론트엔드가 전달한 이미지 bytes를 사용한다.
※ 이 파일은 이어폰 탐지 모듈 단독 테스트용이다.
"""

import json
import sys
import traceback
from pathlib import Path


# 프로젝트 루트 경로
PROJECT_ROOT = Path(__file__).resolve().parents[1]

# 프로젝트 모듈 import를 위한 경로 추가
sys.path.append(str(PROJECT_ROOT))

from modules.earphone_detection.service import (
    analyze_earphone_image,
)


# 테스트 이미지 경로
LEFT_IMAGE_PATH = (
    PROJECT_ROOT / "data" / "earphone" / "left_line_fail.jpg"
)

RIGHT_IMAGE_PATH = (
    PROJECT_ROOT / "data" / "earphone" / "right_pass.jpg"
)


def load_image_bytes(image_path: Path) -> bytes:
    """이미지를 bytes 형태로 읽는다."""

    with open(image_path, "rb") as file:
        return file.read()


def print_result(title: str, result: dict) -> None:
    """이어폰 탐지 결과를 출력한다."""

    print("=" * 60)
    print(title)
    print("=" * 60)

    print(
        json.dumps(
            result,
            indent=4,
            ensure_ascii=False,
        )
    )
    print()


def main():
    """시험 전 이어폰 탐지 기능을 테스트한다."""

    try:
        left_image_bytes = load_image_bytes(
            LEFT_IMAGE_PATH,
        )

        right_image_bytes = load_image_bytes(
            RIGHT_IMAGE_PATH,
        )

        left_result = analyze_earphone_image(
            image_bytes=left_image_bytes,
            image_name="왼쪽 귀",
        )

        right_result = analyze_earphone_image(
            image_bytes=right_image_bytes,
            image_name="오른쪽 귀",
        )

        print_result(
            "왼쪽 귀 검사 결과",
            left_result,
        )

        print_result(
            "오른쪽 귀 검사 결과",
            right_result,
        )

        print("=" * 60)
        print("최종 결과")
        print("=" * 60)

        if (
            left_result["earphone_detected"]
            or right_result["earphone_detected"]
        ):
            print("이어폰이 탐지되었습니다.")
            print("시험 시작 전에 이어폰을 제거해 주세요.")

        else:
            print("이어폰이 탐지되지 않았습니다.")
            print("시험을 진행할 수 있습니다.")

    except Exception:
        print("=" * 60)
        print("이어폰 탐지 테스트 실패")
        print("=" * 60)

        traceback.print_exc()


if __name__ == "__main__":
    main()