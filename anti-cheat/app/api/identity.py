"""
identity.py

본인 인증 API 라우터.

- 시험 및 응시자 정보 수신
- 신분증 이미지 파일 수신
- 웹캠 캡처 이미지 파일 수신
- 이미지 파일을 bytes로 변환
- 본인 인증 서비스 호출
- 인증 결과 반환
"""

from datetime import datetime

from fastapi import (
    APIRouter,
    File,
    Form,
    HTTPException,
    UploadFile,
    status,
)

from app.schemas.identity import IdentityVerificationResponse
from modules.common.exceptions import InvalidImageError, RekognitionAPIError
from modules.identity_verification.service import verify_identity


router = APIRouter(
    prefix="/identity",
    tags=["Identity Verification"],
)


@router.post(
    "/verify",
    response_model=IdentityVerificationResponse,
    status_code=status.HTTP_200_OK,
)
async def verify_identity_api(
    exam_id: str = Form(
        ...,
        description="시험 식별자",
    ),
    examinee_id: str = Form(
        ...,
        description="응시자 식별자",
    ),
    captured_at: datetime = Form(
        ...,
        description="웹캠 이미지 촬영 시각",
    ),
    source_image: UploadFile = File(
        ...,
        description="신분증 또는 수험표 이미지",
    ),
    target_image: UploadFile = File(
        ...,
        description="시험 시작 전 웹캠 캡처 이미지",
    ),
) -> IdentityVerificationResponse:
    """시험 시작 전 신분증 얼굴과 웹캠 얼굴을 비교한다."""

    try:
        source_image_bytes = await source_image.read()
        target_image_bytes = await target_image.read()

        result = verify_identity(
            source_image_bytes=source_image_bytes,
            target_image_bytes=target_image_bytes,
        )

        return IdentityVerificationResponse(
            exam_id=exam_id,
            examinee_id=examinee_id,
            captured_at=captured_at,
            **result,
        )

    except InvalidImageError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(error),
        ) from error

    except RekognitionAPIError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(error),
        ) from error

    except Exception as error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="본인 인증 처리 중 예상하지 못한 오류가 발생했습니다.",
        ) from error

    finally:
        await source_image.close()
        await target_image.close()