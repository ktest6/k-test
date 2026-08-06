"""
config.py

프로젝트 환경설정 관리 모듈.

- .env 파일 로드
- AWS Rekognition 설정 관리
- 본인 인증 유사도 임계값 관리
"""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


# 프로젝트 루트 경로
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# 프로젝트 루트의 .env 파일 로드
ENV_PATH = PROJECT_ROOT / ".env"
load_dotenv(ENV_PATH)


@dataclass(frozen=True)
class Settings:
    """프로젝트에서 사용하는 환경설정."""

    aws_region: str
    aws_access_key_id: str | None
    aws_secret_access_key: str | None
    identity_similarity_threshold: float
    identity_similarity_retrieval_threshold: float


def get_required_env(name: str) -> str:
    """필수 환경변수를 읽고, 없으면 예외를 발생시킨다."""

    value = os.getenv(name)

    if not value:
        raise RuntimeError(
            f"필수 환경변수가 설정되지 않았습니다: {name}"
        )

    return value


def get_similarity_threshold() -> float:
    """본인 인증 유사도 임계값을 읽고 검증한다."""

    raw_value = os.getenv(
        "IDENTITY_SIMILARITY_THRESHOLD",
        "80.0",
    )

    try:
        threshold = float(raw_value)

    except ValueError as error:
        raise RuntimeError(
            "IDENTITY_SIMILARITY_THRESHOLD는 숫자여야 합니다."
        ) from error

    if not 0.0 <= threshold <= 100.0:
        raise RuntimeError(
            "IDENTITY_SIMILARITY_THRESHOLD는 "
            "0 이상 100 이하이어야 합니다."
        )

    return threshold


def get_similarity_retrieval_threshold() -> float:
    """실제 얼굴 유사도 조회에 사용할 기준값을 읽고 검증한다."""

    raw_value = os.getenv(
        "IDENTITY_SIMILARITY_RETRIEVAL_THRESHOLD",
        "0.0",
    )

    try:
        threshold = float(raw_value)

    except ValueError as error:
        raise RuntimeError(
            "IDENTITY_SIMILARITY_RETRIEVAL_THRESHOLD는 숫자여야 합니다."
        ) from error

    if not 0.0 <= threshold <= 100.0:
        raise RuntimeError(
            "IDENTITY_SIMILARITY_RETRIEVAL_THRESHOLD는 "
            "0 이상 100 이하이어야 합니다."
        )

    return threshold


settings = Settings(
    aws_region=get_required_env("AWS_REGION"),
    aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
    identity_similarity_threshold=get_similarity_threshold(),
    identity_similarity_retrieval_threshold=(
        get_similarity_retrieval_threshold()
    ),
)
