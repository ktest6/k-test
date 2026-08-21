"""
document_reader.py

여권 이미지에서 신청자 정보를 읽는 전체 흐름을 관리하는 모듈.

- 입력 여권 이미지 검증
- Azure prebuilt-idDocument 분석
- 여권 여부 확인
- 구조화된 신청자 정보 추출
"""

from datetime import date, datetime
from typing import Any, Mapping

from modules.azure_document_intelligence.id_document import (
    analyze_id_document,
)
from modules.common.exceptions import (
    DocumentReadError,
    UnsupportedDocumentError,
)
from modules.common.image_validation import validate_image_bytes
from modules.identity_verification.field_normalizer import (
    normalize_birth_date,
)


_PASSPORT_DOCUMENT_TYPE = "idDocument.passport"


def read_identity_document(image_bytes: bytes) -> dict[str, str]:
    """Azure 분석 결과에서 여권 신청자 정보를 추출한다."""

    validate_image_bytes(image_bytes, "여권")
    result = analyze_id_document(image_bytes)
    documents = _get_value(result, "documents") or []

    if not documents:
        raise DocumentReadError("여권을 인식할 수 없습니다.")

    document = documents[0]
    document_type = _get_value(document, "doc_type")
    if document_type != _PASSPORT_DOCUMENT_TYPE:
        raise UnsupportedDocumentError("지원하는 문서는 여권뿐입니다.")

    fields = _get_value(document, "fields") or {}
    extracted_fields = {
        "first_name": _get_string_field(fields, "FirstName"),
        "last_name": _get_string_field(fields, "LastName"),
        "date_of_birth": _get_date_field(fields, "DateOfBirth"),
        "document_number": _get_string_field(fields, "DocumentNumber"),
    }

    missing_fields = [
        label
        for key, label in (
            ("first_name", "이름"),
            ("last_name", "성"),
            ("date_of_birth", "생년월일"),
            ("document_number", "여권번호"),
        )
        if not extracted_fields[key]
    ]
    if missing_fields:
        raise DocumentReadError(
            "여권에서 필수 정보를 읽을 수 없습니다: "
            f"{', '.join(missing_fields)}"
        )

    return {
        "document_type": _PASSPORT_DOCUMENT_TYPE,
        **extracted_fields,
    }


def _get_value(value: Any, name: str) -> Any:
    # Azure SDK 모델은 snake_case 속성과 camelCase Mapping 키를 함께 제공한다.
    if hasattr(value, name):
        return getattr(value, name)

    if isinstance(value, Mapping):
        direct_value = value.get(name)
        if direct_value is not None:
            return direct_value

        camel_case_name = _to_camel_case(name)
        return value.get(camel_case_name)

    return None


def _to_camel_case(value: str) -> str:
    first_part, *remaining_parts = value.split("_")
    return first_part + "".join(
        part.capitalize() for part in remaining_parts
    )


def _get_document_field(fields: Any, name: str) -> Any:
    if isinstance(fields, Mapping):
        return fields.get(name)
    return _get_value(fields, name)


def _get_string_field(fields: Any, name: str) -> str:
    field = _get_document_field(fields, name)
    if field is None:
        return ""

    value = _get_value(field, "value_string")
    if not value:
        value = _get_value(field, "value_country_region")
    if not value:
        value = _get_value(field, "content")

    return str(value).strip() if value is not None else ""


def _get_date_field(fields: Any, name: str) -> str:
    field = _get_document_field(fields, name)
    if field is None:
        return ""

    structured_value = _get_value(field, "value_date")
    if isinstance(structured_value, (date, datetime)):
        return normalize_birth_date(structured_value)
    if structured_value:
        try:
            return normalize_birth_date(str(structured_value))
        except ValueError:
            pass

    content = _get_value(field, "content")
    if not content:
        return ""

    try:
        return normalize_birth_date(str(content))
    except ValueError:
        return _normalize_azure_date_content(str(content))


def _normalize_azure_date_content(value: str) -> str:
    for date_format in ("%d %b %Y", "%d %B %Y"):
        try:
            return datetime.strptime(
                value.strip(),
                date_format,
            ).date().isoformat()
        except ValueError:
            continue

    return ""
