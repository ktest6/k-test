"""
monitoring.py

시험 중 모니터링 프레임 분석 API를 정의한다.

처리 과정
1. 프론트엔드 또는 백엔드에서 모니터링 요청 수신
2. 현재 웹캠 캡처 이미지 수신
3. 필요한 경우 기준 얼굴 이미지 수신
4. 이미지 파일을 bytes로 변환
5. Monitoring Service 호출
6. 분석 결과 반환
"""

from datetime import datetime

from pydantic import ValidationError

from fastapi import (
    APIRouter,
    File,
    Form,
    HTTPException,
    UploadFile,
    status,
)

from app.schemas.monitoring import (
    GazeCalibrationResponse,
    MonitoringResponse,
    PreviousGazeState,
)
from modules.cheating_detection.service import (
    analyze_monitoring_frame,
    create_gaze_calibration_from_images,
)
from modules.common.exceptions import (
    GazeCalibrationError,
    InvalidImageError,
    MonitoringError,
    RekognitionAPIError,
)


router = APIRouter(
    prefix="/monitoring",
    tags=["Monitoring"],
)


def parse_previous_gaze_state(
    previous_gaze_state: str | None,
) -> dict[str, object] | None:
    """Form JSON 문자열을 이전 시선 상태로 검증한다."""

    if previous_gaze_state is None:
        return None

    try:
        state = PreviousGazeState.model_validate_json(
            previous_gaze_state,
        )
    except ValidationError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="previous_gaze_state JSON 형식이 올바르지 않습니다.",
        ) from error

    return state.model_dump()


@router.post(
    "/gaze-calibration",
    response_model=GazeCalibrationResponse,
    status_code=status.HTTP_200_OK,
)
async def calibrate_gaze(
    exam_id: str = Form(...),
    examinee_id: str = Form(...),
    calibration_images: list[UploadFile] = File(...),
) -> GazeCalibrationResponse:
    """화면 중앙 응시 이미지로 응시자별 시선 기준값을 계산한다."""

    if not calibration_images:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Calibration 이미지를 하나 이상 전달해야 합니다.",
        )

    try:
        calibration_image_bytes_list = [
            await calibration_image.read()
            for calibration_image in calibration_images
        ]
        calibration = create_gaze_calibration_from_images(
            exam_id=exam_id,
            examinee_id=examinee_id,
            calibration_image_bytes_list=calibration_image_bytes_list,
        )

        return GazeCalibrationResponse(
            exam_id=exam_id,
            examinee_id=examinee_id,
            calibrated=True,
            **calibration,
        )
    except (GazeCalibrationError, InvalidImageError) as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(error),
        ) from error
    except RekognitionAPIError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(error),
        ) from error


@router.post(
    "/analyze",
    response_model=MonitoringResponse,
    status_code=status.HTTP_200_OK,
)
async def analyze_frame(
    exam_id: str = Form(...),
    examinee_id: str = Form(...),
    request_id: str = Form(...),
    captured_at: datetime = Form(...),
    elapsed_ms: int = Form(...),
    capture_sequence: int = Form(...),
    run_identity_check: bool = Form(False),
    eye_yaw_center: float | None = Form(None),
    eye_pitch_center: float | None = Form(None),
    previous_gaze_state: str | None = Form(None),
    current_image: UploadFile = File(...),
    reference_image: UploadFile | None = File(None),
) -> MonitoringResponse:
    """
    시험 중 전달받은 웹캠 캡처 이미지 한 장을 분석한다.

    - 얼굴 수 및 화면 이탈 상태 확인
    - 필요한 경우 중간 동일인 검사
    - Rule Engine 판단
    - Event Engine 이벤트 생성
    - 클립 생성이 필요한 경우 클립 시간 범위 반환
    """

    if elapsed_ms < 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="elapsed_ms는 0 이상이어야 합니다.",
        )

    if capture_sequence < 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="capture_sequence는 1 이상이어야 합니다.",
        )

    if captured_at.tzinfo is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "captured_at에는 타임존 정보가 포함되어야 합니다. "
                "예: 2026-07-26T15:30:00+09:00"
            ),
        )

    try:
        parsed_previous_gaze_state = parse_previous_gaze_state(
            previous_gaze_state,
        )
        current_image_bytes = await current_image.read()

        reference_image_bytes = None

        if reference_image is not None:
            reference_image_bytes = await reference_image.read()

        monitoring_result = analyze_monitoring_frame(
            exam_id=exam_id,
            examinee_id=examinee_id,
            request_id=request_id,
            captured_at=captured_at,
            elapsed_ms=elapsed_ms,
            capture_sequence=capture_sequence,
            current_image_bytes=current_image_bytes,
            reference_image_bytes=reference_image_bytes,
            run_identity_check=run_identity_check,
            eye_yaw_center=eye_yaw_center,
            eye_pitch_center=eye_pitch_center,
            previous_gaze_state=parsed_previous_gaze_state,
        )

        return MonitoringResponse(
            **monitoring_result,
        )

    except HTTPException:
        raise

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

    except MonitoringError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(error),
        ) from error

    except Exception as error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="시험 모니터링 처리 중 오류가 발생했습니다.",
        ) from error
