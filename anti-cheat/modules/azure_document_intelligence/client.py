"""
client.py

Azure Document Intelligence Client 생성 모듈.

- 프로젝트 환경설정을 기반으로 Client 생성
- API Key 인증 설정
"""

from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.core.credentials import AzureKeyCredential

from app.core.config import settings


def create_document_intelligence_client() -> DocumentIntelligenceClient:
    """Azure Document Intelligence Client를 생성한다."""

    return DocumentIntelligenceClient(
        endpoint=settings.azure_document_intelligence_endpoint,
        credential=AzureKeyCredential(
            settings.azure_document_intelligence_key
        ),
    )


document_intelligence_client = create_document_intelligence_client()
