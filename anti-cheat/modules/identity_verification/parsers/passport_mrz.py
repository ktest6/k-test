"""
passport_mrz.py

여권 MRZ OCR 결과에서 신청자 정보를 추출하는 모듈.

- 여권 MRZ 두 행 탐색 및 복원
- TD3 형식과 check digit 검증
- 성과 이름 추출
- 생년월일 추출 및 형식 변환
- 공통 문서 정보 구조 반환
"""

import re
from typing import Any

from app.schemas.identity import DocumentType
from modules.common.exceptions import DocumentReadError
from modules.identity_verification.field_normalizer import (
    normalize_birth_date,
    normalize_name,
)


_CHECK_DIGIT_WEIGHTS = (7, 3, 1)
_TD3_LINE_LENGTH = 44
_WORD_ROW_TOLERANCE = 0.02
_NUMERIC_OCR_CORRECTIONS = str.maketrans(
    {
        "O": "0",
        "I": "1",
        "L": "1",
        "B": "8",
        "S": "5",
    }
)


# 여권 MRZ OCR 결과에서 성, 이름, 생년월일을 추출한다.
def parse_passport_mrz(
    text_detections: list[dict[str, Any]],
) -> dict[str, str]:
    if not text_detections:
        raise DocumentReadError("여권 MRZ OCR 결과가 없습니다.")

    # LINE을 우선 사용하고 불완전한 경우 WORD 결과로 행을 복원한다.
    line1, line2 = _find_mrz_lines(text_detections)
    last_name, first_name = _parse_name_line(line1)
    birth_date = _parse_data_line(line2)

    return {
        "last_name": last_name,
        "first_name": first_name,
        "birth_date": birth_date,
        "document_type": DocumentType.PASSPORT.value,
    }


# OCR 문자열을 MRZ 비교용 형식으로 정리한다.
def _normalize_mrz_line(value: str) -> str:
    normalized = value.strip().upper()
    normalized = re.sub(r"\s+", "", normalized)
    normalized = normalized.replace("-", "")
    if re.fullmatch(r"[A-Z0-9<]*", normalized) is None:
        return ""
    return normalized


# MRZ 문자를 check digit 계산용 숫자로 변환한다.
def _char_value(character: str) -> int:
    if character.isdigit():
        return int(character)
    if "A" <= character <= "Z":
        return ord(character) - ord("A") + 10
    if character == "<":
        return 0
    raise ValueError("MRZ check digit 계산에 지원하지 않는 문자입니다.")


# ICAO 규칙에 따라 check digit을 계산한다.
def _calculate_check_digit(value: str) -> str:
    total = sum(
        _char_value(character)
        * _CHECK_DIGIT_WEIGHTS[index % len(_CHECK_DIGIT_WEIGHTS)]
        for index, character in enumerate(value)
    )
    return str(total % 10)


def _validate_check_digit(value: str, expected_digit: str) -> bool:
    return expected_digit.isdigit() and (
        _calculate_check_digit(value) == expected_digit
    )


# OCR 결과에서 TD3 MRZ 두 행을 찾거나 복원한다.
def _find_mrz_lines(
    text_detections: list[dict[str, Any]],
) -> tuple[str, str]:
    line_candidates = _collect_line_candidates(text_detections)
    pair = _select_mrz_pair(line_candidates)
    if pair is not None:
        return pair

    word_candidates = _reconstruct_word_lines(text_detections)
    pair = _select_mrz_pair(line_candidates + word_candidates)
    if pair is not None:
        return pair

    raise DocumentReadError("여권 MRZ 두 행을 찾을 수 없습니다.")


def _collect_line_candidates(
    text_detections: list[dict[str, Any]],
) -> list[tuple[str, float | None]]:
    candidates: list[tuple[str, float | None]] = []
    for detection in text_detections:
        if detection.get("type") != "LINE":
            continue

        normalized = _normalize_mrz_line(str(detection.get("text", "")))
        if len(normalized) != _TD3_LINE_LENGTH:
            continue
        candidates.append((normalized, _get_vertical_center(detection)))

    return candidates


