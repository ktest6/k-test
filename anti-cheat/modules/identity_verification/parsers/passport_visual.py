"""
passport_visual.py

여권 시각 영역 OCR 결과에서 신청자 정보를 추출하는 모듈.

- 여권 시각 영역의 필드 라벨 탐색
- 성과 이름 추출
- 생년월일 추출 및 형식 변환
- 공통 문서 정보 구조 반환
"""

import re
import unicodedata
from datetime import date
from typing import Any

from app.schemas.identity import DocumentType
from modules.common.exceptions import DocumentReadError
from modules.identity_verification.field_normalizer import (
    normalize_birth_date,
    normalize_name,
)


_FIELD_ALIASES = {
    "last_name": ("SURNAME", "LAST NAME", "FAMILY NAME", "NOM"),
    "first_name": (
        "GIVEN NAMES",
        "GIVEN NAME",
        "FIRST NAME",
        "FORENAMES",
        "PRENOMS",
        "PRÉNOMS",
    ),
    "birth_date": (
        "DATE OF BIRTH / DATE DE NAISSANCE",
        "DATE DE NAISSANCE",
        "DATE OF BIRTH",
        "BIRTH DATE",
        "DOB",
    ),
}

_MONTHS = {
    "JAN": 1,
    "FEB": 2,
    "MAR": 3,
    "APR": 4,
    "MAY": 5,
    "JUN": 6,
    "JUL": 7,
    "AUG": 8,
    "SEP": 9,
    "OCT": 10,
    "NOV": 11,
    "DEC": 12,
}

_MAX_VERTICAL_DISTANCE = 0.12
_MAX_HORIZONTAL_DISTANCE = 0.35
_ROW_ALIGNMENT_TOLERANCE = 0.04


# 여권 시각 영역 OCR 결과에서 성, 이름, 생년월일을 추출한다.
def parse_passport_visual(
    text_detections: list[dict[str, Any]],
) -> dict[str, str]:
    if not text_detections:
        raise DocumentReadError("여권 시각 영역의 OCR 결과가 없습니다.")

    line_detections = [
        detection
        for detection in text_detections
        if detection.get("type") == "LINE"
    ]
    word_detections = [
        detection
        for detection in text_detections
        if detection.get("type") == "WORD"
    ]

    # LINE OCR 결과에서 여권 시각 영역의 필드 라벨을 찾는다.
    raw_fields = _extract_fields(line_detections, word_detections)

    normalized_fields: dict[str, str] = {}
    if raw_fields.get("last_name"):
        normalized_fields["last_name"] = normalize_name(
            raw_fields["last_name"]
        )
    if raw_fields.get("first_name"):
        normalized_fields["first_name"] = normalize_name(
            raw_fields["first_name"]
        )
    if raw_fields.get("birth_date"):
        try:
            normalized_fields["birth_date"] = _parse_passport_birth_date(
                raw_fields["birth_date"]
            )
        except ValueError:
            pass

    # 빈 이름을 포함해 필수 정보가 누락되면 신분증 판독 실패로 처리한다.
    missing_fields = sorted(
        field
        for field in _FIELD_ALIASES
        if not normalized_fields.get(field)
    )
    if missing_fields:
        raise DocumentReadError(
            "여권 시각 영역에서 필수 정보를 읽을 수 없습니다: "
            f"{missing_fields}"
        )

    return {
        "last_name": normalized_fields["last_name"],
        "first_name": normalized_fields["first_name"],
        "birth_date": normalized_fields["birth_date"],
        "document_type": DocumentType.PASSPORT.value,
    }


def _extract_fields(
    line_detections: list[dict[str, Any]],
    word_detections: list[dict[str, Any]],
) -> dict[str, str]:
    fields: dict[str, str] = {}

    for label_detection in line_detections:
        label_match = _match_field_label(str(label_detection.get("text", "")))
        if label_match is None:
            continue

        field_name, inline_value = label_match
        if field_name in fields:
            continue

        if inline_value:
            fields[field_name] = inline_value
            continue

        # 같은 행의 값이 없으면 라벨과 가까운 LINE 항목을 탐색한다.
        nearest_value = _find_nearest_value(label_detection, line_detections)
        if nearest_value is None:
            nearest_value = _find_nearest_value(
                label_detection,
                word_detections,
            )
        if nearest_value:
            fields[field_name] = nearest_value

    return fields


