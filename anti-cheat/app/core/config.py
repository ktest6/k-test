"""
config.py

프로젝트 환경설정 관리 모듈.

- .env 파일 로드
- AWS Rekognition 설정 관리
- 본인 인증 유사도 임계값 관리
- 시선 추적 임계값 관리
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
    gaze_eye_yaw_threshold: float
    gaze_eye_pitch_threshold: float
    gaze_head_yaw_threshold: float
    gaze_head_pitch_threshold: float
    gaze_minimum_eye_confidence: float
    gaze_persistent_count_threshold: int
    gaze_calibration_minimum_sample_count: int


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


def get_float_env(
    name: str,
    default: str,
    minimum: float,
    maximum: float,
) -> float:
    """실수형 환경설정 값을 읽고 허용 범위를 검증한다."""

    raw_value = os.getenv(name, default)

    try:
        value = float(raw_value)

    except ValueError as error:
        raise RuntimeError(
            f"{name}은 숫자여야 합니다."
        ) from error

    if not minimum <= value <= maximum:
        raise RuntimeError(
            f"{name}은 {minimum} 이상 "
            f"{maximum} 이하이어야 합니다."
        )

    return value


def get_positive_int_env(name: str, default: str) -> int:
    """양의 정수형 환경설정 값을 읽고 검증한다."""

    raw_value = os.getenv(name, default)

    try:
        value = int(raw_value)

    except ValueError as error:
        raise RuntimeError(
            f"{name}은 정수여야 합니다."
        ) from error

    if value < 1:
        raise RuntimeError(
            f"{name}은 1 이상이어야 합니다."
        )

    return value


settings = Settings(
    aws_region=get_required_env("AWS_REGION"),
    aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
    identity_similarity_threshold=get_similarity_threshold(),
    gaze_eye_yaw_threshold=get_float_env(
        name="GAZE_EYE_YAW_THRESHOLD",
        default="15.0",
        minimum=0.0,
        maximum=180.0,
    ),
    gaze_eye_pitch_threshold=get_float_env(
        name="GAZE_EYE_PITCH_THRESHOLD",
        default="15.0",
        minimum=0.0,
        maximum=180.0,
    ),
    gaze_head_yaw_threshold=get_float_env(
        name="GAZE_HEAD_YAW_THRESHOLD",
        default="25.0",
        minimum=0.0,
        maximum=180.0,
    ),
    gaze_head_pitch_threshold=get_float_env(
        name="GAZE_HEAD_PITCH_THRESHOLD",
        default="20.0",
        minimum=0.0,
        maximum=180.0,
    ),
    gaze_minimum_eye_confidence=get_float_env(
        name="GAZE_MINIMUM_EYE_CONFIDENCE",
        default="80.0",
        minimum=0.0,
        maximum=100.0,
    ),
    gaze_persistent_count_threshold=get_positive_int_env(
        name="GAZE_PERSISTENT_COUNT_THRESHOLD",
        default="3",
    ),
    gaze_calibration_minimum_sample_count=get_positive_int_env(
        name="GAZE_CALIBRATION_MINIMUM_SAMPLE_COUNT",
        default="3",
    ),
)
