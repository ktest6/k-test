"""
exceptions.py

프로젝트 공통 사용자 정의 예외 모듈.

- 온라인 시험 감독 시스템 공통 예외
- 본인 인증 예외
- 시험 모니터링 예외
- 이어폰 탐지 예외
- AWS Rekognition 예외
- 이미지 검증 예외
"""


class ProctoringError(Exception):
    """온라인 시험 감독 처리 중 발생하는 기본 예외."""


class IdentityVerificationError(ProctoringError):
    """본인 인증 처리 중 발생하는 예외."""


class MonitoringError(ProctoringError):
    """시험 모니터링 처리 중 발생하는 예외."""


class EarphoneDetectionError(ProctoringError):
    """이어폰 탐지 처리 중 발생하는 예외."""


class RekognitionAPIError(ProctoringError):
    """AWS Rekognition API 호출 중 발생하는 예외."""


class InvalidImageError(ProctoringError):
    """입력 이미지가 유효하지 않을 때 발생하는 예외."""