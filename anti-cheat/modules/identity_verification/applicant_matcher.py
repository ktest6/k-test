"""
applicant_matcher.py

신청 정보와 신분증 추출 정보를 비교하는 모듈.

- 성과 이름 정규화 후 비교
- 생년월일 정규화 후 비교
- 필드별 일치 여부 생성
- 신청 정보 전체 일치 여부 계산
"""

from typing import Any

from modules.identity_verification.field_normalizer import (
    normalize_birth_date,
    normalize_name,
)


_REQUIRED_FIELDS = {"last_name", "first_name", "birth_date"}


# 신청 정보와 신분증 추출 정보를 필드별로 비교한다.
def match_applicant_info(
    applicant_info: dict[str, Any],
    document_fields: dict[str, Any],
) -> dict[str, Any]:
    # 필수 비교 필드가 모두 존재하는지 확인한다.
    missing_applicant_fields = _REQUIRED_FIELDS - applicant_info.keys()
    if missing_applicant_fields:
        raise ValueError(
            "신청 정보에 필수 필드가 없습니다: "
            f"{sorted(missing_applicant_fields)}"
        )

    missing_document_fields = _REQUIRED_FIELDS - document_fields.keys()
    if missing_document_fields:
        raise ValueError(
            "신분증 추출 정보에 필수 필드가 없습니다: "
            f"{sorted(missing_document_fields)}"
        )

    # 이름과 생년월일을 정규화한 뒤 필드별로 비교한다.
    field_matches = {
        "last_name": normalize_name(applicant_info["last_name"])
        == normalize_name(document_fields["last_name"]),
        "first_name": normalize_name(applicant_info["first_name"])
        == normalize_name(document_fields["first_name"]),
        "birth_date": normalize_birth_date(applicant_info["birth_date"])
        == normalize_birth_date(document_fields["birth_date"]),
    }

    # 모든 필드가 일치한 경우 신청 정보 검증에 성공한다.
    applicant_verified = all(field_matches.values())

    return {
        "applicant_verified": applicant_verified,
        "field_matches": field_matches,
    }
