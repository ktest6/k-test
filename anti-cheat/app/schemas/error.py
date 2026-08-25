"""공통 API 오류 응답 스키마."""

from typing import Any

from pydantic import BaseModel


class ErrorResponse(BaseModel):
    """클라이언트에 반환하는 구조화된 오류."""

    detail: str
    code: str
    params: dict[str, Any] | None = None
