"""
alien_registration.py

외국인등록증 OCR 결과에서 신청자 정보를 추출하는 모듈.

- 외국인등록증의 영문 전체 이름 추출
- 생년월일 추출 및 형식 변환
- 공통 문서 정보 구조 반환
"""

import re
from typing import Any, Callable

from app.schemas.identity import DocumentType
from modules.common.exceptions import DocumentReadError
from modules.identity_verification.field_normalizer import (
    normalize_birth_date,
    normalize_name,
)


_NAME_ALIASES = (
    "NAME IN ENGLISH",
    "ENGLISH NAME",
    "NAME IN FULL",
    "FULL NAME",
    "NAME",
)

_BIRTH_DATE_ALIASES = (
    "DATE OF BIRTH",
    "BIRTH DATE",
    "DOB",
)

_OTHER_FIELD_ALIASES = (
    "REGISTRATION NO",
    "REGISTRATION NUMBER",
    "REGISTRATION",
    "COUNTRY / REGION",
    "COUNTRY REGION",
    "COUNTRY",
    "NATIONALITY",
    "STATUS OF STAY",
    "STATUS",
    "DATE OF ISSUE",
    "ISSUE DATE",
    "DATE OF EXPIRY",
    "EXPIRY DATE",
    "ISSUED BY",
)

_EXCLUDED_NAME_PHRASES = {
    "REPUBLIC OF KOREA",
    "ALIEN REGISTRATION CARD",
    "RESIDENCE CARD",
    "REGISTRATION",
    "REGISTRATION NO",
    "REGISTRATION NUMBER",
    "COUNTRY REGION",
    "COUNTRY",
    "NATIONALITY",
    "STATUS OF STAY",
    "DATE OF ISSUE",
    "ISSUE DATE",
    "ISSUED BY",
    "IMMIGRATION",
}

_MAX_VERTICAL_DISTANCE = 0.12
_MAX_HORIZONTAL_DISTANCE = 0.35

# OCR BoundingBox가 미세하게 겹치는 경우를 허용한다.
_MAX_VERTICAL_OVERLAP = 0.01

_ROW_ALIGNMENT_TOLERANCE = 0.04
_WORD_ROW_TOLERANCE = 0.02


# 외국인등록증 OCR 결과에서 전체 이름과 생년월일을 추출한다.
def parse_alien_registration(
    text_detections: list[dict[str, Any]],
) -> dict[str, str]:
    if not text_detections:
        raise DocumentReadError(
            "외국인등록증 OCR 결과가 없습니다."
        )

    line_detections = [
        detection
        for detection in text_detections
        if detection.get("type") == "LINE"
    ]

    word_lines = _reconstruct_word_lines(text_detections)

    # 다른 필드와 연결된 값은 이름 후보에서 제외한다.
    line_name_exclusions = _find_other_field_value_ids(
        line_detections
    )
    word_name_exclusions = _find_other_field_value_ids(
        word_lines
    )

    # LINE OCR 결과에서 영문 이름 라벨과 값을 찾는다.
    raw_name = _extract_labeled_value(
        line_detections,
        _NAME_ALIASES,
        _normalize_name_candidate,
        "영문 이름",
        excluded_candidate_ids=line_name_exclusions,
        allow_above=True,
    )

    if raw_name is None:
        raw_name = _extract_labeled_value(
            word_lines,
            _NAME_ALIASES,
            _normalize_name_candidate,
            "영문 이름",
            excluded_candidate_ids=word_name_exclusions,
            allow_above=True,
        )

    # LINE OCR 결과에서 생년월일 라벨과 값을 찾는다.
    raw_birth_date = _extract_labeled_value(
        line_detections,
        _BIRTH_DATE_ALIASES,
        _normalize_birth_date_candidate,
        "생년월일",
    )

    if raw_birth_date is None:
        raw_birth_date = _extract_labeled_value(
            word_lines,
            _BIRTH_DATE_ALIASES,
            _normalize_birth_date_candidate,
            "생년월일",
        )

    # 이름 라벨 기반 추출이 실패하면 제한적인 후보를 찾는다.
    if raw_name is None:
        raw_name = _find_unlabeled_name(
            line_detections,
            line_name_exclusions,
        )

    if raw_name is None:
        raw_name = _find_unlabeled_name(
            word_lines,
            word_name_exclusions,
        )

    # 생년월일 라벨이 없으면 등록번호 앞 6자리를 사용한다.
    if raw_birth_date is None:
        raw_birth_date = _find_registration_birth_date(
            line_detections + word_lines
        )

    normalized_fields: dict[str, str] = {}

    if raw_name is not None:
        normalized_name = normalize_name(raw_name)

        if normalized_name:
            normalized_fields["full_name"] = normalized_name

    if raw_birth_date is not None:
        try:
            normalized_fields["birth_date"] = (
                normalize_birth_date(raw_birth_date)
            )
        except ValueError:
            pass

    # 필수 정보가 누락되면 신분증 판독 실패로 처리한다.
    missing_fields = sorted(
        field
        for field in ("full_name", "birth_date")
        if not normalized_fields.get(field)
    )

    if missing_fields:
        raise DocumentReadError(
            "외국인등록증에서 필수 정보를 읽을 수 없습니다: "
            f"{missing_fields}"
        )

    return {
        "full_name": normalized_fields["full_name"],
        "birth_date": normalized_fields["birth_date"],
        "document_type": (
            DocumentType.ALIEN_REGISTRATION.value
        ),
    }


