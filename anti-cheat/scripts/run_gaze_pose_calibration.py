"""
맥북 내장 카메라를 이용한 고개/시선 캘리브레이션 및 1분 테스트.

결과 구조:
data/gaze_pose_tests/<실행 시각>/
├── recording.mp4
├── calibration/          # 중앙 점 캘리브레이션 이미지 6장
├── captures/             # 1초 간격 원본 캡처 이미지 60장
├── annotated/            # 분석값이 표시된 이미지 60장
└── analysis.json         # 캘리브레이션 및 전체 분석 결과
"""

import json
import os
import time
from datetime import datetime
from pathlib import Path

import boto3
import cv2
from botocore.exceptions import BotoCoreError, ClientError
from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageFont


# ============================================================
# 실행 설정
# ============================================================

CAMERA_INDEX = 0  # 맥북 내장 카메라. 외장 카메라는 숫자를 변경하세요.
CALIBRATION_SECONDS = 3.0
CALIBRATION_IMAGE_COUNT = 6
TEST_SECONDS = 60.0
TEST_IMAGE_COUNT = 60

# 눈 시선 판정 기준
EYE_YAW_THRESHOLD = 15.0
EYE_PITCH_THRESHOLD = 15.0
MINIMUM_EYE_CONFIDENCE = 80.0

# 고개 Yaw 판정 기준
HEAD_YAW_NORMAL_THRESHOLD = 10.0
HEAD_YAW_LOW_THRESHOLD = 15.0
HEAD_YAW_MEDIUM_THRESHOLD = 20.0

# 고개 Pitch 판정 기준. AWS 값에서 음수는 아래, 양수는 위로 본다.
HEAD_PITCH_DOWN_MEDIUM_THRESHOLD = -5.0
HEAD_PITCH_DOWN_HIGH_THRESHOLD = -10.0
HEAD_PITCH_UP_LOW_THRESHOLD = 10.0
HEAD_PITCH_UP_MEDIUM_THRESHOLD = 15.0
HEAD_PITCH_UP_HIGH_THRESHOLD = 20.0

SEVERITY_PRIORITY = {
    "NORMAL": 0,
    "LOW": 1,
    "MEDIUM": 2,
    "HIGH": 3,
    "UNKNOWN": -1,
}

# 결과 폴더 경로 입력
OUTPUT_ROOT = Path("/Users/apple/dio_folder/python/ktest_git/k-test/anti-cheat/data/gaze_pose_tests")


def create_rekognition_client():
    load_dotenv()
    return boto3.client(
        "rekognition",
        region_name=os.getenv("AWS_REGION"),
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
    )


def round_value(value):
    return round(float(value), 2) if value is not None else None


def detect_gaze_pose(client, image_bytes: bytes) -> dict:
    response = client.detect_faces(
        Image={"Bytes": image_bytes},
        Attributes=["ALL"],
    )
    faces = response.get("FaceDetails", [])
    if not faces:
        return {
            "face_count": 0,
            "face_confidence": None,
            "head": None,
            "gaze": None,
        }

    # 화면에 여러 얼굴이 잡히면 가장 큰 얼굴을 테스트 대상자로 사용한다.
    face = max(
        faces,
        key=lambda item: (
            item.get("BoundingBox", {}).get("Width", 0)
            * item.get("BoundingBox", {}).get("Height", 0)
        ),
    )
    pose = face.get("Pose", {})
    gaze = face.get("EyeDirection", {})
    return {
        "face_count": len(faces),
        "face_confidence": round_value(face.get("Confidence")),
        "head": {
            "yaw": round_value(pose.get("Yaw")),
            "pitch": round_value(pose.get("Pitch")),
            "roll": round_value(pose.get("Roll")),
        },
        "gaze": {
            "yaw": round_value(gaze.get("Yaw")),
            "pitch": round_value(gaze.get("Pitch")),
            "confidence": round_value(gaze.get("Confidence")),
        },
    }


