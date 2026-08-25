"""공통 구조화 오류 응답 테스트."""

import json
import unittest

try:
    from fastapi import Request
    from fastapi.exceptions import RequestValidationError
except ModuleNotFoundError as error:
    raise unittest.SkipTest("FastAPI dependencies are not installed") from error

from app.core.error_handlers import (
    CodedHTTPException,
    http_exception_handler,
    request_validation_exception_handler,
)
from modules.common.exceptions import InvalidImageError
from modules.common.image_validation import validate_image_bytes


def _request() -> Request:
    return Request({"type": "http", "method": "POST", "path": "/"})


class ErrorHandlerTest(unittest.IsolatedAsyncioTestCase):
    """오류 응답의 code와 선택적 params를 검증한다."""

    async def test_coded_http_exception_includes_params(self) -> None:
        response = await http_exception_handler(
            _request(),
            CodedHTTPException(
                status_code=400,
                detail="elapsed_ms는 0 이상이어야 합니다.",
                code="ELAPSED_MS_OUT_OF_RANGE",
                params={"actual": -1, "min": 0},
            ),
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            json.loads(response.body),
            {
                "detail": "elapsed_ms는 0 이상이어야 합니다.",
                "code": "ELAPSED_MS_OUT_OF_RANGE",
                "params": {"actual": -1, "min": 0},
            },
        )

    async def test_validation_error_uses_stable_datetime_contract(self) -> None:
        response = await request_validation_exception_handler(
            _request(),
            RequestValidationError(
                [
                    {
                        "type": "datetime_parsing",
                        "loc": ("body", "captured_at"),
                        "msg": "invalid datetime",
                        "input": "not-a-date",
                    }
                ]
            ),
        )

        self.assertEqual(
            json.loads(response.body),
            {
                "detail": "날짜와 시간 형식이 올바르지 않습니다.",
                "code": "REQUEST_DATETIME_INVALID",
                "params": {
                    "field": "capturedAt",
                    "expectedFormat": "ISO 8601 datetime",
                },
            },
        )

    def test_image_validation_exposes_image_key(self) -> None:
        with self.assertRaises(InvalidImageError) as context:
            validate_image_bytes(b"", "현재 프레임 이미지", "currentImage")

        self.assertEqual(context.exception.code, "IMAGE_DATA_EMPTY")
        self.assertEqual(
            context.exception.params,
            {"imageName": "currentImage"},
        )


if __name__ == "__main__":
    unittest.main()
