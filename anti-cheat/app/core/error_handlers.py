"""FastAPI 공통 오류 응답 생성 및 예외 핸들러."""

from typing import Any

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from modules.common.exceptions import ProctoringError


FIELD_NAMES = {
    "exam_id": "examId",
    "examinee_id": "examineeId",
    "request_id": "requestId",
    "captured_at": "capturedAt",
    "elapsed_ms": "elapsedMs",
    "capture_sequence": "captureSequence",
    "run_identity_check": "runIdentityCheck",
    "eye_yaw_center": "eyeYawCenter",
    "eye_pitch_center": "eyePitchCenter",
    "previous_gaze_state": "previousGazeState",
    "current_image": "currentImage",
    "reference_image": "referenceImage",
    "calibration_images": "calibrationImages",
    "source_image": "sourceImage",
    "target_image": "targetImage",
    "left_ear_image": "leftEarImage",
    "right_ear_image": "rightEarImage",
    "last_name": "lastName",
    "first_name": "firstName",
    "birth_date": "birthDate",
    "document_number": "documentNumber",
    "document_type": "documentType",
}

DATETIME_FIELDS = {"captured_at"}
DATE_FIELDS = {"birth_date"}
INTEGER_FIELDS = {"elapsed_ms", "capture_sequence"}
BOOLEAN_FIELDS = {"run_identity_check"}
NUMBER_FIELDS = {"eye_yaw_center", "eye_pitch_center"}
ENUM_FIELDS = {"document_type"}
FILE_LIST_FIELDS = {"calibration_images"}
FILE_FIELDS = {
    "source_image",
    "target_image",
    "left_ear_image",
    "right_ear_image",
    "current_image",
    "reference_image",
}


class CodedHTTPException(HTTPException):
    """오류 코드와 params를 포함하는 HTTP 예외."""

    def __init__(
        self,
        *,
        status_code: int,
        detail: str,
        code: str,
        params: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(status_code=status_code, detail=detail)
        self.code = code
        self.params = params


def from_proctoring_error(
    *,
    status_code: int,
    error: ProctoringError,
) -> CodedHTTPException:
    """도메인 예외를 API HTTP 예외로 변환한다."""

    return CodedHTTPException(
        status_code=status_code,
        detail=str(error),
        code=error.code,
        params=error.params,
    )


def _error_content(
    *,
    detail: str,
    code: str,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    content: dict[str, Any] = {
        "detail": detail,
        "code": code,
    }
    if params:
        content["params"] = params
    return content


def _validation_error_response(error: dict[str, Any]) -> dict[str, Any]:
    location = error.get("loc", ())
    raw_field = str(location[-1]) if location else "body"
    field = FIELD_NAMES.get(raw_field, raw_field)
    error_type = str(error.get("type", "validation_error"))

    if error_type == "missing":
        return _error_content(
            detail="필수 요청 값이 누락되었습니다.",
            code="REQUEST_FIELD_REQUIRED",
            params={"field": field},
        )
    if raw_field in DATETIME_FIELDS:
        return _error_content(
            detail="날짜와 시간 형식이 올바르지 않습니다.",
            code="REQUEST_DATETIME_INVALID",
            params={"field": field, "expectedFormat": "ISO 8601 datetime"},
        )
    if raw_field in DATE_FIELDS:
        return _error_content(
            detail="날짜 형식이 올바르지 않습니다.",
            code="REQUEST_DATE_INVALID",
            params={"field": field, "expectedFormat": "YYYY-MM-DD"},
        )
    if raw_field in INTEGER_FIELDS:
        return _error_content(
            detail="정수 형식이 올바르지 않습니다.",
            code="REQUEST_INTEGER_INVALID",
            params={"field": field, "expectedType": "integer"},
        )
    if raw_field in BOOLEAN_FIELDS:
        return _error_content(
            detail="불리언 형식이 올바르지 않습니다.",
            code="REQUEST_BOOLEAN_INVALID",
            params={"field": field, "expectedType": "boolean"},
        )
    if raw_field in NUMBER_FIELDS:
        return _error_content(
            detail="숫자 형식이 올바르지 않습니다.",
            code="REQUEST_NUMBER_INVALID",
            params={"field": field, "expectedType": "number"},
        )
    if raw_field in ENUM_FIELDS:
        return _error_content(
            detail="허용되지 않은 요청 값입니다.",
            code="REQUEST_ENUM_INVALID",
            params={"field": field, "allowedValues": ["passport"]},
        )
    if raw_field in FILE_LIST_FIELDS:
        return _error_content(
            detail="파일 목록 형식이 올바르지 않습니다.",
            code="REQUEST_FILE_LIST_INVALID",
            params={"field": field, "expectedType": "fileList"},
        )
    if raw_field in FILE_FIELDS:
        return _error_content(
            detail="파일 형식이 올바르지 않습니다.",
            code="REQUEST_FILE_INVALID",
            params={"field": field, "expectedType": "file"},
        )
    return _error_content(
        detail="요청 본문 형식이 올바르지 않습니다.",
        code="REQUEST_BODY_INVALID",
        params={"reason": error_type},
    )


async def request_validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    """FastAPI 요청 검증 오류 중 첫 번째 원인을 구조화해 반환한다."""

    del request
    errors = exc.errors()
    content = (
        _validation_error_response(errors[0])
        if errors
        else _error_content(
            detail="요청 본문 형식이 올바르지 않습니다.",
            code="REQUEST_BODY_INVALID",
        )
    )
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content=content,
    )


async def http_exception_handler(
    request: Request,
    exc: StarletteHTTPException,
) -> JSONResponse:
    """HTTP 예외를 공통 오류 응답 형식으로 반환한다."""

    del request
    code = getattr(exc, "code", None)
    params = getattr(exc, "params", None)
    if code is None and exc.status_code == status.HTTP_400_BAD_REQUEST:
        code = "REQUEST_BODY_INVALID"
        params = {"reason": "multipart_parse_error"}
    elif code is None:
        code = "HTTP_ERROR"
    return JSONResponse(
        status_code=exc.status_code,
        content=_error_content(
            detail=str(exc.detail),
            code=code,
            params=params,
        ),
        headers=exc.headers,
    )


def register_error_handlers(app: FastAPI) -> None:
    """애플리케이션에 공통 오류 핸들러를 등록한다."""

    app.add_exception_handler(
        RequestValidationError,
        request_validation_exception_handler,
    )
    app.add_exception_handler(
        StarletteHTTPException,
        http_exception_handler,
    )
