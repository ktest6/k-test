"""
run_document_reader.py

로컬 신분증 이미지 기반 문서 판독 테스트 실행 파일.

- 테스트할 이미지 경로와 신분증 종류 설정
- 로컬 신분증 이미지 파일 읽기
- document_reader 호출
- 문서 정보 추출 결과 출력
- 문서 판독 오류 출력
"""

import json
import sys
from pathlib import Path


# 프로젝트 루트 경로
PROJECT_ROOT = Path(__file__).resolve().parents[1]

# 프로젝트 모듈을 import할 수 있도록 경로 추가
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from modules.common.exceptions import ProctoringError
from modules.identity_verification.document_reader import (
    read_identity_document,
)


SUPPORTED_DOCUMENT_TYPES = {
    "passport",
    "alien_registration_card",
}

# 테스트할 신분증 종류와 이미지 경로를 설정한다.
DOCUMENT_TYPE = "alien_registration_card"
IMAGE_PATH = PROJECT_ROOT / "data" / "compare" / "china_card_female.png"


# 로컬 신분증 이미지 파일을 bytes로 읽는다.
def read_image_bytes(image_path: Path) -> bytes:
    if not image_path.exists():
        raise FileNotFoundError(
            f"이미지 파일을 찾을 수 없습니다: {image_path}"
        )

    if not image_path.is_file():
        raise IsADirectoryError(
            f"입력 경로가 파일이 아닙니다: {image_path}"
        )

    try:
        return image_path.read_bytes()
    except OSError as error:
        raise OSError(
            f"이미지 파일을 읽을 수 없습니다: {image_path}"
        ) from error


def main() -> int:
    # 설정된 신분증 종류가 지원 대상인지 확인한다.
    if DOCUMENT_TYPE not in SUPPORTED_DOCUMENT_TYPES:
        print(f"지원하지 않는 신분증 종류입니다: {DOCUMENT_TYPE}")
        return 1

    try:
        image_bytes = read_image_bytes(IMAGE_PATH)

        # document_reader 전체 흐름을 호출해 문서 정보를 추출한다.
        result = read_identity_document(
            image_bytes=image_bytes,
            document_type=DOCUMENT_TYPE,
        )

        # 문서 종류별 반환 결과를 변환하지 않고 JSON 형식으로 출력한다.
        print(
            json.dumps(
                result,
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    except (FileNotFoundError, IsADirectoryError, OSError) as error:
        print(f"파일 오류: {error}")
        return 1

    # 프로젝트 사용자 정의 예외를 사용자 메시지로 출력한다.
    except ProctoringError as error:
        print(f"문서 판독 실패: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
