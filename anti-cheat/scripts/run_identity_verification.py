"""
run_identity_verification.py

로컬 이미지 기반 본인 인증 실행 파일.

동작 과정
1. 신분증 이미지 경로 확인
2. 얼굴 캡처 이미지 경로 확인
3. 이미지 파일을 bytes로 변환
4. 본인 인증 서비스 호출
5. 인증 결과 출력
"""

import json
import sys
from datetime import date
from pathlib import Path


# 프로젝트 루트 경로
PROJECT_ROOT = Path(__file__).resolve().parents[1]

# 프로젝트 모듈을 import할 수 있도록 경로 추가
sys.path.append(str(PROJECT_ROOT))

from app.schemas.identity import DocumentType
from modules.common.exceptions import IdentityVerificationError
from modules.identity_verification.service import verify_identity


# 테스트 이미지 경로, 로컬 용
# source_image_bytes = await id_image.read()

# target_image_bytes = await capture_image.read()
SOURCE_IMAGE_PATH = Path(
    # "/Users/apple/dio_folder/python/hackathon_aws/poc/images/ex_dio_front.jpg"
    "/Users/apple/dio_folder/python/dataset/dio_passport.jpg"
)

TARGET_IMAGE_PATH = Path(
    "/Users/apple/dio_folder/python/ktest_git/k-test/anti-cheat/data/compare/test_img.png"
    # "/Users/apple/dio_folder/python/ktest_git/k-test/anti-cheat/data/compare/target_false.png"
)

# 테스트할 신청자 정보를 실제 여권 정보에 맞게 설정한다.
LAST_NAME = "KIM"
FIRST_NAME = "DOYEONG"
BIRTH_DATE = "1998-09-26"
DOCUMENT_NUMBER = "M00579616"


def validate_image_path(
    image_path: Path,
    image_name: str,
) -> None:
    """이미지 파일의 존재 여부를 확인한다."""

    if not image_path.exists():
        raise FileNotFoundError(
            f"{image_name} 이미지 파일을 찾을 수 없습니다: "
            f"{image_path}"
        )

    if not image_path.is_file():
        raise FileNotFoundError(
            f"{image_name} 경로가 파일이 아닙니다: "
            f"{image_path}"
        )


def main() -> None:
    """로컬 이미지를 이용해 본인 인증을 실행한다."""

    try:
        validate_image_path(
            image_path=SOURCE_IMAGE_PATH,
            image_name="신분증",
        )

        validate_image_path(
            image_path=TARGET_IMAGE_PATH,
            image_name="얼굴 캡처",
        )

        source_image_bytes = SOURCE_IMAGE_PATH.read_bytes()
        target_image_bytes = TARGET_IMAGE_PATH.read_bytes()

        result = verify_identity(
            source_image_bytes=source_image_bytes,
            target_image_bytes=target_image_bytes,
            last_name=LAST_NAME,
            first_name=FIRST_NAME,
            birth_date=date.fromisoformat(BIRTH_DATE),
            document_number=DOCUMENT_NUMBER,
            document_type=DocumentType.PASSPORT,
        )

        print("본인 인증 결과")
        print(
            json.dumps(
                result,
                indent=2,
                ensure_ascii=False,
            )
        )

    except FileNotFoundError as error:
        print(f"[파일 오류] {error}")

    except IdentityVerificationError as error:
        print(f"[본인 인증 오류] {error}")

    except Exception as error:
        print(f"[예상하지 못한 오류] {error}")


if __name__ == "__main__":
    main()
