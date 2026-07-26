"""
client.py

AWS Rekognition Client 생성 모듈.

- 프로젝트 환경설정을 기반으로 Rekognition Client 생성
- 로컬 환경의 Access Key 인증 지원
- AWS 배포 환경의 IAM Role 인증 지원
"""

import boto3
from botocore.client import BaseClient

from app.core.config import settings


def create_rekognition_client() -> BaseClient:
    """AWS Rekognition Client를 생성한다."""

    client_options = {
        "service_name": "rekognition",
        "region_name": settings.aws_region,
    }

    # Access Key가 설정된 로컬 환경에서는 명시적으로 인증 정보를 전달한다.
    if (
        settings.aws_access_key_id
        and settings.aws_secret_access_key
    ):
        client_options["aws_access_key_id"] = (
            settings.aws_access_key_id
        )
        client_options["aws_secret_access_key"] = (
            settings.aws_secret_access_key
        )

    return boto3.client(**client_options)


rekognition_client = create_rekognition_client()