def average_calibration(samples: list[dict]) -> dict:
    valid_samples = [
        sample
        for sample in samples
        if "error" not in sample
        and sample.get("head") is not None
        and sample.get("gaze") is not None
    ]
    if not valid_samples:
        raise RuntimeError(
            "캘리브레이션 이미지에서 얼굴을 감지하지 못했습니다. "
            "조명과 카메라 위치를 확인해 주세요."
        )

    def average(section: str, key: str) -> float:
        values = [
            sample[section][key]
            for sample in valid_samples
            if sample[section].get(key) is not None
        ]
        if not values:
            raise RuntimeError(f"캘리브레이션 {section}.{key} 값이 없습니다.")
        return round(sum(values) / len(values), 2)

    return {
        "valid_sample_count": len(valid_samples),
        "head": {
            "yaw": average("head", "yaw"),
            "pitch": average("head", "pitch"),
        },
        "gaze": {
            "yaw": average("gaze", "yaw"),
            "pitch": average("gaze", "pitch"),
        },
    }


def calculate_calibrated(raw: dict, calibration: dict) -> dict | None:
    if raw.get("head") is None or raw.get("gaze") is None:
        return None
    return {
        "head": {
            "yaw": round(raw["head"]["yaw"] - calibration["head"]["yaw"], 2),
            "pitch": round(
                raw["head"]["pitch"] - calibration["head"]["pitch"], 2
            ),
        },
        "gaze": {
            "yaw": round(raw["gaze"]["yaw"] - calibration["gaze"]["yaw"], 2),
            "pitch": round(
                raw["gaze"]["pitch"] - calibration["gaze"]["pitch"], 2
            ),
        },
    }


def highest_severity(*severities: str) -> str:
    """입력된 위험도 중 가장 높은 값을 반환한다."""

    return max(
        severities,
        key=lambda severity: SEVERITY_PRIORITY.get(severity, -1),
    )


def classify_eye_direction(yaw: float, pitch: float) -> str:
    """캘리브레이션 상대 Eye Direction을 9방향으로 분류한다."""

    horizontal = "CENTER"
    vertical = "CENTER"

    if yaw <= -EYE_YAW_THRESHOLD:
        horizontal = "LEFT"
    elif yaw >= EYE_YAW_THRESHOLD:
        horizontal = "RIGHT"

    if pitch <= -EYE_PITCH_THRESHOLD:
        vertical = "DOWN"
    elif pitch >= EYE_PITCH_THRESHOLD:
        vertical = "UP"

    if horizontal == "CENTER":
        return vertical
    if vertical == "CENTER":
        return horizontal
    return f"{vertical}_{horizontal}"


def classify_eye(
    raw: dict,
    calibrated: dict,
    previous_consecutive_away_count: int,
) -> dict:
    """고개와 독립적으로 눈 시선 신뢰도와 연속 이탈을 판정한다."""

    confidence = float(raw["gaze"].get("confidence") or 0.0)
    reliable = confidence >= MINIMUM_EYE_CONFIDENCE

    if not reliable:
        return {
            "reliable": False,
            "direction": "UNKNOWN",
            "away": False,
            "consecutive_away_count": 0,
            "severity": "UNKNOWN",
        }

    direction = classify_eye_direction(
        calibrated["gaze"]["yaw"],
        calibrated["gaze"]["pitch"],
    )
    away = direction != "CENTER"
    consecutive_count = (
        previous_consecutive_away_count + 1 if away else 0
    )

    if consecutive_count >= 3:
        severity = "HIGH"
    elif consecutive_count == 2:
        severity = "MEDIUM"
    elif consecutive_count == 1:
        severity = "LOW"
    else:
        severity = "NORMAL"

    return {
        "reliable": True,
        "direction": direction,
        "away": away,
        "consecutive_away_count": consecutive_count,
        "severity": severity,
    }


