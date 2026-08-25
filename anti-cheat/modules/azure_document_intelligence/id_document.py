"""
id_document.py

Azure prebuilt ID Document 분석 모듈.

- 신분증 이미지 분석 요청
- Azure 원본 분석 결과 반환
"""

import logging
from io import BytesIO
from typing import Any

from azure.core.exceptions import AzureError

from modules.azure_document_intelligence.client import (
    document_intelligence_client,
)
from modules.common.exceptions import DocumentIntelligenceAPIError


logger = logging.getLogger(__name__)


def analyze_id_document(image_bytes: bytes) -> Any:
    """이미지를 prebuilt-idDocument 모델로 분석한다."""

    try:
        poller = document_intelligence_client.begin_analyze_document(
            model_id="prebuilt-idDocument",
            body=BytesIO(image_bytes),
        )
        return poller.result()

    except AzureError as error:
        azure_error = getattr(error, "error", None)
        logger.exception(
            "Azure Document Intelligence API 호출 실패 "
            "(exception_type=%s, status_code=%s, error_code=%s): %s",
            type(error).__name__,
            getattr(error, "status_code", None),
            getattr(azure_error, "code", None),
            error,
        )
        raise DocumentIntelligenceAPIError(
            "Azure Document Intelligence API 호출에 실패했습니다.",
            code="DOCUMENT_INTELLIGENCE_API_FAILED",
        ) from error
