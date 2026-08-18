"""
run_document_reader.py

로컬 여권 이미지 기반 Azure 문서 판독 테스트 실행 파일.

- 로컬 여권 이미지 파일 읽기
- document_reader 호출
- 여권 정보 추출 결과 출력
- 여권 미인식 및 판독 오류 출력
"""

import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from modules.common.exceptions import ProctoringError
from modules.identity_verification.document_reader import (
    read_identity_document,
)


IMAGE_PATH = Path(
    # "/Users/apple/dio_folder/python/hackathon_aws/poc/images/ex_dio_front.jpg"
    "/Users/apple/dio_folder/python/hackathon_aws/poc/images/pakistan_male.png"
    # "/Users/apple/dio_folder/python/dataset/dio_passport.jpg"
)


def read_image_bytes(image_path: Path) -> bytes:
    """로컬 이미지 파일을 bytes로 읽는다."""

    if not image_path.exists():
        raise FileNotFoundError(
            f"이미지 파일을 찾을 수 없습니다: {image_path}"
        )
    if not image_path.is_file():
        raise IsADirectoryError(
            f"입력 경로가 파일이 아닙니다: {image_path}"
        )
    return image_path.read_bytes()


def main() -> int:
    """Azure 여권 판독 결과를 JSON으로 출력한다."""

    try:
        result = read_identity_document(read_image_bytes(IMAGE_PATH))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    except (FileNotFoundError, IsADirectoryError, OSError) as error:
        print(f"파일 오류: {error}")
        return 1
    except ProctoringError as error:
        print(f"passport not detected: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
