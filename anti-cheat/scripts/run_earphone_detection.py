"""
run_earphone_detection.py

시험 전 이어폰 탐지 기능을 로컬 웹캠으로 테스트하는 실행 파일.

기능
- 웹캠 미리보기 표시
- 스페이스바로 왼쪽·오른쪽 귀 이미지 캡처
- 이어폰 탐지 서비스 실행
- 양쪽 귀 검사 결과 출력
- 시험 진행 가능 여부 출력

※ 캡처 이미지는 메모리에서 AWS로 전송한 뒤 분석 결과를 표시해 저장한다.
※ 이 파일은 이어폰 탐지 모듈 단독 테스트용이다.
"""

import argparse
import json
import platform
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any

import cv2
import numpy as np


# 프로젝트 루트 경로
PROJECT_ROOT = Path(__file__).resolve().parents[1]

# 프로젝트 모듈 import를 위한 경로 추가
sys.path.append(str(PROJECT_ROOT))

from modules.earphone_detection.service import (
    analyze_earphone_image,
)


WINDOW_NAME = "Pre-exam earphone detection test"
SPACE_KEY_CODE = 32
ESC_KEY_CODE = 27
GUIDE_COLOR = (0, 255, 0)
RESULT_TEXT_COLOR = (255, 255, 255)
RESULT_BACKGROUND_COLOR = (0, 0, 0)
OUTPUT_DIRECTORY = PROJECT_ROOT / "data" / "응시전_이어폰_감지_테스트"


def parse_args() -> argparse.Namespace:
    """사용할 웹캠 번호를 명령행에서 읽는다."""

    parser = argparse.ArgumentParser(
        description=(
            "웹캠 캡처로 Pose.Yaw 자세 확인을 포함한 "
            "시험 전 이어폰 탐지를 테스트합니다."
        ),
    )
    parser.add_argument(
        "--camera",
        type=int,
        default=0,
        help="사용할 카메라 번호 (기본값: 0)",
    )
    return parser.parse_args()


def create_camera(camera_index: int) -> cv2.VideoCapture:
    """운영체제에 맞는 OpenCV 백엔드로 웹캠을 연다."""

    if platform.system() == "Darwin":
        camera = cv2.VideoCapture(
            camera_index,
            cv2.CAP_AVFOUNDATION,
        )
    elif platform.system() == "Windows":
        camera = cv2.VideoCapture(camera_index, cv2.CAP_DSHOW)
    else:
        camera = cv2.VideoCapture(camera_index)

    if not camera.isOpened():
        camera.release()
        raise RuntimeError(
            f"카메라 {camera_index}을(를) 열 수 없습니다. "
            "macOS 카메라 권한과 연결 상태를 확인해 주세요."
        )

    return camera


def draw_capture_guide(
    frame: cv2.typing.MatLike,
    ear_name: str,
) -> cv2.typing.MatLike:
    """거울 모드 미리보기에 캡처 안내를 표시한다."""

    preview = cv2.flip(frame, 1)
    center, radius = get_capture_circle(preview)
    cv2.circle(
        preview,
        center,
        radius,
        GUIDE_COLOR,
        3,
        cv2.LINE_AA,
    )
    cv2.putText(
        preview,
        f"Place your {ear_name.upper()} ear inside the green circle",
        (24, 42),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.9,
        (0, 255, 255),
        2,
        cv2.LINE_AA,
    )
    cv2.putText(
        preview,
        "SPACE: capture   ESC: exit",
        (24, preview.shape[0] - 24),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.65,
        (255, 255, 255),
        2,
        cv2.LINE_AA,
    )
    return preview


