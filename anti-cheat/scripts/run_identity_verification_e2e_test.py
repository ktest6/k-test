"""로컬 카메라를 사용하는 본인 인증 통합 테스트 실행 도구.

신청 정보 입력, 여권 이미지 선택, 얼굴 촬영, 본인 인증 서비스 호출을
실제 API 요청 순서와 같은 흐름으로 실행한다. 실행 기록과 각 시도의 응답은
날짜/시각 이름의 JSON 파일에 즉시 저장한다.
"""

from __future__ import annotations

import json
import platform
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import numpy as np
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog

try:
    import cv2
except ModuleNotFoundError as import_error:
    cv2 = None  # type: ignore[assignment]
    CV2_IMPORT_ERROR: ModuleNotFoundError | None = import_error
else:
    CV2_IMPORT_ERROR = None


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(PROJECT_ROOT))

from app.schemas.identity import DocumentType, IdentityVerificationResponse
from modules.common.exceptions import ProctoringError


WINDOW_NAME = "Identity verification integration test"
OUTPUT_DIRECTORY = PROJECT_ROOT / "data" / "logs" / "identity_verification"
CAPTURE_KEY_CODES = {10, 13, 32}
ESC_KEY_CODE = 27
GREEN = (0, 220, 0)
WHITE = (255, 255, 255)
BLACK = (0, 0, 0)


@dataclass(frozen=True)
class ApplicantInput:
    """백엔드가 본인 인증 API에 전달하는 사전 정보."""

    exam_id: str
    examinee_id: str
    last_name: str
    first_name: str
    birth_date: date
    document_number: str
    document_type: DocumentType = DocumentType.PASSPORT

    def as_log_data(self) -> dict[str, str]:
        """JSON 기록용 API 필드 구조로 변환한다."""

        return {
            "exam_id": self.exam_id,
            "examinee_id": self.examinee_id,
            "last_name": self.last_name,
            "first_name": self.first_name,
            "birth_date": self.birth_date.isoformat(),
            "document_number": self.document_number,
            "document_type": self.document_type.value,
        }