# OCR 라벨 비교를 위해 문자열을 정규화한다.
def _normalize_label(value: str) -> str:
    normalized = re.sub(
        r"[.:/\-]",
        " ",
        value.upper(),
    )

    return " ".join(normalized.split())


# OCR 문자열이 지정된 라벨과 일치하는지 확인한다.
def _match_label(
    text: str,
    aliases: tuple[str, ...],
) -> str | None:
    normalized_text = _normalize_label(text)

    for alias in aliases:
        normalized_alias = _normalize_label(alias)

        if normalized_text == normalized_alias:
            return alias

        if normalized_text.startswith(
            f"{normalized_alias} "
        ):
            return alias

    return None


# 라벨과 같은 OCR 행에 포함된 값을 추출한다.
def _extract_inline_value(
    text: str,
    alias: str,
) -> str | None:
    alias_words = _normalize_label(alias).split()

    label_pattern = (
        r"^\s*"
        + r"[\s.:/\-]*".join(
            re.escape(word)
            for word in alias_words
        )
    )

    match = re.match(
        label_pattern,
        text,
        flags=re.IGNORECASE,
    )

    if match is None:
        return None

    value = text[match.end():].lstrip(" \t.:/-")

    return value or None


# 라벨과 연결된 필드 값을 추출한다.
def _extract_labeled_value(
    detections: list[dict[str, Any]],
    aliases: tuple[str, ...],
    normalizer: Callable[[str], str | None],
    field_label: str,
    excluded_candidate_ids: set[int] | None = None,
    allow_above: bool = False,
) -> str | None:
    inline_candidates: list[str] = []
    nearby_candidates: list[str] = []

    for detection in detections:
        text = str(detection.get("text", ""))

        alias = _match_label(text, aliases)

        if alias is None:
            continue

        inline_value = _extract_inline_value(
            text,
            alias,
        )

        if (
            inline_value is not None
            and normalizer(inline_value) is not None
        ):
            inline_candidates.append(inline_value)
            continue

        nearby_value = _find_nearest_value(
            detection,
            detections,
            normalizer,
            excluded_candidate_ids=excluded_candidate_ids,
            allow_above=allow_above,
        )

        if nearby_value is not None:
            nearby_candidates.append(nearby_value)

    if inline_candidates:
        return _resolve_candidates(
            inline_candidates,
            normalizer,
            field_label,
        )

    if nearby_candidates:
        return _resolve_candidates(
            nearby_candidates,
            normalizer,
            field_label,
        )

    return None