def _reconstruct_word_lines(
    text_detections: list[dict[str, Any]],
) -> list[tuple[str, float | None]]:
    positioned_words: list[tuple[float, float, str]] = []
    for detection in text_detections:
        if detection.get("type") != "WORD":
            continue

        bounding_box = _get_bounding_box(detection)
        normalized = _normalize_mrz_line(str(detection.get("text", "")))
        if bounding_box is None or not normalized:
            continue

        center_y = bounding_box["Top"] + bounding_box["Height"] / 2
        positioned_words.append((center_y, bounding_box["Left"], normalized))

    if not positioned_words:
        return []

    positioned_words.sort(key=lambda item: (item[0], item[1]))
    rows: list[list[tuple[float, float, str]]] = []
    for word in positioned_words:
        for row in rows:
            row_center = sum(item[0] for item in row) / len(row)
            if abs(word[0] - row_center) <= _WORD_ROW_TOLERANCE:
                row.append(word)
                break
        else:
            rows.append([word])

    reconstructed: list[tuple[str, float | None]] = []
    for row in rows:
        row.sort(key=lambda item: item[1])
        text = "".join(item[2] for item in row)
        if len(text) == _TD3_LINE_LENGTH:
            center = sum(item[0] for item in row) / len(row)
            reconstructed.append((text, center))

    return reconstructed


def _select_mrz_pair(
    candidates: list[tuple[str, float | None]],
) -> tuple[str, str] | None:
    first_lines = [
        candidate
        for candidate in candidates
        if candidate[0].startswith("P<") and "<<" in candidate[0][5:]
    ]
    second_lines = [
        candidate
        for candidate in candidates
        if not candidate[0].startswith("P<")
        and _has_data_line_shape(candidate[0])
    ]

    possible_pairs: list[
        tuple[tuple[int, float], tuple[str, float | None], tuple[str, float | None]]
    ] = []
    for first_line in first_lines:
        for second_line in second_lines:
            first_top = first_line[1]
            second_top = second_line[1]
            if first_top is None or second_top is None:
                position_score = (1, 1.0)
            else:
                position_score = (
                    0 if second_top >= first_top else 1,
                    abs(second_top - first_top),
                )
            possible_pairs.append((position_score, first_line, second_line))

    if not possible_pairs:
        return None

    _, selected_first, selected_second = min(
        possible_pairs,
        key=lambda item: item[0],
    )
    return selected_first[0], selected_second[0]


def _has_data_line_shape(line: str) -> bool:
    if len(line) != _TD3_LINE_LENGTH:
        return False

    birth_date = _normalize_numeric_field(line[13:19])
    expiry_date = _normalize_numeric_field(line[21:27])
    birth_digit = _normalize_check_digit(line[19])
    expiry_digit = _normalize_check_digit(line[27])
    composite_digit = _normalize_check_digit(line[43])
    return (
        birth_date.isdigit()
        and expiry_date.isdigit()
        and birth_digit.isdigit()
        and expiry_digit.isdigit()
        and composite_digit.isdigit()
    )


def _get_bounding_box(
    detection: dict[str, Any],
) -> dict[str, float] | None:
    bounding_box = detection.get("geometry", {}).get("BoundingBox", {})
    required_coordinates = ("Left", "Top", "Width", "Height")
    if not all(coordinate in bounding_box for coordinate in required_coordinates):
        return None
    try:
        return {
            coordinate: float(bounding_box[coordinate])
            for coordinate in required_coordinates
        }
    except (TypeError, ValueError):
        return None


def _get_vertical_center(detection: dict[str, Any]) -> float | None:
    bounding_box = _get_bounding_box(detection)
    if bounding_box is None:
        return None
    return bounding_box["Top"] + bounding_box["Height"] / 2


