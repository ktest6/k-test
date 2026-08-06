"""
field_normalizer.py

신청 정보와 신분증 추출 정보를 비교하기 위한 필드 정규화 모듈.

- 영문 이름 정규화
- 생년월일 형식 정규화
"""

import re
from datetime import date, datetime


def normalize_name(value: str) -> str:
    # 공백과 이름 표기에 사용되는 구분 문자를 제거한다.
    normalized = value.strip().upper()
    normalized = re.sub(r"\s+", "", normalized)
    normalized = normalized.replace("-", "")
    normalized = normalized.replace("<", "")
    normalized = normalized.replace("'", "")
    normalized = normalized.replace(".", "")

    # 최종 결과에는 영문 대문자만 남긴다.
    return re.sub(r"[^A-Z]", "", normalized)


def normalize_birth_date(value: str | date | datetime) -> str:
    # datetime은 date의 하위 타입이므로 먼저 처리한다.
    if isinstance(value, datetime):
        return value.date().isoformat()

    if isinstance(value, date):
        return value.isoformat()

    normalized_date = _normalize_birth_date_string(value)
    return normalized_date.isoformat()


def _normalize_birth_date_string(value: str) -> date:
    normalized = value.strip()

    # 연, 월, 일이 구분자로 나뉜 형식을 처리한다.
    separated_match = re.fullmatch(
        r"(?P<year>\d{4})[-./](?P<month>\d{2})[-./](?P<day>\d{2})",
        normalized,
    )
    if separated_match:
        return _build_date(
            int(separated_match.group("year")),
            int(separated_match.group("month")),
            int(separated_match.group("day")),
            value,
        )

    if re.fullmatch(r"\d{8}", normalized):
        return _build_date(
            int(normalized[:4]),
            int(normalized[4:6]),
            int(normalized[6:]),
            value,
        )

    if re.fullmatch(r"\d{6}", normalized):
        year = _expand_two_digit_year(int(normalized[:2]))
        return _build_date(
            year,
            int(normalized[2:4]),
            int(normalized[4:]),
            value,
        )

    raise ValueError(f"지원하지 않는 생년월일 형식입니다: {value}")


def _expand_two_digit_year(year: int) -> int:
    current_year = date.today().year
    current_century = current_year // 100 * 100
    current_two_digit_year = current_year % 100

    if year <= current_two_digit_year:
        return current_century + year

    return current_century - 100 + year


def _build_date(year: int, month: int, day: int, original_value: str) -> date:
    try:
        return date(year, month, day)
    except ValueError as error:
        raise ValueError(
            f"지원하지 않는 생년월일 형식입니다: {original_value}"
        ) from error
