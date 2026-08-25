"""
exceptions.py

프로젝트 공통 사용자 정의 예외 모듈.

- 온라인 시험 감독 시스템 공통 예외
- 본인 인증 예외
- 시험 모니터링 예외
- 이어폰 탐지 예외
- 시선 상태 관리 예외
- AWS Rekognition 예외
- Azure Document Intelligence 예외
- 이미지 검증 예외
- 신청 정보 검증 예외
- 신분증 OCR 예외
"""


from typing import Any


class ProctoringError(Exception):
    """온라인 시험 감독 처리 중 발생하는 구조화된 기본 예외."""

    def __init__(
        self,
        message: str,
        *,
        code: str,
        params: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.params = params


class IdentityVerificationError(ProctoringError):
    """본인 인증 처리 중 발생하는 예외."""


class MonitoringError(ProctoringError):
    """시험 모니터링 처리 중 발생하는 예외."""


class EarphoneDetectionError(ProctoringError):
    """이어폰 탐지 처리 중 발생하는 예외."""


class GazeStateError(MonitoringError):
    """시선 상태 관리 중 발생하는 예외."""


class RekognitionAPIError(ProctoringError):
    """AWS Rekognition API 호출 중 발생하는 예외."""


class DocumentIntelligenceAPIError(IdentityVerificationError):
    """Azure Document Intelligence API 호출 중 발생하는 예외."""


class InvalidImageError(ProctoringError):
    """입력 이미지가 유효하지 않을 때 발생하는 예외."""

class DocumentReadError(IdentityVerificationError):
    """신분증에서 정보를 읽을 수 없을 때 발생하는 예외."""


class UnsupportedDocumentError(DocumentReadError):
    """지원하지 않는 신분증 종류일 때 발생하는 예외."""


class ApplicantVerificationError(IdentityVerificationError, ValueError):
    """신청 정보 검증 중 발생하는 예외."""


class GazeCalibrationError(MonitoringError):
    """시선 기준점 보정 중 발생하는 예외."""