def classify_head_yaw(yaw: float) -> dict:
    """캘리브레이션 상대 Head Yaw의 방향과 위험도를 판정한다."""

    absolute_yaw = abs(yaw)
    direction = "CENTER"
    if yaw > HEAD_YAW_NORMAL_THRESHOLD:
        direction = "LEFT"
    elif yaw < -HEAD_YAW_NORMAL_THRESHOLD:
        direction = "RIGHT"

    if absolute_yaw > HEAD_YAW_MEDIUM_THRESHOLD:
        severity = "HIGH"
    elif absolute_yaw > HEAD_YAW_LOW_THRESHOLD:
        severity = "MEDIUM"
    elif absolute_yaw > HEAD_YAW_NORMAL_THRESHOLD:
        severity = "LOW"
    else:
        severity = "NORMAL"

    return {
        "value": yaw,
        "direction": direction,
        "severity": severity,
    }


def classify_head_pitch(pitch: float) -> dict:
    """캘리브레이션 상대 Head Pitch의 방향과 위험도를 판정한다."""

    if pitch < HEAD_PITCH_DOWN_HIGH_THRESHOLD:
        direction = "DOWN"
        severity = "HIGH"
    elif pitch < HEAD_PITCH_DOWN_MEDIUM_THRESHOLD:
        direction = "DOWN"
        severity = "MEDIUM"
    elif pitch > HEAD_PITCH_UP_HIGH_THRESHOLD:
        direction = "UP"
        severity = "HIGH"
    elif pitch > HEAD_PITCH_UP_MEDIUM_THRESHOLD:
        direction = "UP"
        severity = "MEDIUM"
    elif pitch > HEAD_PITCH_UP_LOW_THRESHOLD:
        direction = "UP"
        severity = "LOW"
    else:
        direction = "CENTER"
        severity = "NORMAL"

    return {
        "value": pitch,
        "direction": direction,
        "severity": severity,
    }


def classify_head(calibrated: dict) -> dict:
    """눈과 독립적으로 Head Yaw와 Pitch를 판정한다."""

    yaw_result = classify_head_yaw(calibrated["head"]["yaw"])
    pitch_result = classify_head_pitch(calibrated["head"]["pitch"])
    return {
        "yaw": yaw_result,
        "pitch": pitch_result,
        "severity": highest_severity(
            yaw_result["severity"],
            pitch_result["severity"],
        ),
    }


def calculate_severity(
    raw: dict,
    calibrated: dict | None,
    previous_consecutive_eye_away_count: int,
) -> dict:
    """눈 우선 정책으로 눈·고개 독립 결과와 최종 위험도를 계산한다."""

    if calibrated is None:
        return {
            "severity": "UNKNOWN",
            "reason": "FACE_NOT_ANALYZED",
            "eye": None,
            "head": None,
        }

    eye_result = classify_eye(
        raw=raw,
        calibrated=calibrated,
        previous_consecutive_away_count=(
            previous_consecutive_eye_away_count
        ),
    )
    head_result = classify_head(calibrated)

    if eye_result["reliable"]:
        if eye_result["away"]:
            final_severity = highest_severity(
                eye_result["severity"],
                head_result["severity"],
            )
            reason = (
                "EYE_AND_HEAD_HIGHEST"
                if head_result["severity"] != "NORMAL"
                else "EYE_AWAY"
            )
        elif head_result["severity"] != "NORMAL":
            final_severity = "LOW"
            reason = "EYE_CENTER_HEAD_AWAY"
        else:
            final_severity = "NORMAL"
            reason = "EYE_AND_HEAD_CENTER"
    else:
        final_severity = head_result["severity"]
        reason = "HEAD_ONLY_EYE_UNRELIABLE"

    return {
        "severity": final_severity,
        "reason": reason,
        "eye": eye_result,
        "head": head_result,
    }