# MRZ 이름 영역에서 성과 이름을 분리하고 정규화한다.
def _parse_name_line(line1: str) -> tuple[str, str]:
    if len(line1) != _TD3_LINE_LENGTH or not line1.startswith("P<"):
        raise DocumentReadError("여권 MRZ 첫 번째 행 형식이 올바르지 않습니다.")

    name_area = line1[5:]
    if "<<" not in name_area:
        raise DocumentReadError("여권 MRZ 이름 구분자를 찾을 수 없습니다.")

    raw_last_name, raw_first_name = name_area.split("<<", maxsplit=1)
    last_name = normalize_name(raw_last_name)
    first_name = normalize_name(raw_first_name)
    if not last_name or not first_name:
        raise DocumentReadError("여권 MRZ의 필수 이름 정보를 읽을 수 없습니다.")

    return last_name, first_name


# 두 번째 행의 필수 check digit을 검증하고 생년월일을 반환한다.
def _parse_data_line(line2: str) -> str:
    if len(line2) != _TD3_LINE_LENGTH or line2.startswith("P<"):
        raise DocumentReadError("여권 MRZ 두 번째 행 형식이 올바르지 않습니다.")

    passport_number = line2[0:9]
    passport_digit = _normalize_check_digit(line2[9])
    birth_date = _validated_numeric_field(line2[13:19], line2[19])
    expiry_date = _validated_numeric_field(line2[21:27], line2[27])
    personal_number = line2[28:42]
    personal_digit = _normalize_check_digit(line2[42])
    composite_digit = _normalize_check_digit(line2[43])

    # ICAO 규칙으로 여권번호와 날짜 필드의 check digit을 검증한다.
    if not _validate_check_digit(passport_number, passport_digit):
        raise DocumentReadError("여권 MRZ의 check digit 검증에 실패했습니다.")

    if set(personal_number) == {"<"}:
        if personal_digit not in {"<", "0"}:
            raise DocumentReadError("여권 MRZ의 check digit 검증에 실패했습니다.")
    elif not _validate_check_digit(
        personal_number,
        personal_digit,
    ):
        raise DocumentReadError("여권 MRZ의 check digit 검증에 실패했습니다.")

    corrected_line = (
        passport_number
        + passport_digit
        + line2[10:13]
        + birth_date
        + _normalize_check_digit(line2[19])
        + line2[20]
        + expiry_date
        + _normalize_check_digit(line2[27])
        + personal_number
        + personal_digit
        + composite_digit
    )
    composite_value = (
        corrected_line[0:10]
        + corrected_line[13:20]
        + corrected_line[21:43]
    )
    if not _validate_check_digit(composite_value, composite_digit):
        raise DocumentReadError(
            "여권 MRZ의 composite check digit 검증에 실패했습니다."
        )

    # 생년월일을 공통 YYYY-MM-DD 형식으로 변환한다.
    try:
        return normalize_birth_date(birth_date)
    except ValueError as error:
        raise DocumentReadError(
            "여권 MRZ의 생년월일 형식이 올바르지 않습니다."
        ) from error


def _validated_numeric_field(value: str, expected_digit: str) -> str:
    if value.isdigit() and _validate_check_digit(value, expected_digit):
        return value

    corrected_value = _normalize_numeric_field(value)
    corrected_digit = _normalize_check_digit(expected_digit)
    if corrected_value.isdigit() and _validate_check_digit(
        corrected_value,
        corrected_digit,
    ):
        return corrected_value

    raise DocumentReadError("여권 MRZ의 check digit 검증에 실패했습니다.")


def _normalize_numeric_field(value: str) -> str:
    return value.translate(_NUMERIC_OCR_CORRECTIONS)


def _normalize_check_digit(value: str) -> str:
    return value.translate(_NUMERIC_OCR_CORRECTIONS)