# 라벨 위치와 가까운 OCR 값을 찾는다.
def _find_nearest_value(
    label_detection: dict[str, Any],
    candidates: list[dict[str, Any]],
    normalizer: Callable[[str], str | None],
    excluded_candidate_ids: set[int] | None = None,
    allow_above: bool = False,
) -> str | None:
    label_box = _get_bounding_box(label_detection)

    if label_box is None:
        return None

    ranked: list[tuple[int, float, str]] = []
    excluded_ids = excluded_candidate_ids or set()

    for candidate in candidates:
        if (
            candidate is label_detection
            or id(candidate) in excluded_ids
        ):
            continue

        text = str(
            candidate.get("text", "")
        ).strip()

        candidate_box = _get_bounding_box(candidate)

        if (
            not text
            or candidate_box is None
            or _is_any_label(text)
            or normalizer(text) is None
        ):
            continue

        position = _position_rank(
            label_box,
            candidate_box,
            allow_above=allow_above,
        )

        if position is not None:
            ranked.append(
                (
                    position[0],
                    position[1],
                    text,
                )
            )

    if not ranked:
        return None

    ranked.sort(
        key=lambda item: (
            item[0],
            item[1],
        )
    )

    best = ranked[0]

    tied_values = {
        normalizer(item[2])
        for item in ranked
        if (
            item[0] == best[0]
            and abs(item[1] - best[1]) < 1e-9
        )
    }

    if len(tied_values) > 1:
        raise DocumentReadError(
            "외국인등록증의 필드 후보가 충돌합니다."
        )

    return best[2]


# 라벨과 후보 값의 위치 관계를 우선순위로 계산한다.
def _position_rank(
    label_box: dict[str, float],
    candidate_box: dict[str, float],
    allow_above: bool = False,
) -> tuple[int, float] | None:
    label_left = label_box["Left"]
    label_right = (
        label_left + label_box["Width"]
    )
    label_top = label_box["Top"]
    label_bottom = (
        label_top + label_box["Height"]
    )
    label_center_y = (
        label_top + label_box["Height"] / 2
    )

    candidate_left = candidate_box["Left"]
    candidate_right = (
        candidate_left + candidate_box["Width"]
    )
    candidate_top = candidate_box["Top"]
    candidate_bottom = (
        candidate_top + candidate_box["Height"]
    )
    candidate_center_y = (
        candidate_top
        + candidate_box["Height"] / 2
    )

    vertical_distance = (
        candidate_top - label_bottom
    )
    upward_distance = (
        label_top - candidate_bottom
    )
    center_distance = abs(
        candidate_center_y - label_center_y
    )

    horizontal_overlap = (
        min(label_right, candidate_right)
        - max(label_left, candidate_left)
    )

    # 이름 값은 라벨 위에 있으면서 BoundingBox가 소폭 겹칠 수 있다.
    if (
        allow_above
        and candidate_center_y < label_center_y
        and (
            -_MAX_VERTICAL_OVERLAP
            <= upward_distance
            <= _MAX_VERTICAL_DISTANCE
        )
        and horizontal_overlap >= 0
    ):
        return (
            0,
            center_distance
            + abs(candidate_left - label_left),
        )

    below_priority = 1 if allow_above else 0

    # 라벨 바로 아래에 있는 값을 후보로 선택한다.
    if (
        candidate_center_y > label_center_y
        and (
            0
            <= vertical_distance
            <= _MAX_VERTICAL_DISTANCE
        )
        and horizontal_overlap >= 0
    ):
        return (
            below_priority,
            center_distance
            + abs(candidate_left - label_left),
        )

    right_priority = 2 if allow_above else 1

    horizontal_distance = (
        candidate_left - label_right
    )

    # 라벨과 같은 행의 오른쪽 값을 후보로 선택한다.
    if (
        0
        <= horizontal_distance
        <= _MAX_HORIZONTAL_DISTANCE
        and abs(
            candidate_center_y - label_center_y
        )
        <= _ROW_ALIGNMENT_TOLERANCE
    ):
        return (
            right_priority,
            horizontal_distance,
        )

    if allow_above:
        return None

    if (
        0
        <= vertical_distance
        <= _MAX_VERTICAL_DISTANCE
        and abs(candidate_left - label_left)
        <= _MAX_HORIZONTAL_DISTANCE
    ):
        return (
            2,
            vertical_distance
            + abs(candidate_left - label_left),
        )

    return None


