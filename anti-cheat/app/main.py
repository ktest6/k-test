"""
main.py

FastAPI 애플리케이션 실행 진입점.

- FastAPI 앱 생성
- API 라우터 등록
- 기본 상태 확인 API 제공
"""

from fastapi import FastAPI

from app.api.earphone_detection import (
    router as earphone_detection_router,
)
from app.api.identity import router as identity_router
from app.api.monitoring import router as monitoring_router
from app.core.error_handlers import register_error_handlers


app = FastAPI(
    title="Online Exam Proctoring API",
    description=(
        "Azure Document Intelligence 및 AWS Rekognition 기반 온라인 시험 "
        "본인 인증 및 부정행위 탐지 API"
    ),
    version="0.1.0",
)

register_error_handlers(app)


@app.get("/")
def read_root() -> dict[str, str]:
    """API 서버의 실행 상태를 확인한다."""

    return {
        "message": "Online Exam Proctoring API is running."
    }


@app.get("/health")
def health_check() -> dict[str, str]:
    """서버 상태 확인용 응답을 반환한다."""

    return {
        "status": "healthy"
    }


app.include_router(identity_router)
app.include_router(earphone_detection_router)
app.include_router(monitoring_router)