def get_capture_circle(
    frame: cv2.typing.MatLike,
) -> tuple[tuple[int, int], int]:
    """귀 위치를 맞추는 중앙 가이드 원의 중심과 반지름을 계산한다."""

    height, width = frame.shape[:2]
    available_radius = min(width, height) // 2 - 12

    if available_radius < 20:
        raise RuntimeError("카메라 프레임 크기가 캡처하기에 너무 작습니다.")

    radius = int(min(width, height) * 0.16)
    radius = max(55, radius)
    radius = min(radius, available_radius)
    return (width // 2, height // 2), radius


def capture_image_bytes(
    camera: cv2.VideoCapture,
    ear_name: str,
) -> bytes | None:
    """스페이스바 입력 시 현재 프레임을 JPEG bytes로 반환한다."""

    print(
        f"{ear_name} 귀가 보이도록 고개를 돌리고 "
        "카메라 창에서 스페이스바를 누르세요."
    )

    while True:
        success, frame = camera.read()

        if not success:
            raise RuntimeError("카메라 프레임을 읽을 수 없습니다.")

        preview = draw_capture_guide(frame, ear_name)
        cv2.imshow(WINDOW_NAME, preview)
        key = cv2.waitKey(1) & 0xFF

        if key == ESC_KEY_CODE:
            return None

        if key == SPACE_KEY_CODE:
            # 초록색 원은 가이드로만 사용하고 전체 프레임을 전송한다.
            captured_frame = cv2.flip(frame, 1)
            encoded, buffer = cv2.imencode(".jpg", captured_frame)

            if not encoded:
                raise RuntimeError(
                    "캡처 이미지를 JPEG로 변환하지 못했습니다."
                )

            print(f"{ear_name} 귀 이미지를 캡처했습니다.")
            return buffer.tobytes()

        if cv2.getWindowProperty(
            WINDOW_NAME,
            cv2.WND_PROP_VISIBLE,
        ) < 1:
            return None


def capture_both_ears(
    camera_index: int,
) -> tuple[bytes, bytes] | None:
    """한 카메라 세션에서 왼쪽과 오른쪽 귀를 차례로 캡처한다."""

    camera = create_camera(camera_index)
    cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)

    try:
        left_image_bytes = capture_image_bytes(camera, "left")

        if left_image_bytes is None:
            return None

        right_image_bytes = capture_image_bytes(camera, "right")

        if right_image_bytes is None:
            return None

        return left_image_bytes, right_image_bytes

    finally:
        camera.release()
        cv2.destroyAllWindows()


def print_result(title: str, result: dict[str, Any]) -> None:
    """이어폰 탐지 결과를 출력한다."""

    print("=" * 60)
    print(title)
    print("=" * 60)

    print(
        json.dumps(
            result,
            indent=4,
            ensure_ascii=False,
        )
    )
    print()


def draw_result_overlay(
    image_bytes: bytes,
    ear_name: str,
    result: dict[str, Any],
    can_proceed: bool,
) -> cv2.typing.MatLike:
    """캡처 이미지 좌측 상단에 AWS 분석 결과를 표시한다."""

    image_array = np.frombuffer(image_bytes, dtype=np.uint8)
    image = cv2.imdecode(image_array, cv2.IMREAD_COLOR)

    if image is None:
        raise RuntimeError("결과를 기록할 캡처 이미지를 읽지 못했습니다.")

    label = result.get("label") or "None"
    confidence = float(result.get("confidence", 0.0) or 0.0)
    lines = [
        f"Ear: {ear_name}",
        f"Pose.Yaw: {result.get('yaw')}",
        f"Yaw threshold: {result.get('yaw_threshold')}",
        f"Ear visible: {result.get('ear_visible')}",
        f"Earphone detected: {result.get('earphone_detected')}",
        f"Label / confidence: {label} / {confidence:.2f}",
        f"Can proceed: {can_proceed}",
    ]
    font = cv2.FONT_HERSHEY_SIMPLEX
    font_scale = max(0.45, min(image.shape[:2]) / 900.0)
    thickness = 1 if font_scale < 0.7 else 2
    line_height = int(28 * max(font_scale, 0.6))
    padding = 12
    text_width = max(
        cv2.getTextSize(line, font, font_scale, thickness)[0][0]
        for line in lines
    )
    box_height = padding * 2 + line_height * len(lines)
    overlay = image.copy()
    cv2.rectangle(
        overlay,
        (0, 0),
        (min(image.shape[1], text_width + padding * 2), box_height),
        RESULT_BACKGROUND_COLOR,
        thickness=-1,
    )
    cv2.addWeighted(overlay, 0.7, image, 0.3, 0, image)

    for index, line in enumerate(lines):
        y = padding + line_height * (index + 1) - 6
        cv2.putText(
            image,
            line,
            (padding, y),
            font,
            font_scale,
            RESULT_TEXT_COLOR,
            thickness,
            cv2.LINE_AA,
        )

    return image