# OCR 문자열이 유효한 영문 이름 후보인지 확인한다.
def _normalize_name_candidate(
    value: str,
) -> str | None:
    stripped = value.strip()
    normalized_label = _normalize_label(stripped)

    if (
        not stripped
        or re.fullmatch(
            r"[A-Za-z][A-Za-z\s.'\-]*",
            stripped,
        )
        is None
        or _is_any_label(stripped)
        or normalized_label
        in _EXCLUDED_NAME_PHRASES
    ):
        return None

    normalized = normalize_name(stripped)

    return (
        normalized
        if len(normalized) >= 2
        else None
    )


# OCR 문자열이 유효한 생년월일 후보인지 확인한다.
def _normalize_birth_date_candidate(
    value: str,
) -> str | None:
    try:
        return normalize_birth_date(value)
    except ValueError:
        return None


# OCR 문자열이 알려진 필드 라벨인지 확인한다.
def _is_any_label(value: str) -> bool:
    return (
        _match_label(
            value,
            _NAME_ALIASES,
        )
        is not None
        or _match_label(
            value,
            _BIRTH_DATE_ALIASES,
        )
        is not None
        or _match_label(
            value,
            _OTHER_FIELD_ALIASES,
        )
        is not None
    )


# 다른 필드 라벨과 연결된 값은 이름 후보에서 제외한다.
def _find_other_field_value_ids(
    detections: list[dict[str, Any]],
) -> set[int]:
    excluded_ids: set[int] = set()

    for label_detection in detections:
        label_text = str(
            label_detection.get("text", "")
        )

        alias = _match_label(
            label_text,
            _OTHER_FIELD_ALIASES,
        )

        if alias is None:
            continue

        if (
            _extract_inline_value(
                label_text,
                alias,
            )
            is not None
        ):
            continue

        label_box = _get_bounding_box(
            label_detection
        )

        if label_box is None:
            continue

        ranked_candidates: list[
            tuple[
                int,
                float,
                dict[str, Any],
            ]
        ] = []

        for candidate in detections:
            if candidate is label_detection:
                continue

            candidate_text = str(
                candidate.get("text", "")
            ).strip()

            candidate_box = _get_bounding_box(
                candidate
            )

            if (
                not candidate_text
                or candidate_box is None
                or _is_any_label(candidate_text)
            ):
                continue

            position = _position_rank(
                label_box,
                candidate_box,
                allow_above=True,
            )

            if position is not None:
                ranked_candidates.append(
                    (
                        position[0],
                        position[1],
                        candidate,
                    )
                )

        if ranked_candidates:
            _, _, linked_value = min(
                ranked_candidates,
                key=lambda item: (
                    item[0],
                    item[1],
                ),
            )

            excluded_ids.add(id(linked_value))

    return excluded_ids


# 라벨이 없을 때 형식에 맞는 영문 이름 후보를 선택한다.
def _find_unlabeled_name(
    detections: list[dict[str, Any]],
    excluded_candidate_ids: set[int] | None = None,
) -> str | None:
    candidates: list[str] = []
    excluded_ids = excluded_candidate_ids or set()

    for detection in detections:
        text = str(
            detection.get("text", "")
        ).strip()

        bounding_box = _get_bounding_box(
            detection
        )

        if (
            id(detection) in excluded_ids
            or bounding_box is None
            or bounding_box["Top"] > 0.70
            or _normalize_name_candidate(text)
            is None
        ):
            continue

        candidates.append(text)

    if not candidates:
        return None

    return _resolve_candidates(
        candidates,
        _normalize_name_candidate,
        "영문 이름",
    )


# 외국인등록번호 후보에서 생년월일 앞 6자리만 사용한다.
def _find_registration_birth_date(
    detections: list[dict[str, Any]],
) -> str | None:
    birth_dates: list[str] = []

    for detection in detections:
        birth_date = (
            _extract_birth_date_from_registration_number(
                str(detection.get("text", ""))
            )
        )

        if birth_date is not None:
            birth_dates.append(birth_date)

    if not birth_dates:
        return None

    return _resolve_candidates(
        birth_dates,
        _normalize_birth_date_candidate,
        "생년월일",
    )


