"""눈과 고개 캘리브레이션 중심값을 검증한다."""

import unittest

from modules.cheating_detection.gaze_calibration import (
    create_gaze_calibration,
)


class GazeCalibrationTest(unittest.TestCase):
    def test_returns_eye_and_head_median_centers(self) -> None:
        samples = [
            {
                "face_count": 1,
                "face_details": [
                    {
                        "EyeDirection": {
                            "Yaw": eye_yaw,
                            "Pitch": eye_pitch,
                            "Confidence": 99.0,
                        },
                        "Pose": {
                            "Yaw": head_yaw,
                            "Pitch": head_pitch,
                            "Roll": 0.0,
                        },
                    }
                ],
            }
            for eye_yaw, eye_pitch, head_yaw, head_pitch in (
                (-2.0, -8.0, -1.0, 8.0),
                (0.0, -6.0, 1.0, 10.0),
                (2.0, -4.0, 3.0, 12.0),
            )
        ]

        result = create_gaze_calibration(
            exam_id="exam-1",
            examinee_id="examinee-1",
            face_monitor_results=samples,
            minimum_eye_confidence=80.0,
            minimum_sample_count=3,
        )

        self.assertEqual(result["sample_count"], 3)
        self.assertEqual(result["eye_yaw_center"], 0.0)
        self.assertEqual(result["eye_pitch_center"], -6.0)
        self.assertEqual(result["head_yaw_center"], 1.0)
        self.assertEqual(result["head_pitch_center"], 10.0)


if __name__ == "__main__":
    unittest.main()
