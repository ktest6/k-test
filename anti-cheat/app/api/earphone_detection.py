"""
earphone_detection.py

이어폰 탐지 API 라우터.

- 시험 및 응시자 정보 수신
- 왼쪽 귀 이미지 파일 수신
- 오른쪽 귀 이미지 파일 수신
- 이미지 파일을 bytes로 변환
- 이어폰 탐지 서비스 호출
- 양쪽 귀 결과를 종합하여 최종 탐지 결과 반환
"""

from fastapi import (
    APIRouter,
    File,
    Form,
    HTTPException,
    UploadFile,
    status,
)

from app.schemas.earphone_detection import EarphoneDetectionResponse
from modules.common.exceptions import (
    EarphoneDetectionError,
    InvalidImageError,
    RekognitionAPIError,
)
from modules.earphone_detection.service import analyze_earphone_image


router = APIRouter(
    prefix="/earphone",
    tags=["Earphone Detection"],
)


@router.post(
    "/detect",
    response_model=EarphoneDetectionResponse,
    status_code=status.HTTP_200_OK,
)
async def detect_earphone_api(
    exam_id: str = Form(
        ...,
        description="시험 식별자",
    ),
    examinee_id: str = Form(
        ...,
        description="응시자 식별자",
    ),
    left_ear_image: UploadFile = File(
        ...,
        description="왼쪽 귀 이미지",
    ),
    right_ear_image: UploadFile = File(
        ...,
        description="오른쪽 귀 이미지",
    ),
) -> EarphoneDetectionResponse:
    """시험 시작 전 양쪽 귀 이미지에서 이어폰 착용 여부를 검사한다."""

    try:
        left_image_bytes = await left_ear_image.read()
        right_image_bytes = await right_ear_image.read()

        left_result = analyze_earphone_image(
            image_bytes=left_image_bytes,
            image_name="왼쪽 귀 이미지",
        )

        right_result = analyze_earphone_image(
            image_bytes=right_image_bytes,
            image_name="오른쪽 귀 이미지",
        )

        earphone_detected = (
            left_result["earphone_detected"]
            or right_result["earphone_detected"]
        )

        if earphone_detected:
            message = "시험 시작 전에 이어폰을 제거해 주세요."
        else:
            message = "이어폰이 탐지되지 않았습니다."

        return EarphoneDetectionResponse(
            exam_id=exam_id,
            examinee_id=examinee_id,
            earphone_detected=earphone_detected,
            left_ear_detected=left_result["earphone_detected"],
            right_ear_detected=right_result["earphone_detected"],
            left_label=left_result["label"],
            right_label=right_result["label"],
            left_confidence=left_result["confidence"],
            right_confidence=right_result["confidence"],
            threshold=left_result["threshold"],
            message=message,
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

    except EarphoneDetectionError as error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(error),
        ) from error

    except Exception as error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="이어폰 탐지 처리 중 예상하지 못한 오류가 발생했습니다.",
        ) from error

    finally:
        await left_ear_image.close()
        await right_ear_image.close()