# OCR 라벨 비교를 위해 문자열을 정규화한다.
def _normalize_label(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    without_accents = "".join(
        character
        for character in decomposed
        if not unicodedata.combining(character)
    )
    without_punctuation = re.sub(r"[.:/]", " ", without_accents.upper())
    return " ".join(without_punctuation.split())


def _match_field_label(text: str) -> tuple[str, str | None] | None:
    normalized_text = _normalize_label(text)

    for field_name, aliases in _FIELD_ALIASES.items():
        for alias in sorted(aliases, key=len, reverse=True):
            normalized_alias = _normalize_label(alias)
            if normalized_text == normalized_alias:
                return field_name, None
            if normalized_text.startswith(f"{normalized_alias} "):
                return field_name, _extract_inline_value(text, alias)

    return None


# 라벨과 같은 행에 포함된 값을 추출한다.
def _extract_inline_value(text: str, alias: str) -> str | None:
    folded_text = _fold_accents(text)
    alias_words = _normalize_label(alias).split()
    label_pattern = r"^\s*" + r"[\s.:/]*".join(
        re.escape(word) for word in alias_words
    )
    match = re.match(label_pattern, folded_text, flags=re.IGNORECASE)
    if match is None:
        return None

    value = text[match.end():].lstrip(" \t.:/-")
    return value or None


def _fold_accents(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    return "".join(
        character
        for character in decomposed
        if not unicodedata.combining(character)
    )


# 라벨 위치와 가까운 OCR 값을 찾는다.
def _find_nearest_value(
    label_detection: dict[str, Any],
    candidates: list[dict[str, Any]],
) -> str | None:
    label_box = _get_bounding_box(label_detection)
    if label_box is None:
        return None

    ranked_candidates: list[tuple[int, float, str]] = []
    for candidate in candidates:
        if candidate is label_detection:
            continue

        text = str(candidate.get("text", "")).strip()
        candidate_box = _get_bounding_box(candidate)
        if (
            not text
            or candidate_box is None
            or _match_field_label(text) is not None
            or _is_mrz_candidate(text, candidate_box)
        ):
            continue

        rank = _position_rank(label_box, candidate_box)
        if rank is not None:
            priority, distance = rank
            ranked_candidates.append((priority, distance, text))

    if not ranked_candidates:
        return None

    return min(ranked_candidates, key=lambda item: (item[0], item[1]))[2]


def _get_bounding_box(
    detection: dict[str, Any],
) -> dict[str, float] | None:
    bounding_box = detection.get("geometry", {}).get("BoundingBox", {})
    required_coordinates = ("Left", "Top", "Width", "Height")
    if not all(coordinate in bounding_box for coordinate in required_coordinates):
        return None

    return {
        coordinate: float(bounding_box[coordinate])
        for coordinate in required_coordinates
    }


def _position_rank(
    label_box: dict[str, float],
    candidate_box: dict[str, float],
) -> tuple[int, float] | None:
    label_left = label_box["Left"]
    label_right = label_left + label_box["Width"]
    label_bottom = label_box["Top"] + label_box["Height"]
    label_center_y = label_box["Top"] + label_box["Height"] / 2

    candidate_left = candidate_box["Left"]
    candidate_right = candidate_left + candidate_box["Width"]
    candidate_top = candidate_box["Top"]
    candidate_center_y = candidate_top + candidate_box["Height"] / 2

    vertical_distance = candidate_top - label_bottom
    horizontal_overlap = min(label_right, candidate_right) - max(
        label_left,
        candidate_left,
    )

    # 라벨 바로 아래이면서 수평 영역이 겹치는 값을 가장 우선한다.
    if (
        0 <= vertical_distance <= _MAX_VERTICAL_DISTANCE
        and horizontal_overlap >= 0
    ):
        return 0, vertical_distance + abs(candidate_left - label_left)

    horizontal_distance = candidate_left - label_right
    if (
        0 <= horizontal_distance <= _MAX_HORIZONTAL_DISTANCE
        and abs(candidate_center_y - label_center_y) <= _ROW_ALIGNMENT_TOLERANCE
    ):
        return 1, horizontal_distance

    # 라벨보다 아래의 가까운 동일 수평 영역을 마지막 후보로 사용한다.
    if (
        0 <= vertical_distance <= _MAX_VERTICAL_DISTANCE
        and abs(candidate_left - label_left) <= _MAX_HORIZONTAL_DISTANCE
    ):
        return 2, vertical_distance + abs(candidate_left - label_left)

    return None


def _is_mrz_candidate(text: str, bounding_box: dict[str, float]) -> bool:
    compact_text = re.sub(r"\s+", "", text.upper())
    if compact_text.startswith("P<") or compact_text.count("<") >= 2:
        return True

    is_long_machine_text = (
        len(compact_text) >= 30
        and re.fullmatch(r"[A-Z0-9<]+", compact_text) is not None
    )
    is_bottom_machine_text = (
        bounding_box["Top"] >= 0.75
        and len(compact_text) >= 20
        and re.fullmatch(r"[A-Z0-9<]+", compact_text) is not None
    )
    return is_long_machine_text or is_bottom_machine_text


# 여권 시각 영역의 생년월일을 YYYY-MM-DD로 변환한다.
def _parse_passport_birth_date(value: str) -> str:
    try:
        return normalize_birth_date(value)
    except ValueError:
        pass

    passport_date_match = re.fullmatch(
        r"\s*(?P<day>\d{2})[\s-]+(?P<month>[A-Za-z]{3})"
        r"[\s-]+(?P<year>\d{2}|\d{4})\s*",
        value,
        flags=re.IGNORECASE,
    )
    if passport_date_match is None:
        raise ValueError("지원하지 않는 여권 생년월일 형식입니다.")

    month_text = passport_date_match.group("month").upper()
    if month_text not in _MONTHS:
        raise ValueError("지원하지 않는 여권 생년월일 형식입니다.")

    day = int(passport_date_match.group("day"))
    month = _MONTHS[month_text]
    year_text = passport_date_match.group("year")
    if len(year_text) == 2:
        return normalize_birth_date(f"{year_text}{month:02d}{day:02d}")

    return date(int(year_text), month, day).isoformat()