class JsonRunLogger:
    """통합 테스트 상태를 매 이벤트마다 JSON 파일에 반영한다."""

    def __init__(self, output_directory: Path = OUTPUT_DIRECTORY) -> None:
        started_at = datetime.now().astimezone()
        output_directory.mkdir(parents=True, exist_ok=True)
        self.path = output_directory / started_at.strftime(
            "%Y-%m-%d_%H-%M-%S_%f.json"
        )
        self.document: dict[str, Any] = {
            "started_at": started_at.isoformat(),
            "finished_at": None,
            "termination": None,
            "request": None,
            "source_image": None,
            "attempts": [],
            "events": [],
        }
        self.add_event("integration_test_started")

    def write(self) -> None:
        """현재 상태를 UTF-8 JSON으로 즉시 저장한다."""

        self.path.write_text(
            json.dumps(self.document, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def add_event(self, event: str, **data: Any) -> None:
        """시각이 포함된 실행 이벤트를 추가하고 저장한다."""

        entry: dict[str, Any] = {
            "timestamp": datetime.now().astimezone().isoformat(),
            "event": event,
        }
        if data:
            entry["data"] = data
        self.document["events"].append(entry)
        self.write()

    def set_request(self, applicant: ApplicantInput) -> None:
        """입력이 끝난 신청 정보를 기록한다."""

        self.document["request"] = applicant.as_log_data()
        self.add_event("applicant_information_entered", **applicant.as_log_data())

    def add_attempt(self, attempt: dict[str, Any]) -> None:
        """한 번의 얼굴 캡처 및 인증 결과를 기록한다."""

        self.document["attempts"].append(attempt)
        self.add_event(
            "identity_verification_completed",
            attempt_number=attempt["attempt_number"],
            status=attempt["status"],
            response=attempt.get("response"),
            error=attempt.get("error"),
        )

    def finish(self, reason: str, verified: bool) -> None:
        """종료 방식과 최종 인증 여부를 기록한다."""

        self.document["finished_at"] = datetime.now().astimezone().isoformat()
        self.document["termination"] = {
            "reason": reason,
            "verified": verified,
        }
        self.add_event("integration_test_finished", reason=reason, verified=verified)


def prompt_required_text(
    root: tk.Tk,
    title: str,
    prompt: str,
    initial_value: str = "",
) -> str | None:
    """취소할 때까지 필수 문자열 한 항목을 입력받는다."""

    while True:
        value = simpledialog.askstring(
            title,
            prompt,
            initialvalue=initial_value,
            parent=root,
        )
        if value is None:
            return None
        value = value.strip()
        if value:
            return value
        messagebox.showwarning(title, "필수 입력 항목입니다.", parent=root)


def collect_applicant_input(root: tk.Tk) -> ApplicantInput | None:
    """API 폼 순서대로 신청 정보를 입력받는다."""

    field_specs = (
        ("시험 ID", "exam_id를 입력하세요."),
        ("응시자 ID", "examinee_id를 입력하세요."),
        ("성", "신청 정보의 last_name을 입력하세요."),
        ("이름", "신청 정보의 first_name을 입력하세요."),
    )
    values: list[str] = []
    for title, prompt in field_specs:
        value = prompt_required_text(root, title, prompt)
        if value is None:
            return None
        values.append(value)

    while True:
        raw_birth_date = prompt_required_text(
            root,
            "생년월일",
            "birth_date를 YYYY-MM-DD 형식으로 입력하세요.",
        )
        if raw_birth_date is None:
            return None
        try:
            birth_date = date.fromisoformat(raw_birth_date)
            break
        except ValueError:
            messagebox.showerror(
                "생년월일",
                "YYYY-MM-DD 형식의 실제 날짜를 입력하세요.",
                parent=root,
            )

    document_number = prompt_required_text(
        root,
        "여권번호",
        "document_number를 입력하세요.",
    )
    if document_number is None:
        return None

    messagebox.showinfo(
        "신분증 종류",
        "현재 API가 지원하는 document_type은 passport입니다.",
        parent=root,
    )
    return ApplicantInput(
        exam_id=values[0],
        examinee_id=values[1],
        last_name=values[2],
        first_name=values[3],
        birth_date=birth_date,
        document_number=document_number,
    )


def select_source_image(root: tk.Tk) -> Path | None:
    """검증할 신분증 이미지 파일을 선택한다."""

    selected = filedialog.askopenfilename(
        title="신분증 이미지를 선택하세요",
        filetypes=(
            ("Image files", "*.jpg *.jpeg *.png"),
            ("All files", "*.*"),
        ),
        parent=root,
    )
    return Path(selected) if selected else None


def create_camera(camera_index: int = 0) -> cv2.VideoCapture:
    """운영체제에 맞는 OpenCV 백엔드로 카메라를 연다."""

    if platform.system() == "Darwin":
        camera = cv2.VideoCapture(camera_index, cv2.CAP_AVFOUNDATION)
    elif platform.system() == "Windows":
        camera = cv2.VideoCapture(camera_index, cv2.CAP_DSHOW)
    else:
        camera = cv2.VideoCapture(camera_index)
    if not camera.isOpened():
        camera.release()
        raise RuntimeError("카메라를 열 수 없습니다. 권한과 연결 상태를 확인하세요.")
    return camera


def circle_geometry(frame: np.ndarray) -> tuple[tuple[int, int], int]:
    """프레임 중앙 얼굴 가이드의 중심과 반지름을 계산한다."""

    height, width = frame.shape[:2]
    radius = max(80, int(min(width, height) * 0.3))
    radius = min(radius, width // 2 - 12, height // 2 - 12)
    return (width // 2, height // 2), radius


def draw_capture_preview(frame: np.ndarray) -> np.ndarray:
    """거울 모드 화면에 중앙 초록색 원과 안내 문구를 표시한다."""

    preview = cv2.flip(frame, 1)
    center, radius = circle_geometry(preview)
    cv2.circle(preview, center, radius, GREEN, 3, cv2.LINE_AA)
    cv2.putText(
        preview,
        "Align your face within the green circle",
        (max(20, center[0] - radius), max(40, center[1] - radius - 24)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.72,
        WHITE,
        2,
        cv2.LINE_AA,
    )
    cv2.putText(
        preview,
        "SPACE/ENTER: capture   ESC: exit",
        (20, preview.shape[0] - 24),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.62,
        WHITE,
        2,
        cv2.LINE_AA,
    )
    return preview


def crop_circle(frame: np.ndarray) -> np.ndarray:
    """중앙 원 바깥을 검게 마스킹한 정사각형 얼굴 이미지를 만든다."""

    center, radius = circle_geometry(frame)
    left, top = center[0] - radius, center[1] - radius
    right, bottom = center[0] + radius, center[1] + radius
    cropped = frame[top:bottom, left:right].copy()
    mask = np.zeros(cropped.shape[:2], dtype=np.uint8)
    cv2.circle(mask, (radius, radius), radius - 2, 255, thickness=-1)
    return cv2.bitwise_and(cropped, cropped, mask=mask)


def capture_face(camera_index: int = 0) -> tuple[bytes | None, str]:
    """중앙 원 안의 얼굴을 JPEG bytes로 캡처하거나 ESC 종료를 반환한다."""

    camera = create_camera(camera_index)
    cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)
    try:
        while True:
            success, frame = camera.read()
            if not success:
                raise RuntimeError("카메라 프레임을 읽을 수 없습니다.")
            cv2.imshow(WINDOW_NAME, draw_capture_preview(frame))
            key = cv2.waitKey(1) & 0xFF
            if key == ESC_KEY_CODE:
                return None, "esc"
            if key in CAPTURE_KEY_CODES:
                # 사용자가 본 거울 화면과 같은 방향으로 캡처한다.
                circular_face = crop_circle(cv2.flip(frame, 1))
                encoded, buffer = cv2.imencode(".jpg", circular_face)
                if not encoded:
                    raise RuntimeError("얼굴 캡처 이미지를 JPEG로 변환하지 못했습니다.")
                return buffer.tobytes(), "captured"
            if cv2.getWindowProperty(WINDOW_NAME, cv2.WND_PROP_VISIBLE) < 1:
                return None, "window_closed"
    finally:
        camera.release()
        cv2.destroyAllWindows()


def build_api_response(
    applicant: ApplicantInput,
    captured_at: datetime,
    service_result: dict[str, Any],
) -> dict[str, Any]:
    """서비스 결과를 실제 본인 인증 API 응답 스키마로 검증·변환한다."""

    response = IdentityVerificationResponse(
        exam_id=applicant.exam_id,
        examinee_id=applicant.examinee_id,
        captured_at=captured_at,
        **service_result,
    )
    return response.model_dump(mode="json")


def error_response(error: Exception) -> dict[str, Any]:
    """예외를 API 오류 응답과 같은 detail/code/params 구조로 변환한다."""

    response: dict[str, Any] = {
        "detail": str(error),
        "code": getattr(error, "code", "IDENTITY_VERIFICATION_INTERNAL_ERROR"),
    }
    params = getattr(error, "params", None)
    if params:
        response["params"] = params
    return response


def show_failure_screen(response: dict[str, Any]) -> str:
    """실패 결과와 클릭 가능한 Retry/Exit 버튼을 표시한다."""

    width, height = 760, 420
    screen = np.full((height, width, 3), 245, dtype=np.uint8)
    retry_box = (120, 290, 350, 365)
    exit_box = (410, 290, 640, 365)
    selection = {"value": ""}

    def on_mouse(event: int, x: int, y: int, flags: int, data: Any) -> None:
        del flags, data
        if event != cv2.EVENT_LBUTTONUP:
            return
        if retry_box[0] <= x <= retry_box[2] and retry_box[1] <= y <= retry_box[3]:
            selection["value"] = "retry"
        elif exit_box[0] <= x <= exit_box[2] and exit_box[1] <= y <= exit_box[3]:
            selection["value"] = "failure_exit"

    cv2.putText(screen, "Identity verification failed", (145, 95), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 210), 2, cv2.LINE_AA)
    message = str(response.get("message") or response.get("detail") or "Please try again.")
    cv2.putText(screen, message[:72], (70, 170), cv2.FONT_HERSHEY_SIMPLEX, 0.62, BLACK, 2, cv2.LINE_AA)
    cv2.rectangle(screen, retry_box[:2], retry_box[2:], (40, 160, 40), thickness=-1)
    cv2.rectangle(screen, exit_box[:2], exit_box[2:], (110, 110, 110), thickness=-1)
    cv2.putText(screen, "Retry capture", (145, 338), cv2.FONT_HERSHEY_SIMPLEX, 0.72, WHITE, 2, cv2.LINE_AA)
    cv2.putText(screen, "Exit", (495, 338), cv2.FONT_HERSHEY_SIMPLEX, 0.72, WHITE, 2, cv2.LINE_AA)
    cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_AUTOSIZE)
    cv2.setMouseCallback(WINDOW_NAME, on_mouse)
    try:
        while not selection["value"]:
            cv2.imshow(WINDOW_NAME, screen)
            key = cv2.waitKey(20) & 0xFF
            if key == ESC_KEY_CODE:
                return "esc"
            if key in (ord("r"), ord("R")):
                return "retry"
            if cv2.getWindowProperty(WINDOW_NAME, cv2.WND_PROP_VISIBLE) < 1:
                return "window_closed"
        return selection["value"]
    finally:
        cv2.destroyAllWindows()


def show_success_screen() -> None:
    """성공 문구를 잠시 표시한 뒤 자동으로 닫는다."""

    screen = np.full((260, 700, 3), 245, dtype=np.uint8)
    cv2.putText(screen, "Identity verification succeeded", (90, 135), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (30, 170, 30), 2, cv2.LINE_AA)
    cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_AUTOSIZE)
    cv2.imshow(WINDOW_NAME, screen)
    cv2.waitKey(1800)
    cv2.destroyAllWindows()


def run_integration_test(logger: JsonRunLogger, root: tk.Tk) -> tuple[str, bool]:
    """신청 정보부터 인증 완료까지 통합 테스트 한 세션을 실행한다."""

    # 환경 설정/AWS·Azure 클라이언트 로딩 오류도 main에서 JSON에 기록되게 한다.
    from modules.identity_verification.service import verify_identity

    applicant = collect_applicant_input(root)
    if applicant is None:
        return "esc_or_dialog_cancelled", False
    logger.set_request(applicant)

    source_image_path = select_source_image(root)
    if source_image_path is None:
        return "esc_or_dialog_cancelled", False
    source_image_bytes = source_image_path.read_bytes()
    logger.document["source_image"] = {
        "path": str(source_image_path),
        "size_bytes": len(source_image_bytes),
    }
    logger.add_event(
        "source_image_selected",
        path=str(source_image_path),
        size_bytes=len(source_image_bytes),
    )

    attempt_number = 0
    while True:
        attempt_number += 1
        logger.add_event("face_capture_started", attempt_number=attempt_number)
        target_image_bytes, capture_status = capture_face()
        if target_image_bytes is None:
            logger.add_event(
                "face_capture_cancelled",
                attempt_number=attempt_number,
                reason=capture_status,
            )
            return capture_status, False

        captured_at = datetime.now().astimezone()
        logger.add_event(
            "face_captured",
            attempt_number=attempt_number,
            captured_at=captured_at.isoformat(),
            size_bytes=len(target_image_bytes),
        )
        attempt: dict[str, Any] = {
            "attempt_number": attempt_number,
            "captured_at": captured_at.isoformat(),
        }
        try:
            service_result = verify_identity(
                source_image_bytes=source_image_bytes,
                target_image_bytes=target_image_bytes,
                last_name=applicant.last_name,
                first_name=applicant.first_name,
                birth_date=applicant.birth_date,
                document_number=applicant.document_number,
                document_type=applicant.document_type,
            )
            response = build_api_response(applicant, captured_at, service_result)
            attempt.update(
                status="success" if response["verified"] else "failure",
                response=response,
            )
        except Exception as error:
            attempt.update(status="error", error=error_response(error))

        logger.add_attempt(attempt)
        result = attempt.get("response") or attempt["error"]
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if attempt["status"] == "success":
            show_success_screen()
            return "identity_verification_completed", True

        action = show_failure_screen(result)
        logger.add_event(
            "failure_action_selected",
            attempt_number=attempt_number,
            action=action,
        )
        if action != "retry":
            return action, False


def main() -> None:
    """본인 인증 통합 테스트를 실행하고 모든 종료 시 JSON을 완성한다."""

    logger = JsonRunLogger()
    if CV2_IMPORT_ERROR is not None:
        error = RuntimeError(
            "카메라 통합 테스트에 opencv-python이 필요합니다. "
            "의존성을 설치한 뒤 다시 실행하세요."
        )
        logger.add_event("dependency_error", error=error_response(error))
        logger.finish("dependency_error", False)
        print(error)
        print(f"통합 테스트 JSON: {logger.path}")
        return

    root = tk.Tk()
    root.withdraw()
    termination_reason = "unexpected_error"
    verified = False
    try:
        termination_reason, verified = run_integration_test(logger, root)
    except KeyboardInterrupt:
        termination_reason = "keyboard_interrupt"
        logger.add_event("integration_test_interrupted")
    except (OSError, RuntimeError, ProctoringError) as error:
        logger.add_event("integration_test_error", error=error_response(error))
        messagebox.showerror("통합 테스트 오류", str(error), parent=root)
    except Exception as error:
        logger.add_event("unexpected_error", error=error_response(error))
        messagebox.showerror("예상하지 못한 오류", str(error), parent=root)
    finally:
        cv2.destroyAllWindows()
        root.destroy()
        logger.finish(termination_reason, verified)
        print(f"통합 테스트 JSON: {logger.path}")


if __name__ == "__main__":
    main()
