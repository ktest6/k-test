"""macOS와 Windows에서 사용하는 로컬 카메라 녹화 실험 도구.

조작법:
- Space: 녹화 시작/중단
- Q: 화면 중앙의 캘리브레이션 점 표시/숨김
- Esc 또는 창 닫기: 종료
"""

from __future__ import annotations

import argparse
import platform
import tkinter
from datetime import datetime
from pathlib import Path

import cv2


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIRECTORY = PROJECT_ROOT / "data" / "camera_recordings"
WINDOW_NAME = "Anti-cheat local camera test"
RECORDING_FOURCC = "mp4v"


def parse_arguments() -> argparse.Namespace:
    """카메라 번호와 녹화 파일 저장 경로를 읽는다."""

    parser = argparse.ArgumentParser(
        description="로컬 웹캠으로 안티치트 실험 영상을 녹화합니다.",
    )
    parser.add_argument(
        "--camera",
        type=int,
        default=0,
        help="사용할 카메라 번호 (기본값: 0)",
    )
    parser.add_argument(
        "--output-directory",
        type=Path,
        default=DEFAULT_OUTPUT_DIRECTORY,
        help="녹화 파일 저장 디렉터리",
    )
    return parser.parse_args()


def create_camera(camera_index: int) -> cv2.VideoCapture:
    """운영체제에 맞는 백엔드로 카메라를 연다."""

    system = platform.system()
    if system == "Darwin":
        camera = cv2.VideoCapture(camera_index, cv2.CAP_AVFOUNDATION)
    elif system == "Windows":
        camera = cv2.VideoCapture(camera_index, cv2.CAP_DSHOW)
    else:
        camera = cv2.VideoCapture(camera_index)

    if not camera.isOpened():
        camera.release()
        raise RuntimeError(
            f"카메라 {camera_index}을(를) 열 수 없습니다. "
            "카메라 권한과 사용 중인 앱을 확인해 주세요."
        )
    return camera


def create_recording_path(output_directory: Path) -> Path:
    """현재 날짜와 시각으로 중복되지 않는 녹화 경로를 만든다."""

    output_directory.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    return output_directory / f"camera_{timestamp}.mp4"


def create_writer(
    output_path: Path,
    fps: float,
    frame_width: int,
    frame_height: int,
) -> cv2.VideoWriter:
    """MP4 녹화 writer를 만들고 정상 초기화 여부를 검증한다."""

    writer = cv2.VideoWriter(
        str(output_path),
        cv2.VideoWriter_fourcc(*RECORDING_FOURCC),
        fps,
        (frame_width, frame_height),
    )
    if not writer.isOpened():
        writer.release()
        raise RuntimeError(f"녹화 파일을 만들 수 없습니다: {output_path}")
    return writer


def get_screen_size() -> tuple[int, int]:
    """기본 모니터의 가로와 세로 픽셀 크기를 반환한다."""

    root = tkinter.Tk()
    root.withdraw()
    try:
        return root.winfo_screenwidth(), root.winfo_screenheight()
    finally:
        root.destroy()


def draw_preview_overlay(
    frame: cv2.typing.MatLike,
    calibration_point_visible: bool,
    recording: bool,
) -> cv2.typing.MatLike:
    """원본과 분리된 거울 모드 미리보기에만 안내를 그린다."""

    preview = cv2.flip(frame, 1)
    height, width = preview.shape[:2]

    if calibration_point_visible:
        cv2.circle(
            preview,
            (width // 2, height // 2),
            9,
            (0, 0, 255),
            thickness=-1,
            lineType=cv2.LINE_AA,
        )

    status = "REC" if recording else "READY"
    status_color = (0, 0, 255) if recording else (255, 255, 255)
    cv2.putText(
        preview,
        status,
        (24, 42),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.0,
        status_color,
        2,
        cv2.LINE_AA,
    )
    cv2.putText(
        preview,
        "SPACE: record  Q: center point  ESC: exit",
        (24, height - 24),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.65,
        (255, 255, 255),
        2,
        cv2.LINE_AA,
    )
    return preview


def run_camera_test(camera_index: int, output_directory: Path) -> None:
    """카메라 미리보기와 키 입력 기반 녹화를 실행한다."""

    camera = create_camera(camera_index)
    writer: cv2.VideoWriter | None = None
    output_path: Path | None = None
    calibration_point_visible = True

    try:
        success, frame = camera.read()
        if not success:
            raise RuntimeError("카메라에서 첫 프레임을 읽을 수 없습니다.")

        frame_height, frame_width = frame.shape[:2]
        camera_fps = camera.get(cv2.CAP_PROP_FPS)
        fps = camera_fps if camera_fps > 1.0 else 30.0

        screen_width, screen_height = get_screen_size()
        cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(WINDOW_NAME, screen_width, screen_height)
        cv2.moveWindow(WINDOW_NAME, 0, 0)

        while True:
            success, frame = camera.read()
            if not success:
                raise RuntimeError("카메라 프레임 읽기에 실패했습니다.")

            # 오버레이를 그리기 전 원본만 저장한다.
            if writer is not None:
                writer.write(frame)

            preview = draw_preview_overlay(
                frame,
                calibration_point_visible,
                writer is not None,
            )
            cv2.imshow(WINDOW_NAME, preview)

            key = cv2.waitKey(1) & 0xFF
            if key == 27:
                break
            if key in (ord("q"), ord("Q")):
                calibration_point_visible = not calibration_point_visible
            elif key == ord(" "):
                if writer is None:
                    output_path = create_recording_path(output_directory)
                    writer = create_writer(
                        output_path,
                        fps,
                        frame_width,
                        frame_height,
                    )
                    print(f"녹화 시작: {output_path}")
                else:
                    writer.release()
                    writer = None
                    print(f"녹화 완료: {output_path}")

            if cv2.getWindowProperty(WINDOW_NAME, cv2.WND_PROP_VISIBLE) < 1:
                break
    finally:
        if writer is not None:
            writer.release()
            print(f"녹화 완료: {output_path}")
        camera.release()
        cv2.destroyAllWindows()


def main() -> None:
    """명령행 인자로 로컬 카메라 실험을 시작한다."""

    arguments = parse_arguments()
    run_camera_test(arguments.camera, arguments.output_directory)


if __name__ == "__main__":
    main()
