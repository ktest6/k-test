"""
run_applicant_matcher.py

신청 정보와 여권 추출 정보의 필드 비교 테스트 실행 파일.

- 이름, 생년월일, 여권번호 정규화 비교
- 필드별 일치 여부와 전체 검증 결과 출력
"""

import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from modules.identity_verification.applicant_matcher import (
    match_applicant_info,
)


APPLICANT_INFO = {
    "last_name": "KIM",
    "first_name": "DOYEONG",
    "birth_date": "1998-09-26",
    "document_number": "M00579616",
}

DOCUMENT_FIELDS = {
    "last_name": "KIM",
    "first_name": "DOYEONG",
    "birth_date": "1998-09-26",
    "document_number": "M 00579616",
}


def main() -> None:
    """필드별 신청 정보 비교 결과를 출력한다."""

    result = match_applicant_info(
        applicant_info=APPLICANT_INFO,
        document_fields=DOCUMENT_FIELDS,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