# 등록번호 후보에서 생년월일 앞 6자리를 추출한다.
def _extract_birth_date_from_registration_number(
    value: str,
) -> str | None:
    match = re.fullmatch(
        r"\s*(?P<birth_date>\d{6})-?\d{7}\s*",
        value,
    )

    if match is None:
        return None

    birth_date = match.group("birth_date")

    try:
        return normalize_birth_date(birth_date)
    except ValueError:
        return None


# 동일 필드의 후보가 하나로 일치하는지 확인한다.
def _resolve_candidates(
    candidates: list[str],
    normalizer: Callable[[str], str | None],
    field_label: str,
) -> str:
    normalized_candidates = {
        normalized
        for candidate in candidates
        if (
            normalized := normalizer(candidate)
        )
        is not None
    }

    if len(normalized_candidates) != 1:
        raise DocumentReadError(
            f"외국인등록증의 {field_label} "
            "후보가 충돌합니다."
        )

    return candidates[0]


# OCR 결과에서 BoundingBox 좌표를 가져온다.
def _get_bounding_box(
    detection: dict[str, Any],
) -> dict[str, float] | None:
    bounding_box = detection.get(
        "geometry",
        {},
    ).get(
        "BoundingBox",
        {},
    )

    required_coordinates = (
        "Left",
        "Top",
        "Width",
        "Height",
    )

    if not all(
        coordinate in bounding_box
        for coordinate in required_coordinates
    ):
        return None

    try:
        return {
            coordinate: float(
                bounding_box[coordinate]
            )
            for coordinate in required_coordinates
        }
    except (TypeError, ValueError):
        return None


# WORD OCR 결과를 위치 기준으로 LINE 형태로 재구성한다.
def _reconstruct_word_lines(
    text_detections: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    positioned_words: list[
        tuple[
            float,
            float,
            dict[str, Any],
        ]
    ] = []

    for detection in text_detections:
        if detection.get("type") != "WORD":
            continue

        bounding_box = _get_bounding_box(
            detection
        )

        if (
            bounding_box is None
            or not str(
                detection.get("text", "")
            ).strip()
        ):
            continue

        center_y = (
            bounding_box["Top"]
            + bounding_box["Height"] / 2
        )

        positioned_words.append(
            (
                center_y,
                bounding_box["Left"],
                detection,
            )
        )

    positioned_words.sort(
        key=lambda item: (
            item[0],
            item[1],
        )
    )

    rows: list[
        list[
            tuple[
                float,
                float,
                dict[str, Any],
            ]
        ]
    ] = []

    for word in positioned_words:
        for row in rows:
            row_center = (
                sum(item[0] for item in row)
                / len(row)
            )

            if (
                abs(word[0] - row_center)
                <= _WORD_ROW_TOLERANCE
            ):
                row.append(word)
                break
        else:
            rows.append([word])

    reconstructed: list[dict[str, Any]] = []

    for row in rows:
        row.sort(key=lambda item: item[1])

        boxes = [
            _get_bounding_box(item[2])
            for item in row
        ]

        valid_boxes = [
            box
            for box in boxes
            if box is not None
        ]

        if not valid_boxes:
            continue

        left = min(
            box["Left"]
            for box in valid_boxes
        )
        top = min(
            box["Top"]
            for box in valid_boxes
        )
        right = max(
            box["Left"] + box["Width"]
            for box in valid_boxes
        )
        bottom = max(
            box["Top"] + box["Height"]
            for box in valid_boxes
        )

        reconstructed.append(
            {
                "text": " ".join(
                    str(item[2]["text"]).strip()
                    for item in row
                ),
                "type": "LINE",
                "geometry": {
                    "BoundingBox": {
                        "Left": left,
                        "Top": top,
                        "Width": right - left,
                        "Height": bottom - top,
                    }
                },
            }
        )

    return reconstructed