def save_test_artifacts(
    left_image_bytes: bytes,
    right_image_bytes: bytes,
    left_result: dict[str, Any],
    right_result: dict[str, Any],
    final_result: dict[str, Any],
) -> dict[str, str]:
    """결과가 표시된 캡처 이미지와 전체 JSON을 data 아래 저장한다."""

    OUTPUT_DIRECTORY.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    left_path = OUTPUT_DIRECTORY / f"{timestamp}_left.jpg"
    right_path = OUTPUT_DIRECTORY / f"{timestamp}_right.jpg"
    json_path = OUTPUT_DIRECTORY / f"{timestamp}_result.json"
    can_proceed = bool(final_result["can_proceed"])
    left_image = draw_result_overlay(
        left_image_bytes,
        "left",
        left_result,
        can_proceed,
    )
    right_image = draw_result_overlay(
        right_image_bytes,
        "right",
        right_result,
        can_proceed,
    )

    if not cv2.imwrite(str(left_path), left_image):
        raise RuntimeError(f"왼쪽 결과 이미지를 저장하지 못했습니다: {left_path}")

    if not cv2.imwrite(str(right_path), right_image):
        raise RuntimeError(f"오른쪽 결과 이미지를 저장하지 못했습니다: {right_path}")

    artifact_result = {
        "left_image": str(left_path),
        "right_image": str(right_path),
        "result_json": str(json_path),
    }
    json_payload = {
        **final_result,
        "left_result": left_result,
        "right_result": right_result,
        "artifacts": artifact_result,
    }

    with json_path.open("w", encoding="utf-8") as file:
        json.dump(json_payload, file, ensure_ascii=False, indent=4)

    return artifact_result


def main() -> int:
    """시험 전 이어폰 탐지 기능을 테스트한다."""

    try:
        args = parse_args()
        captured_images = capture_both_ears(args.camera)

        if captured_images is None:
            print("사용자가 이어폰 탐지 테스트를 종료했습니다.")
            return 0

        left_image_bytes, right_image_bytes = captured_images

        print("캡처가 완료되었습니다. AWS 분석을 시작합니다.")

        left_result = analyze_earphone_image(
            image_bytes=left_image_bytes,
            image_name="왼쪽 귀",
        )

        right_result = analyze_earphone_image(
            image_bytes=right_image_bytes,
            image_name="오른쪽 귀",
        )

        print_result(
            "왼쪽 귀 검사 결과",
            left_result,
        )

        print_result(
            "오른쪽 귀 검사 결과",
            right_result,
        )

        earphone_detected = (
            left_result["earphone_detected"]
            or right_result["earphone_detected"]
        )
        inspection_complete = (
            left_result["ear_visible"]
            and right_result["ear_visible"]
        )

        if earphone_detected:
            message = "시험 시작 전에 이어폰을 제거해 주세요."
        elif not inspection_complete:
            message = "얼굴을 옆으로 돌려 양쪽 귀를 모두 보여 주세요."
        else:
            message = "이어폰이 탐지되지 않았습니다."

        final_result = {
            "inspection_complete": inspection_complete,
            "earphone_detected": earphone_detected,
            "can_proceed": (
                inspection_complete and not earphone_detected
            ),
            "left_ear_visible": left_result["ear_visible"],
            "right_ear_visible": right_result["ear_visible"],
            "left_yaw": left_result["yaw"],
            "right_yaw": right_result["yaw"],
            "yaw_threshold": left_result["yaw_threshold"],
            "left_ear_detected": left_result["earphone_detected"],
            "right_ear_detected": right_result["earphone_detected"],
            "message": message,
        }
        final_result["artifacts"] = save_test_artifacts(
            left_image_bytes=left_image_bytes,
            right_image_bytes=right_image_bytes,
            left_result=left_result,
            right_result=right_result,
            final_result=final_result,
        )
        print_result("최종 JSON 결과", final_result)
        return 0

    except Exception:
        print("=" * 60)
        print("이어폰 탐지 테스트 실패")
        print("=" * 60)

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
