"""
image_validation.py

이미지 데이터 공통 검증 모듈.

- bytes 타입 확인
- 빈 이미지 데이터 확인
"""

from modules.common.exceptions import InvalidImageError


def validate_image_bytes(
    image_bytes: bytes,
    image_name: str,
) -> None:
    """이미지 데이터가 유효한지 확인한다."""

    if not isinstance(image_bytes, bytes):
        raise InvalidImageError(
            f"{image_name} 이미지 데이터는 bytes 타입이어야 합니다."
        )

    if not image_bytes:
        raise InvalidImageError(
            f"{image_name} 이미지 데이터가 비어 있습니다."
        )