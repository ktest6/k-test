"""
document_reader.py

신분증 이미지에서 신청자 정보를 읽는 전체 흐름을 관리하는 모듈.

- 입력 신분증 이미지 검증
- AWS Rekognition DetectText 1회 호출
- 신분증 종류에 따른 parser 선택
- 여권 시각 영역과 MRZ 결과 통합
- 문서별 신청자 정보 추출 결과 반환
"""

from typing import Any

from app.schemas.identity import DocumentType
from modules.aws_rekognition.text_detection import detect_text
from modules.common.exceptions import (
    DocumentReadError,
    UnsupportedDocumentError,
)
from modules.common.image_validation import validate_image_bytes
from modules.identity_verification.field_normalizer import (
    normalize_birth_date,
    normalize_name,
)
from modules.identity_verification.parsers.alien_registration import (
    parse_alien_registration,
)
from modules.identity_verification.parsers.passport_mrz import (
    parse_passport_mrz,
)
from modules.identity_verification.parsers.passport_visual import (
    parse_passport_visual,
)


_SUPPORTED_DOCUMENT_TYPES = {
    DocumentType.PASSPORT.value,
    DocumentType.ALIEN_REGISTRATION.value,
}


# 신분증 종류에 맞는 parser를 호출하고 추출 결과를 반환한다.
def read_identity_document(
    image_bytes: bytes,
    document_type: str,
) -> dict[str, Any]:
    # API 계약에 정의되지 않은 문서 종류는 OCR 전에 거부한다.
    if document_type not in _SUPPORTED_DOCUMENT_TYPES:
        raise UnsupportedDocumentError(
            f"지원하지 않는 신분증 종류입니다: {document_type}"
        )

    # 신분증 OCR 전에 입력 이미지 bytes를 검증한다.
    validate_image_bytes(image_bytes, "신분증")

    # DetectText는 이미지당 한 번만 호출하고 결과를 parser들이 재사용한다.
    text_detections = detect_text(image_bytes)
    if not text_detections:
        raise DocumentReadError("신분증에서 텍스트를 찾을 수 없습니다.")

    # 백엔드에서 전달받은 신분증 종류에 따라 parser를 선택한다.
    if document_type == DocumentType.PASSPORT.value:
        return _read_passport(text_detections)

    return parse_alien_registration(text_detections)


# 같은 OCR 결과로 여권 시각 영역과 MRZ parser를 독립적으로 실행한다.
def _read_passport(
    text_detections: list[dict[str, Any]],
) -> dict[str, str]:
    visual_result: dict[str, str] | None = None
    mrz_result: dict[str, str] | None = None

    try:
        visual_result = parse_passport_visual(text_detections)
    except DocumentReadError:
        pass

    try:
        mrz_result = parse_passport_mrz(text_detections)
    except DocumentReadError:
        pass

    # 두 여권 parser가 성공하면 정규화된 필드 값을 교차검증한다.
    if visual_result is not None and mrz_result is not None:
        if not _passport_results_match(visual_result, mrz_result):
            raise DocumentReadError(
                "여권 시각 영역과 MRZ의 신청자 정보가 일치하지 않습니다."
            )
        return visual_result

    if visual_result is not None:
        return visual_result

    # 시각 영역이 실패한 경우 MRZ 결과를 fallback으로 사용한다.
    if mrz_result is not None:
        return mrz_result

    raise DocumentReadError("여권에서 신청자 정보를 읽을 수 없습니다.")


# 여권 시각 영역과 MRZ 결과가 일치하는지 확인한다.
def _passport_results_match(
    visual_result: dict[str, str],
    mrz_result: dict[str, str],
) -> bool:
    return (
        normalize_name(visual_result["last_name"])
        == normalize_name(mrz_result["last_name"])
        and normalize_name(visual_result["first_name"])
        == normalize_name(mrz_result["first_name"])
        and normalize_birth_date(visual_result["birth_date"])
        == normalize_birth_date(mrz_result["birth_date"])
    )
