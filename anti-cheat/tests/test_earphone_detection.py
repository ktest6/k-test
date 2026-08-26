"""시험 전 이어폰 검사의 자세 게이트 테스트."""

import unittest
from unittest.mock import patch

from app.core.config import settings
from modules.earphone_detection.analyzer import analyze_ear_visibility

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
            "threshold": settings.earphone_confidence_threshold,
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


if __name__ == "__main__":
    unittest.main()
