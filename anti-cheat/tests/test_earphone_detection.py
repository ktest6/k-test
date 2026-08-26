"""시험 전 이어폰 검사의 자세 게이트 테스트."""

import asyncio
from io import BytesIO
import unittest
from unittest.mock import patch

from fastapi import UploadFile

from app.api.earphone_detection import detect_earphone_api
from app.core.config import settings
from modules.earphone_detection.analyzer import (
    analyze_ear_visibility,
    analyze_earphone_detection,
)

try:
    from modules.earphone_detection.service import analyze_earphone_image
except ModuleNotFoundError:
    analyze_earphone_image = None


class EarVisibilityTest(unittest.TestCase):
    """Pose.Yaw 기반 귀 노출 판단을 검증한다."""

    def test_front_face_requires_ear_visibility(self) -> None:
        result = analyze_ear_visibility(
            {"FaceDetails": [{"Pose": {"Yaw": 0.0}}]},
        )

        self.assertFalse(result["ear_visible"])
        self.assertEqual(result["yaw"], 0.0)

    def test_turned_face_exposes_ear(self) -> None:
        yaw = settings.pre_exam_earphone_head_yaw_threshold
        result = analyze_ear_visibility(
            {"FaceDetails": [{"Pose": {"Yaw": -yaw}}]},
        )

        self.assertTrue(result["ear_visible"])

    def test_missing_face_requires_retry(self) -> None:
        result = analyze_ear_visibility({"FaceDetails": []})

        self.assertFalse(result["ear_visible"])
        self.assertEqual(result["face_count"], 0)
        self.assertIsNone(result["yaw"])

    def test_multiple_faces_require_retry(self) -> None:
        result = analyze_ear_visibility(
            {
                "FaceDetails": [
                    {"Pose": {"Yaw": 60.0}},
                    {"Pose": {"Yaw": -60.0}},
                ],
            },
        )

        self.assertFalse(result["ear_visible"])
        self.assertEqual(result["face_count"], 2)

    @unittest.skipIf(
        analyze_earphone_image is None,
        "AWS dependencies are not installed",
    )
    @patch("modules.earphone_detection.service.detect_earphone")
    @patch("modules.earphone_detection.service.detect_faces")
    def test_label_detection_is_skipped_for_front_face(
        self,
        detect_faces_mock,
        detect_earphone_mock,
    ) -> None:
        detect_faces_mock.return_value = {
            "FaceDetails": [{"Pose": {"Yaw": 5.0}}],
        }

        assert analyze_earphone_image is not None
        result = analyze_earphone_image(b"valid-image")

        self.assertFalse(result["ear_visible"])
        self.assertFalse(result["earphone_detected"])
        detect_faces_mock.assert_called_once_with(
            image_bytes=b"valid-image",
        )
        detect_earphone_mock.assert_not_called()

    @unittest.skipIf(
        analyze_earphone_image is None,
        "AWS dependencies are not installed",
    )
    @patch("modules.earphone_detection.service.analyze_earphone_detection")
    @patch("modules.earphone_detection.service.detect_earphone")
    @patch("modules.earphone_detection.service.detect_faces")
    def test_label_detection_runs_after_yaw_threshold(
        self,
        detect_faces_mock,
        detect_earphone_mock,
        analyze_detection_mock,
    ) -> None:
        yaw = settings.pre_exam_earphone_head_yaw_threshold
        detect_faces_mock.return_value = {
            "FaceDetails": [{"Pose": {"Yaw": yaw}}],
        }
        detect_earphone_mock.return_value = {"matched_labels": []}
        analyze_detection_mock.return_value = {
            "earphone_detected": False,
            "label": None,
            "confidence": 0.0,
            "threshold": settings.pre_exam_earphone_confidence_threshold,
            "message": "이어폰이 탐지되지 않았습니다.",
        }

        assert analyze_earphone_image is not None
        result = analyze_earphone_image(b"valid-image")

        self.assertTrue(result["ear_visible"])
        detect_faces_mock.assert_called_once_with(
            image_bytes=b"valid-image",
        )
        detect_earphone_mock.assert_called_once_with(
            image_bytes=b"valid-image",
        )
        analyze_detection_mock.assert_called_once_with(
            detection_result={"matched_labels": []},
        )


class PreExamEarphoneConfidenceTest(unittest.TestCase):
    """시험 전 이어폰 신뢰도 임계값을 검증한다."""

    def test_confidence_below_pre_exam_threshold_is_rejected(self) -> None:
        result = analyze_earphone_detection(
            {
                "matched_labels": [
                    {"label": "Earbuds", "confidence": 54.99},
                ],
            },
        )

        self.assertFalse(result["earphone_detected"])
        self.assertEqual(
            result["threshold"],
            settings.pre_exam_earphone_confidence_threshold,
        )

    def test_confidence_at_pre_exam_threshold_is_accepted(self) -> None:
        threshold = settings.pre_exam_earphone_confidence_threshold
        result = analyze_earphone_detection(
            {
                "matched_labels": [
                    {"label": "Earbuds", "confidence": threshold},
                ],
            },
        )

        self.assertTrue(result["earphone_detected"])
        self.assertEqual(result["confidence"], threshold)
        self.assertEqual(result["threshold"], threshold)


class EarphoneDetectionApiTest(unittest.TestCase):
    """시험 전 이어폰 API 응답 계약을 검증한다."""

    @patch("app.api.earphone_detection.analyze_earphone_image")
    def test_response_exposes_pre_exam_confidence_threshold(
        self,
        analyze_image_mock,
    ) -> None:
        threshold = settings.pre_exam_earphone_confidence_threshold
        analyze_image_mock.side_effect = [
            {
                "ear_visible": True,
                "earphone_detected": False,
                "yaw": 60.0,
                "yaw_threshold": 50.0,
                "label": None,
                "confidence": 0.0,
                "threshold": threshold,
            },
            {
                "ear_visible": True,
                "earphone_detected": False,
                "yaw": -60.0,
                "yaw_threshold": 50.0,
                "label": None,
                "confidence": 0.0,
                "threshold": threshold,
            },
        ]

        response = asyncio.run(
            detect_earphone_api(
                exam_id="7",
                examinee_id="9",
                left_ear_image=UploadFile(
                    filename="left.jpg",
                    file=BytesIO(b"left"),
                ),
                right_ear_image=UploadFile(
                    filename="right.jpg",
                    file=BytesIO(b"right"),
                ),
            )
        )

        self.assertEqual(response.threshold, threshold)
        self.assertTrue(response.inspection_complete)


if __name__ == "__main__":
    unittest.main()
