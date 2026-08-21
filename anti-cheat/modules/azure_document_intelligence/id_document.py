"""
id_document.py

Azure prebuilt ID Document 분석 모듈.

- 신분증 이미지 분석 요청
- Azure 원본 분석 결과 반환
"""

from io import BytesIO
from typing import Any

from azure.core.exceptions import AzureError

from modules.azure_document_intelligence.client import (
    document_intelligence_client,
)
from modules.common.exceptions import DocumentIntelligenceAPIError


def analyze_id_document(image_bytes: bytes) -> Any:
    """이미지를 prebuilt-idDocument 모델로 분석한다."""

    try:
        poller = document_intelligence_client.begin_analyze_document(
            model_id="prebuilt-idDocument",
            body=BytesIO(image_bytes),
        )
        return poller.result()

    except AzureError as error:
        raise DocumentIntelligenceAPIError(
            "Azure Document Intelligence API 호출에 실패했습니다."
        ) from error