def put_camera_message(frame, message: str) -> None:
    height, width = frame.shape[:2]
    scale = max(0.6, width / 1200)
    thickness = max(1, int(scale * 2))
    text_size = cv2.getTextSize(
        message, cv2.FONT_HERSHEY_SIMPLEX, scale, thickness
    )[0]
    x = max(10, (width - text_size[0]) // 2)
    cv2.putText(
        frame,
        message,
        (x, 40),
        cv2.FONT_HERSHEY_SIMPLEX,
        scale,
        (0, 0, 0),
        thickness + 3,
        cv2.LINE_AA,
    )
    cv2.putText(
        frame,
        message,
        (x, 40),
        cv2.FONT_HERSHEY_SIMPLEX,
        scale,
        (255, 255, 255),
        thickness,
        cv2.LINE_AA,
    )


def read_mirrored_frame(camera):
    """카메라 프레임을 읽고 좌우 반전해 거울 모드로 반환한다."""
    success, frame = camera.read()
    if not success:
        return False, None
    return True, cv2.flip(frame, 1)


def wait_for_space(camera, message: str) -> None:
    """카메라 화면을 유지하면서 Space 입력을 기다린다. ESC는 즉시 종료한다."""
    while True:
        success, frame = read_mirrored_frame(camera)
        if not success:
            raise RuntimeError("카메라 대기 화면을 읽지 못했습니다.")
        put_camera_message(frame, message)
        cv2.imshow("Gaze / Head Calibration Test", frame)
        key = cv2.waitKey(1) & 0xFF
        if key == 32:
            return
        if key == 27:
            raise KeyboardInterrupt


def wait_for_escape(camera, message: str) -> None:
    """마지막 결과 화면은 사용자가 ESC를 누를 때까지 유지한다."""
    while True:
        success, frame = read_mirrored_frame(camera)
        if not success:
            raise RuntimeError("카메라 종료 화면을 읽지 못했습니다.")
        put_camera_message(frame, message)
        cv2.imshow("Gaze / Head Calibration Test", frame)
        if cv2.waitKey(1) & 0xFF == 27:
            return


def capture_calibration(camera, calibration_dir: Path) -> list[Path]:
    print("맥북 내장 캠이 켜지고 캘리베이션을 시작합니다.")
    print("3초 동안 화면 중앙의 점을 바라봐 주세요.")

    paths = []
    start = time.monotonic()
    next_capture_index = 0
    interval = CALIBRATION_SECONDS / CALIBRATION_IMAGE_COUNT

    while time.monotonic() - start < CALIBRATION_SECONDS:
        success, frame = read_mirrored_frame(camera)
        if not success:
            raise RuntimeError("카메라 프레임을 읽지 못했습니다.")

        elapsed = time.monotonic() - start
        while (
            next_capture_index < CALIBRATION_IMAGE_COUNT
            and elapsed >= next_capture_index * interval
        ):
            path = calibration_dir / f"calibration_{next_capture_index + 1:02d}.jpg"
            if not cv2.imwrite(str(path), frame):
                raise OSError(f"캘리브레이션 이미지를 저장하지 못했습니다: {path}")
            paths.append(path)
            next_capture_index += 1

        display = frame.copy()
        height, width = display.shape[:2]
        radius = max(8, min(width, height) // 60)
        cv2.circle(display, (width // 2, height // 2), radius, (0, 0, 255), -1)
        put_camera_message(display, "Calibration: look at the center dot")
        cv2.imshow("Gaze / Head Calibration Test", display)
        if cv2.waitKey(1) & 0xFF == 27:
            raise KeyboardInterrupt

    if len(paths) != CALIBRATION_IMAGE_COUNT:
        raise RuntimeError(
            f"캘리브레이션 캡처 수가 부족합니다: {len(paths)}/"
            f"{CALIBRATION_IMAGE_COUNT}"
        )
    return paths


def capture_test(camera, output_dir: Path, captures_dir: Path) -> tuple[Path, list[dict]]:
    success, first_frame = read_mirrored_frame(camera)
    if not success:
        raise RuntimeError("테스트 시작 프레임을 읽지 못했습니다.")

    height, width = first_frame.shape[:2]
    camera_fps = camera.get(cv2.CAP_PROP_FPS)
    video_fps = camera_fps if 1 <= camera_fps <= 120 else 30.0
    video_path = output_dir / "recording.mp4"
    writer = cv2.VideoWriter(
        str(video_path),
        cv2.VideoWriter_fourcc(*"mp4v"),
        video_fps,
        (width, height),
    )
    if not writer.isOpened():
        raise RuntimeError("녹화 파일을 생성하지 못했습니다.")

    print("캘리브레이션이 끝났습니다. 1분 테스트를 진행합니다.")
    captures = []
    start = time.monotonic()
    next_capture_index = 0

    try:
        frame = first_frame
        while time.monotonic() - start < TEST_SECONDS:
            elapsed = time.monotonic() - start
            writer.write(frame)

            while (
                next_capture_index < TEST_IMAGE_COUNT
                and elapsed >= next_capture_index
            ):
                capture_path = captures_dir / f"capture_{next_capture_index + 1:03d}.jpg"
                if not cv2.imwrite(str(capture_path), frame):
                    raise OSError(f"테스트 이미지를 저장하지 못했습니다: {capture_path}")
                captures.append(
                    {
                        "index": next_capture_index + 1,
                        "elapsed_seconds": round(elapsed, 3),
                        "path": capture_path,
                    }
                )
                next_capture_index += 1

            display = frame.copy()
            remaining = max(0, int(TEST_SECONDS - elapsed + 0.999))
            put_camera_message(display, f"Test recording: {remaining}s remaining")
            cv2.imshow("Gaze / Head Calibration Test", display)
            if cv2.waitKey(1) & 0xFF == 27:
                raise KeyboardInterrupt

            success, frame = read_mirrored_frame(camera)
            if not success:
                raise RuntimeError("테스트 중 카메라 프레임을 읽지 못했습니다.")
    finally:
        writer.release()

    if len(captures) != TEST_IMAGE_COUNT:
        raise RuntimeError(
            f"테스트 캡처 수가 부족합니다: {len(captures)}/{TEST_IMAGE_COUNT}"
        )
    return video_path, captures


def load_font(image_width: int):
    font_size = max(15, image_width // 48)
    for font_path in (
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ):
        try:
            return ImageFont.truetype(font_path, font_size)
        except OSError:
            continue
    return ImageFont.load_default()


def annotate_result(
    source_path: Path,
    output_path: Path,
    calibration: dict,
    result: dict,
) -> None:
    with Image.open(source_path) as opened:
        image = opened.convert("RGB")

    if result.get("calibrated") is None:
        lines = [
            "Severity: UNKNOWN",
            "Face not detected or analysis failed",
        ]
    else:
        raw = result["raw"]
        calibrated = result["calibrated"]
        lines = [
            (
                f"Severity: {result['severity']} "
                f"(reason={result['severity_reason']})"
            ),
            (
                f"Head calibration: yaw={calibration['head']['yaw']}, "
                f"pitch={calibration['head']['pitch']}"
            ),
            (
                f"Gaze calibration: yaw={calibration['gaze']['yaw']}, "
                f"pitch={calibration['gaze']['pitch']}"
            ),
            (
                f"AWS head: yaw={raw['head']['yaw']}, "
                f"pitch={raw['head']['pitch']}"
            ),
            (
                f"Calibrated head: yaw={calibrated['head']['yaw']}, "
                f"pitch={calibrated['head']['pitch']}"
            ),
            (
                f"AWS gaze: yaw={raw['gaze']['yaw']}, "
                f"pitch={raw['gaze']['pitch']}"
            ),
            (
                f"Calibrated gaze: yaw={calibrated['gaze']['yaw']}, "
                f"pitch={calibrated['gaze']['pitch']}"
            ),
            (
                f"Eye: direction={result['eye_result']['direction']}, "
                f"reliable={result['eye_result']['reliable']}, "
                f"severity={result['eye_result']['severity']}"
            ),
            (
                f"Head: yaw={result['head_result']['yaw']['severity']}, "
                f"pitch={result['head_result']['pitch']['severity']}, "
                f"severity={result['head_result']['severity']}"
            ),
        ]

    draw = ImageDraw.Draw(image)
    font = load_font(image.width)
    margin = max(10, image.width // 100)
    y = margin
    for line in lines:
        draw.text(
            (margin, y),
            line,
            font=font,
            fill="red",
            stroke_width=2,
            stroke_fill="white",
        )
        box = draw.textbbox((margin, y), line, font=font, stroke_width=2)
        y = box[3] + max(4, image.height // 220)
    image.save(output_path, quality=95)


def analyze_calibration(client, paths: list[Path]) -> tuple[list[dict], dict]:
    samples = []
    print("캘리브레이션 값을 계산합니다.")
    for index, path in enumerate(paths, start=1):
        try:
            sample = detect_gaze_pose(client, path.read_bytes())
            sample["image_file"] = path.name
        except (BotoCoreError, ClientError, OSError, ValueError) as error:
            sample = {"image_file": path.name, "error": str(error)}
        samples.append(sample)
        print(f"  캘리브레이션 분석: {index}/{len(paths)}")
    return samples, average_calibration(samples)


def analyze_test_images(
    client,
    captures: list[dict],
    annotated_dir: Path,
    calibration: dict,
) -> list[dict]:
    results = []
    consecutive_eye_away_count = 0
    print("캡처 이미지의 AWS 분석을 시작합니다.")
    for index, capture in enumerate(captures, start=1):
        path = capture["path"]
        result = {
            "index": capture["index"],
            "image_file": path.name,
            "annotated_image_file": path.name,
            "elapsed_seconds": capture["elapsed_seconds"],
        }
        try:
            raw = detect_gaze_pose(client, path.read_bytes())
            calibrated = calculate_calibrated(raw, calibration)
            judgment = calculate_severity(
                raw=raw,
                calibrated=calibrated,
                previous_consecutive_eye_away_count=(
                    consecutive_eye_away_count
                ),
            )
            eye_result = judgment["eye"]
            consecutive_eye_away_count = (
                eye_result["consecutive_away_count"]
                if eye_result is not None
                else 0
            )
            result.update(
                {
                    "raw": raw,
                    "calibrated": calibrated,
                    "eye_result": eye_result,
                    "head_result": judgment["head"],
                    "severity": judgment["severity"],
                    "severity_reason": judgment["reason"],
                }
            )
        except (BotoCoreError, ClientError, OSError, ValueError) as error:
            result.update(
                {
                    "raw": None,
                    "calibrated": None,
                    "eye_result": None,
                    "head_result": None,
                    "severity": "UNKNOWN",
                    "severity_reason": "ANALYSIS_ERROR",
                    "error": str(error),
                }
            )
            consecutive_eye_away_count = 0

        annotate_result(path, annotated_dir / path.name, calibration, result)
        results.append(result)
        print(f"  테스트 이미지 분석: {index}/{len(captures)}")
    return results


def main() -> None:
    started_at = datetime.now().astimezone()
    output_dir = (
        OUTPUT_ROOT.expanduser().resolve()
        / started_at.strftime("test_%Y%m%d_%H%M%S")
    )
    calibration_dir = output_dir / "calibration"
    captures_dir = output_dir / "captures"
    annotated_dir = output_dir / "annotated"
    for directory in (calibration_dir, captures_dir, annotated_dir):
        directory.mkdir(parents=True, exist_ok=True)

    client = create_rekognition_client()
    camera = cv2.VideoCapture(CAMERA_INDEX, cv2.CAP_AVFOUNDATION)
    if not camera.isOpened():
        camera = cv2.VideoCapture(CAMERA_INDEX)
    if not camera.isOpened():
        raise RuntimeError(
            "맥북 내장 카메라를 열지 못했습니다. 카메라 접근 권한을 확인해 주세요."
        )

    try:
        print("카메라가 준비되었습니다. Space를 누르면 캘리브레이션을 시작합니다.")
        print("창을 닫으려면 언제든 ESC를 누르세요.")
        wait_for_space(camera, "Press SPACE to start calibration")

        calibration_paths = capture_calibration(camera, calibration_dir)
        calibration_samples, calibration = analyze_calibration(
            client, calibration_paths
        )
        video_path, captures = capture_test(camera, output_dir, captures_dir)

        print("60장 캡처가 완료되었습니다. 분석을 진행합니다.")
        test_results = analyze_test_images(
            client, captures, annotated_dir, calibration
        )
        output_data = {
            "started_at": started_at.isoformat(),
            "settings": {
                "camera_index": CAMERA_INDEX,
                "calibration_seconds": CALIBRATION_SECONDS,
                "calibration_image_count": CALIBRATION_IMAGE_COUNT,
                "test_seconds": TEST_SECONDS,
                "test_image_count": TEST_IMAGE_COUNT,
                "severity_rule": "calibrated eye-priority independent eye/head",
                "eye": {
                    "minimum_confidence": MINIMUM_EYE_CONFIDENCE,
                    "yaw_threshold": EYE_YAW_THRESHOLD,
                    "pitch_threshold": EYE_PITCH_THRESHOLD,
                    "consecutive_severity": {
                        "1": "LOW",
                        "2": "MEDIUM",
                        "3_or_more": "HIGH",
                    },
                },
                "head": {
                    "yaw": {
                        "normal_max": HEAD_YAW_NORMAL_THRESHOLD,
                        "low_max": HEAD_YAW_LOW_THRESHOLD,
                        "medium_max": HEAD_YAW_MEDIUM_THRESHOLD,
                        "above_medium": "HIGH",
                    },
                    "pitch": {
                        "down_medium_below": (
                            HEAD_PITCH_DOWN_MEDIUM_THRESHOLD
                        ),
                        "down_high_below": (
                            HEAD_PITCH_DOWN_HIGH_THRESHOLD
                        ),
                        "up_low_above": HEAD_PITCH_UP_LOW_THRESHOLD,
                        "up_medium_above": (
                            HEAD_PITCH_UP_MEDIUM_THRESHOLD
                        ),
                        "up_high_above": HEAD_PITCH_UP_HIGH_THRESHOLD,
                    },
                },
                "priority": (
                    "eye and head away use highest severity; "
                    "eye center caps head-only deviation at LOW"
                ),
            },
            "files": {
                "video": video_path.name,
                "calibration_dir": calibration_dir.name,
                "captures_dir": captures_dir.name,
                "annotated_dir": annotated_dir.name,
            },
            "calibration": calibration,
            "calibration_samples": calibration_samples,
            "results": test_results,
        }
        json_path = output_dir / "analysis.json"
        with json_path.open("w", encoding="utf-8") as file:
            json.dump(output_data, file, ensure_ascii=False, indent=2)

        print("캡처와 분석이 모두 완료되었습니다.")
        print("Space를 눌러 테스트를 종료 상태로 전환하세요.")
        wait_for_space(camera, "Completed - press SPACE to finish")

        print("테스트가 종료되었습니다. ESC를 누르면 창이 닫힙니다.")
        print(f"결과 폴더: {output_dir}")
        print(f"녹화 파일: {video_path}")
        print(f"분석 JSON: {json_path}")
        wait_for_escape(camera, "Finished - press ESC to close")
    except KeyboardInterrupt:
        print("사용자가 ESC를 눌러 테스트를 종료했습니다.")
    finally:
        camera.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
