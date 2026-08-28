"""보정 Head Pose의 각도 등급 경계를 검증한다."""

import unittest

from modules.cheating_detection.gaze_monitor import (
    classify_head_pose_level,
)


def classify(yaw: float, pitch: float) -> str:
    return classify_head_pose_level(
        head_pose={"yaw": yaw, "pitch": pitch, "roll": 0.0},
        yaw_slight_threshold=10.0,
        yaw_large_threshold=20.0,
        pitch_down_slight_threshold=-5.0,
        pitch_down_large_threshold=-10.0,
        pitch_up_slight_threshold=10.0,
        pitch_up_large_threshold=20.0,
    )


class GazePosePolicyTest(unittest.TestCase):
    def test_yaw_boundaries(self) -> None:
        for value, expected in (
            (10.0, "NORMAL"),
            (10.01, "SLIGHT"),
            (-20.0, "SLIGHT"),
            (20.01, "LARGE"),
        ):
            with self.subTest(value=value):
                self.assertEqual(classify(value, 0.0), expected)

    def test_pitch_boundaries(self) -> None:
        for value, expected in (
            (-5.0, "NORMAL"),
            (-5.01, "SLIGHT"),
            (-10.0, "SLIGHT"),
            (-10.01, "LARGE"),
            (10.0, "NORMAL"),
            (10.01, "SLIGHT"),
            (20.0, "SLIGHT"),
            (20.01, "LARGE"),
        ):
            with self.subTest(value=value):
                self.assertEqual(classify(0.0, value), expected)


if __name__ == "__main__":
    unittest.main()
