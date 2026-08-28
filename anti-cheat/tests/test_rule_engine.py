"""개별 부정행위 규칙과 최종 행동 집계를 검증한다."""

import unittest

from modules.cheating_detection.rule_engine import (
    evaluate_rules,
    evaluate_gaze_rules,
)
from modules.cheating_detection.gaze_monitor import analyze_gaze_monitor
from modules.cheating_detection.gaze_state import update_gaze_state
from modules.cheating_detection.service import (
    validate_identity_check_request,
)
from modules.common.exceptions import MonitoringError


class IndependentHeadRuleTest(unittest.TestCase):
    def test_unreliable_eye_does_not_block_head_rule(self) -> None:
        gaze_result = analyze_gaze_monitor(
            face_monitor_result={
                "face_count": 1,
                "face_details": [
                    {
                        "EyeDirection": {
                            "Yaw": 0.0,
                            "Pitch": 0.0,
                            "Confidence": 10.0,
                        },
                        "Pose": {
                            "Yaw": 30.0,
                            "Pitch": 0.0,
                            "Roll": 0.0,
                        },
                    }
                ],
            },
            eye_yaw_threshold=15.0,
            eye_pitch_threshold=15.0,
            head_yaw_threshold=25.0,
            head_pitch_threshold=20.0,
            minimum_eye_confidence=80.0,
        )
        gaze_result["state"] = update_gaze_state(
            gaze_monitor_result=gaze_result,
            elapsed_ms=1000,
            capture_sequence=1,
            persistent_count_threshold=3,
        )

        rules = evaluate_gaze_rules(gaze_result)

        self.assertEqual(gaze_result["event_type"], "GAZE_AWAY")
        self.assertIs(gaze_result["eye_direction_reliable"], False)
        self.assertIs(gaze_result["head_pose_away"], True)
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0]["rule_id"], "RULE_HEAD_POSE_AWAY")

    def test_individual_events_share_one_highest_action(self) -> None:
        result = evaluate_rules(
            {
                "face_monitor": {"event_type": "FACE_NORMAL"},
                "gaze_monitor": None,
                "identity_monitor": None,
                "object_monitor": {
                    "detected_objects": [
                        {"label": "Mobile Phone", "confidence": 99.0},
                        {"label": "Earbuds", "confidence": 98.0},
                    ]
                },
            }
        )

        self.assertEqual(result["rule_count"], 2)
        self.assertEqual(
            {
                rule["event_type"]
                for rule in result["applied_rules"]
            },
            {"PHONE_DETECTED", "EARPHONE_DETECTED"},
        )
        self.assertEqual(result["severity"], "HIGH")
        self.assertEqual(result["decision"], "CREATE_CLIP")
        self.assertIs(result["create_clip"], True)


class IdentityCheckRequestTest(unittest.TestCase):
    def test_requested_identity_check_requires_reference_image(self) -> None:
        with self.assertRaises(MonitoringError) as raised:
            validate_identity_check_request(
                run_identity_check=True,
                reference_image_bytes=None,
            )

        self.assertEqual(
            raised.exception.code,
            "IDENTITY_REFERENCE_IMAGE_REQUIRED",
        )

    def test_unrequested_identity_check_allows_no_reference_image(self) -> None:
        validate_identity_check_request(
            run_identity_check=False,
            reference_image_bytes=None,
        )


if __name__ == "__main__":
    unittest.main()
